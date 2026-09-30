"""REST endpoints for sessions, commands, and authoritative race state."""

from datetime import datetime
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError

from racecore.api.schemas import (
    CarStateUpdate,
    CommandRequest,
    CommandResponse,
    CreateSessionRequest,
    RaceStateResponse,
    SessionResponse,
)
from racecore.api.security import require_admin
from racecore.domain.sessions import ConnectionStatus, InvalidSessionCommand
from racecore.domain.store import store
from racecore.domain.telemetry import TelemetryPacket, telemetry_collector

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _accept_telemetry(session_id: UUID, packet: TelemetryPacket) -> None:
    session = store.get_session(session_id)
    if session is None:
        raise ValueError("Session not found")
    entry = next((item for item in session.config.entries if item.car_id == packet.car_id), None)
    if entry is None:
        raise ValueError("Car is not configured in this session")
    if entry.driver_id != packet.driver_id:
        raise ValueError("Driver does not match the configured session entry")
    telemetry_collector.record(session_id, packet)
    if store.apply_live_telemetry(session_id, packet) is None:
        raise ValueError("Session or configured car no longer exists")


def _driver_leaderboard(session_id: UUID) -> list[dict[str, object]]:
    session = store.get_session(session_id)
    if session is None:
        return []
    health_by_car = {}
    for health in telemetry_collector.health(session_id, list(session.car_states)):
        health_by_car[health.car_id] = health
        store.set_connection_status(
            session_id, health.car_id, ConnectionStatus(health.connection_status)
        )
    session = store.get_session(session_id)
    if session is None:
        return []
    fields = {
        "car_id",
        "driver_name",
        "class_name",
        "current_lap",
        "position",
        "class_position",
        "gap_to_ahead_seconds",
        "tyre_temperatures_c",
        "pit_status",
        "driver_status",
        "connection_status",
    }
    result = []
    for car in session.leaderboard():
        entry = car.model_dump(include=fields, mode="json")
        health = health_by_car.get(car.car_id)
        entry["ping_ms"] = health.client_round_trip_ms if health else None
        result.append(entry)
    return result


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_session(
    request: CreateSessionRequest,
    actor: str = Header(default="operator", alias="X-RaceCore-Actor"),
) -> SessionResponse:
    session = store.create_session(request.config, actor)
    return SessionResponse.from_session(session)


@router.get("", response_model=list[SessionResponse], dependencies=[Depends(require_admin)])
def list_sessions() -> list[SessionResponse]:
    return [SessionResponse.from_session(session) for session in store.list_sessions()]


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    dependencies=[Depends(require_admin)],
)
def get_session(session_id: UUID) -> SessionResponse:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse.from_session(session)


@router.post(
    "/{session_id}/commands",
    response_model=CommandResponse,
    dependencies=[Depends(require_admin)],
)
def issue_command(
    session_id: UUID,
    request: CommandRequest,
    actor: str = Header(default="operator", alias="X-RaceCore-Actor"),
) -> CommandResponse:
    try:
        session, event = store.command(session_id, request.command, actor)
    except InvalidSessionCommand as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if session is None or event is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return CommandResponse(session=SessionResponse.from_session(session), event=event)


@router.get(
    "/{session_id}/race-state",
    response_model=RaceStateResponse,
    dependencies=[Depends(require_admin)],
)
def get_race_state(session_id: UUID) -> RaceStateResponse:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    for health in telemetry_collector.health(session_id, list(session.car_states)):
        store.set_connection_status(
            session_id, health.car_id, ConnectionStatus(health.connection_status)
        )
    session = store.get_session(session_id)
    assert session is not None
    latest = max(
        (car.updated_at for car in session.car_states.values()),
        default=session.created_at,
    )
    return RaceStateResponse(
        session_id=session.session_id,
        session_state=session.state,
        updated_at=latest,
        leaderboard=session.leaderboard(),
    )


@router.post("/{session_id}/telemetry", status_code=status.HTTP_202_ACCEPTED)
def receive_telemetry(session_id: UUID, packet: TelemetryPacket) -> dict[str, object]:
    try:
        _accept_telemetry(session_id, packet)
    except ValueError as exc:
        code = 404 if str(exc) in {"Session not found", "Car is not configured in this session"} else 409
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    received = telemetry_collector.latest(session_id, packet.car_id)
    return {
        "accepted": True,
        "received_at": received.received_at if received else None,
        "sequence": packet.sequence,
    }


@router.websocket("/{session_id}/telemetry/ws")
async def telemetry_stream(websocket: WebSocket, session_id: UUID) -> None:
    """Accept a persistent CSP client stream at the configured car's sample rate."""
    car_id = websocket.query_params.get("car_id", "")
    driver_id = websocket.query_params.get("driver_id", "")
    session = store.get_session(session_id)
    entry = next(
        (
            item
            for item in session.config.entries
            if item.car_id == car_id and item.driver_id == driver_id
        ),
        None,
    ) if session is not None else None
    if entry is None:
        await websocket.close(code=1008, reason="Unknown session car or driver")
        return

    await websocket.accept()
    accepted_packets = 0
    try:
        while True:
            payload = await websocket.receive_json()
            try:
                packet = TelemetryPacket.model_validate(payload)
                if packet.car_id != car_id or packet.driver_id != driver_id:
                    raise ValueError("Telemetry identity does not match the stream")
                _accept_telemetry(session_id, packet)
            except (ValueError, ValidationError) as exc:
                await websocket.send_json({"accepted": False, "error": str(exc)})
                continue
            accepted_packets += 1
            response: dict[str, object] = {
                "accepted": True,
                "sequence": packet.sequence,
            }
            if accepted_packets % 4 == 0:
                response["leaderboard"] = _driver_leaderboard(session_id)
            await websocket.send_json(response)
    except WebSocketDisconnect:
        store.set_connection_status(session_id, car_id, ConnectionStatus.DISCONNECTED)


@router.get("/{session_id}/telemetry/health", dependencies=[Depends(require_admin)])
def get_telemetry_health(session_id: UUID) -> list[dict[str, object]]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    health = telemetry_collector.health(session_id, list(session.car_states))
    for car_health in health:
        store.set_connection_status(
            session_id,
            car_health.car_id,
            ConnectionStatus(car_health.connection_status),
        )
    return [item.model_dump(mode="json") for item in health]


@router.get(
    "/{session_id}/cars/{car_id}/telemetry",
    dependencies=[Depends(require_admin)],
)
def get_car_telemetry_history(
    session_id: UUID,
    car_id: str,
    limit: int = Query(default=100, ge=1, le=256),
) -> list[dict[str, object]]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if car_id not in session.car_states:
        raise HTTPException(status_code=404, detail="Car is not configured in this session")
    return [
        sample.model_dump(mode="json")
        for sample in telemetry_collector.history(session_id, car_id, limit)
    ]


@router.get(
    "/{session_id}/cars/{car_id}/telemetry/interpolated",
    dependencies=[Depends(require_admin)],
)
def get_interpolated_car_telemetry(
    session_id: UUID,
    car_id: str,
    at: datetime = Query(description="Timezone-aware timestamp bracketed by telemetry samples"),
) -> dict[str, object]:
    session = store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if car_id not in session.car_states:
        raise HTTPException(status_code=404, detail="Car is not configured in this session")
    try:
        sample = telemetry_collector.interpolate(session_id, car_id, at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if sample is None:
        raise HTTPException(
            status_code=404,
            detail="Timestamp is not bracketed by buffered telemetry samples",
        )
    return sample.model_dump(mode="json")


@router.patch(
    "/{session_id}/cars/{car_id}",
    response_model=RaceStateResponse,
    dependencies=[Depends(require_admin)],
)
def update_car_state(
    session_id: UUID,
    car_id: str,
    request: CarStateUpdate,
    response: Response,
    actor: str = Header(default="telemetry", alias="X-RaceCore-Actor"),
) -> RaceStateResponse:
    values = request.model_dump(exclude_unset=True)
    try:
        session, _, _ = store.update_car_state(session_id, car_id, values, actor)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if car_id not in session.car_states:
        raise HTTPException(status_code=404, detail="Car is not configured in this session")
    latest = max(
        (car.updated_at for car in session.car_states.values()),
        default=session.created_at,
    )
    response.headers["X-RaceCore-Session-State"] = session.state.value
    return RaceStateResponse(
        session_id=session.session_id,
        session_state=session.state,
        updated_at=latest,
        leaderboard=session.leaderboard(),
    )
