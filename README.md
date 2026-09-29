# Assetto Corsa RaceCore

RaceCore is a local race-control host for Assetto Corsa. It combines a FastAPI backend, optional PostgreSQL persistence, a browser-based Race Director interface, and a lightweight Custom Shaders Patch (CSP) Lua app inside the game.

The host owns race sessions and authoritative race state. The in-game app sends car telemetry to the host. The source repository stays separate from the Assetto Corsa installation; only the Lua client is deployed into the game.

> **Development status:** The session and race-state APIs, telemetry ingestion, in-memory live state, persistence layer, temporary admin HTTP Basic authentication, and Windows host packaging are implemented. The Control dashboard is currently a scaffold. Incident review, reports, full user accounts and roles, and first-run configuration are still on the roadmap. This is a pre-release project; it is not v1.0.

## Joining a race as a client

If someone else is hosting RaceCore, you only need the in-game client. You do **not** need to install or start the RaceCore host, Python, PostgreSQL, or this repository.

1. Download both client files: [AC_RaceCore.lua](https://raw.githubusercontent.com/Dranneken/Assetto-Corsa-RaceCore/main/client/csp_lua/AC_RaceCore.lua) and [manifest.ini](https://raw.githubusercontent.com/Dranneken/Assetto-Corsa-RaceCore/main/client/csp_lua/manifest.ini). [Browse the client folder](https://github.com/Dranneken/Assetto-Corsa-RaceCore/tree/main/client/csp_lua).
2. Create `assettocorsa/apps/lua/AC_RaceCore` in your Assetto Corsa installation and put both downloaded files in that folder.
3. Enable **RaceCore Client** in the CSP Apps settings, then start Assetto Corsa and join the race using the host's normal multiplayer server details.
4. If the RaceCore host is on another network, install and connect Tailscale, then accept the host's device-sharing invitation. In the in-game RaceCore Client window, set Host to the Tailscale address and port the host gives you, such as `100.x.y.z:8000`.
5. Enter the session ID, car ID, and driver ID supplied by the RaceCore host, then connect. The IDs must match your configured session entry.

You need the same Assetto Corsa track, car, and other content required by the multiplayer race. The [remote two-player test plan](docs/remote-two-player-test-plan.md) has the full connection checklist.

## Hosting with RaceCore

The host is the one PC that runs the RaceCore API for the session. The Assetto Corsa multiplayer server is separate; RaceCore does not host the game server. The host can also join the race as a player by installing the client above on that PC.

1. Install and start the [Windows RaceCore host](#package-the-windows-host). PostgreSQL is optional for a two-player test; without it, RaceCore uses in-memory storage.
2. For players on different networks, install Tailscale on the host PC and share access to **only that host PC** with the joining player. Set `RACECORE_HOST` in `%LOCALAPPDATA%\RaceCore\.env` to the host PC's Tailscale IP address, then restart RaceCore. Its default `127.0.0.1` setting accepts local connections only.
3. Save the temporary admin username and password printed during host installation. They are stored in `%LOCALAPPDATA%\RaceCore\.env` and are for the RaceCore operator; do not send them to joining players.
4. Allow TCP port `8000` to the joining player's Tailscale connection. Do not create a router port-forwarding rule or expose the API publicly. Admin REST operations require the temporary credential; the CSP telemetry stream does not, so keep the host on the private network.
5. Open `http://<host-tailscale-ip>:8000/docs`, select **Authorize**, enter the admin credential, create the session, and add a configured entry for each player's unique car ID and driver ID.
6. Send each player the client download links above, the host Tailscale IP and port, the session ID, and their assigned car and driver IDs. They do not need your admin credential.

Follow the [remote two-player test plan](docs/remote-two-player-test-plan.md) for the full setup, firewall checks, reconnection tests, and run sheet. If everyone is on the same trusted home network, Tailscale is unnecessary; set `RACECORE_HOST` to the host PC's LAN IP and allow TCP port `8000` from that LAN only. The default `127.0.0.1` address accepts local connections only.

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

The API listens at `http://127.0.0.1:8000`. Check `/health` for liveness and open `/docs` for the interactive API documentation. Session management and race-state endpoints require `RACECORE_ADMIN_USERNAME` and `RACECORE_ADMIN_PASSWORD`; configure both in your ignored local `.env` before using those endpoints. Copy `.env.example` as a template and replace its password placeholder with a unique random value. If `RACECORE_DATABASE_URL` is not set, RaceCore uses its in-memory store.

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
- Race and driver reports, full user accounts and role-based access control, monitoring, deployment, backup, and recovery.
- Evaluate Redis and container deployment after the local application is established.

## Repository layout

```text
backend/       FastAPI host, domain logic, migrations, and tests
client/        CSP Lua client source
control/       React + TypeScript + Vite dashboard
docs/          Architecture and development conventions
               Remote test plan: docs/remote-two-player-test-plan.md
tools/         Windows setup, packaging, install, and lifecycle scripts
TODO.md        Current project roadmap
ToDoList.txt   Original detailed checklist
```
