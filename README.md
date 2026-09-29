# Assetto Corsa RaceCore

RaceCore is a local race-control host for Assetto Corsa. It combines a FastAPI backend, optional PostgreSQL persistence, a browser-based Race Director interface, and a lightweight Custom Shaders Patch (CSP) Lua app inside the game.

The host owns race sessions and authoritative race state. The in-game app sends car telemetry to the host. The source repository stays separate from the Assetto Corsa installation; only the Lua client is deployed into the game.

> **Development status:** The session and race-state APIs, telemetry ingestion, in-memory live state, persistence layer, and Windows host packaging are implemented. The Control dashboard is currently a scaffold. Incident review, reports, authentication, and first-run configuration are still on the roadmap. This is a pre-release project; it is not v1.0.

## What RaceCore includes

- **RaceCore host:** FastAPI application with session lifecycle APIs and interactive API documentation.
- **Race state:** Live car state, race and class order, timing data, pit and driver status, connection health, and audit events.
- **Telemetry:** CSP WebSocket ingestion, validation, timestamps, in-memory latest state and bounded history, packet-gap and staleness tracking, and connection metrics.
- **Persistence:** Optional PostgreSQL storage for durable session data, entries, completed laps, results, and audit events. High-frequency telemetry stays in RAM.
- **CSP client:** In-game configuration UI and telemetry sender.
- **Windows host package:** A versioned, user-level app bundle with install, start, stop, log, and upgrade scripts.
- **Control UI:** React, TypeScript, and Vite scaffold for the future Race Director dashboard.

## Requirements

- Windows for the packaged host and CSP client deployment scripts.
- Python 3.11 or newer for development and source runs.
- Assetto Corsa with Custom Shaders Patch for in-game telemetry.
- PostgreSQL 17 only if durable database storage is needed; the backend can run with an in-memory store.
- Node.js is needed only to develop the Control UI.

## Run from source

From the repository root, create the Python environment and install the backend with development tools:

```powershell
py -3 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -e "backend/[dev]"
```

Start the API:

```powershell
Push-Location backend
.venv\Scripts\uvicorn.exe racecore.main:app --reload
Pop-Location
```

The API listens at `http://127.0.0.1:8000`. Check `/health` for liveness, open `/docs` for the interactive API documentation, and use `/api/v1/sessions` for session operations. If `RACECORE_DATABASE_URL` is not set, RaceCore uses its in-memory store.

### Optional PostgreSQL

The Windows setup scripts download verified PostgreSQL 17 binaries into the current user's local application data, create a local database, and write the connection URL to `.env`:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\setup_postgres.ps1
powershell.exe -ExecutionPolicy Bypass -File .\tools\start_postgres.ps1
Push-Location backend
.venv\Scripts\alembic.exe upgrade head
Pop-Location
```

Start RaceCore after applying the migrations. Use `tools\stop_postgres.ps1` to stop the local database. The scripts do not install a Windows service or require an administrator account. Local data and secrets are excluded from Git; see `.env.example` for available settings.

## Connect the Assetto Corsa client

Deploy the Lua app to your Assetto Corsa installation, substituting its root path:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\tools\deploy_csp_client.ps1 -AssettoCorsaRoot 'E:\SteamLibrary\steamapps\common\assettocorsa'
```

Start the RaceCore host, then configure the host URL, session ID, car ID, and driver ID in the in-game RaceCore Client window. The IDs must match a car and driver in the session configuration. The client sends telemetry at 20 Hz to the host WebSocket. RaceCore exposes telemetry health and per-car sample endpoints under `/api/v1/sessions/{session_id}`. Live samples are kept in memory and are not written to PostgreSQL.

## Package the Windows host

Build the versioned package from Windows after installing the development dependencies:

```powershell
Push-Location backend
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Pop-Location
powershell.exe -ExecutionPolicy Bypass -File .\tools\package_host.ps1
```

The package version is defined in `backend/pyproject.toml`. The generated ZIP in `dist/` contains a versioned executable, for example `RaceCore-0.1.0.exe`, plus its runtime files. Extract it and run `install_host.ps1` to install under `%LOCALAPPDATA%\Programs\RaceCore`; user configuration and logs are kept under `%LOCALAPPDATA%\RaceCore`. The host is installed independently of the CSP client and is not a Windows service.

The package includes scripts to start and stop the host, view logs, and upgrade to another version. Upgrades preserve configuration and logs and retain the prior version for rollback. When PostgreSQL is configured, start it before starting RaceCore.

## Development checks

```powershell
Push-Location backend
.venv\Scripts\pytest.exe
.venv\Scripts\ruff.exe check src migrations tests
Pop-Location
```

The Control UI lives in `control/`; its development scripts are in `control/package.json`.

## Roadmap

This is the current high-level roadmap. The detailed task checklist is in [`TODO.md`](TODO.md), and the original project plan is in [`ToDoList.txt`](ToDoList.txt).

### Completed

- Project structure, configuration, CI, backend packaging, and database migrations.
- Race session creation and configuration snapshots, lifecycle state machine, reset/restart operations, and audit log.
- Authoritative live car state and overall/class race order, including available timing, pit, driver, connection, retirement, and damage fields.
- CSP telemetry sender and host ingestion with packet validation, timestamps, bounded in-memory history, stale and dropped-packet tracking, and connection health metrics.
- Local PostgreSQL setup and lifecycle scripts, plus a versioned, independently installable Windows host package.

### In progress

- Driver-specific live telemetry API/WebSocket.
- Race Director Control dashboard and command workflow.
- First-run configuration for PostgreSQL and the Assetto Corsa telemetry adapter.

### Planned

- Telemetry interpolation and client-side update-rate tuning.
- Incident detection and steward review, with detection kept separate from penalty decisions.
- Evidence viewing and export, broadcast tools, and post-race results.
- Race and driver reports, authentication and roles, monitoring, deployment, backup, and recovery.
- Evaluate Redis and container deployment after the local application is established.

## Repository layout

```text
backend/       FastAPI host, domain logic, migrations, and tests
client/        CSP Lua client source
control/       React + TypeScript + Vite dashboard
docs/          Architecture and development conventions
tools/         Windows setup, packaging, install, and lifecycle scripts
TODO.md        Current project roadmap
ToDoList.txt   Original detailed checklist
```
