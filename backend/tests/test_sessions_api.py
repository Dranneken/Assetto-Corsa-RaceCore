from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from racecore.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from racecore.config import settings

    monkeypatch.setattr(settings, "admin_username", "test-admin")
    monkeypatch.setattr(settings, "admin_password", SecretStr("test-password"))
    with TestClient(app) as test_client:
        test_client.auth = ("test-admin", "test-password")
        yield test_client


def create_session(client: TestClient) -> tuple[str, dict]:
    driver_id = f"driver-{uuid4()}"
    config = {
        "name": "Test race",
        "track_id": "spa",
        "track_layout": "gp",
        "session_type": "race",
        "planned_laps": 10,
        "entries": [
            {
                "car_id": "car-1",
                "driver_id": driver_id,
                "driver_name": "Test Driver",
                "car_model": "ks_porsche_911_gt3_r",
                "class_name": "GT3",
            }
        ],
    }
    response = client.post("/api/v1/sessions", json={"config": config})
    assert response.status_code == 201
    return response.json()["session_id"], config


def test_create_session_stores_configuration_snapshot(client: TestClient) -> None:
    session_id, config = create_session(client)

    response = client.get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 200
    session = response.json()
    assert session["config"]["name"] == config["name"]
    assert session["config"]["track_id"] == config["track_id"]
    assert session["config"]["entries"][0]["driver_id"] == config["entries"][0]["driver_id"]
    assert session["state"] == "pre_race"
    assert session["car_states"]["car-1"]["driver_name"] == "Test Driver"
    assert [event["event_type"] for event in session["audit_events"]] == ["session.created"]


def test_session_commands_follow_race_lifecycle_and_write_audit_events(
    client: TestClient,
) -> None:
    session_id, _ = create_session(client)
    transitions = [
        ("start", "formation"),
        ("green", "green"),
        ("yellow", "yellow"),
        ("safety_car", "safety_car"),
        ("resume", "green"),
        ("red_flag", "red_flag"),
        ("resume", "formation"),
        ("finish", "finished"),
        ("post_race", "post_race"),
    ]

    for command, expected_state in transitions:
        response = client.post(f"/api/v1/sessions/{session_id}/commands", json={"command": command})
        assert response.status_code == 200
        assert response.json()["session"]["state"] == expected_state
        assert response.json()["event"]["event_type"] == f"session.command.{command}"

    session = client.get(f"/api/v1/sessions/{session_id}").json()
    assert len(session["audit_events"]) == len(transitions) + 1


def test_pause_resume_and_reset_restore_pre_race_state(client: TestClient) -> None:
    session_id, _ = create_session(client)
    for command, expected_state in [
        ("pause", "paused"),
        ("resume", "pre_race"),
        ("reset", "pre_race"),
    ]:
        response = client.post(f"/api/v1/sessions/{session_id}/commands", json={"command": command})
        assert response.status_code == 200
        assert response.json()["session"]["state"] == expected_state


def test_restart_returns_session_to_formation_and_clears_live_car_state(
    client: TestClient,
) -> None:
    session_id, _ = create_session(client)
    client.post(f"/api/v1/sessions/{session_id}/commands", json={"command": "start"})
    client.patch(
        f"/api/v1/sessions/{session_id}/cars/car-1",
        json={"current_lap": 1, "position": 1, "lap_times": [120.5]},
    )

    response = client.post(
        f"/api/v1/sessions/{session_id}/commands", json={"command": "restart"}
    )

    assert response.status_code == 200
    session = response.json()["session"]
    assert session["state"] == "formation"
    assert session["car_states"]["car-1"]["current_lap"] == 0
    assert session["car_states"]["car-1"]["lap_times"] == []


def test_invalid_command_returns_conflict_without_changing_state(client: TestClient) -> None:
    session_id, _ = create_session(client)

    response = client.post(f"/api/v1/sessions/{session_id}/commands", json={"command": "green"})

    assert response.status_code == 409
    assert client.get(f"/api/v1/sessions/{session_id}").json()["state"] == "pre_race"


def test_car_updates_feed_race_state_and_reject_unknown_car(client: TestClient) -> None:
    session_id, _ = create_session(client)

    response = client.patch(
        f"/api/v1/sessions/{session_id}/cars/car-1",
        json={"current_lap": 2, "position": 1, "lap_times": [120.5, 119.2]},
    )

    assert response.status_code == 200
    car = response.json()["leaderboard"][0]
    assert car["current_lap"] == 2
    assert car["position"] == 1
    assert car["connection_status"] == "disconnected"

    missing = client.patch(f"/api/v1/sessions/{session_id}/cars/not-entered", json={"position": 2})
    assert missing.status_code == 404


def test_duplicate_car_ids_are_rejected(client: TestClient) -> None:
    config = {
        "name": "Duplicate entries",
        "track_id": "spa",
        "entries": [
            {
                "car_id": "same-car",
                "driver_id": "driver-1",
                "driver_name": "Driver One",
                "car_model": "car-a",
            },
            {
                "car_id": "same-car",
                "driver_id": "driver-2",
                "driver_name": "Driver Two",
                "car_model": "car-b",
            },
        ],
    }

    response = client.post("/api/v1/sessions", json={"config": config})

    assert response.status_code == 422
