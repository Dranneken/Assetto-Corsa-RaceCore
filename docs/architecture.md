# Architecture

## Initial shape

RaceCore is split into a local host process and an in-game client:

- **RaceCore host:** a separate local FastAPI process. It owns authoritative session state, validated commands, events, PostgreSQL persistence, and role-scoped APIs.
- **RC Client:** a lightweight CSP Lua app inside Assetto Corsa. It will display driver-specific race information and exchange only the data needed by the local driver.
- **RC Control:** a React + TypeScript + Vite browser interface for the Race Director, scaffolded under `control/`.
- **RC Steward:** a browser interface for incident review. Detection creates reviewable incidents; it does not automatically decide fault or apply penalties.
- **RC Broadcast:** a read-focused browser interface for timing and event selection.

## Data flow

The host receives race inputs from a telemetry adapter and client connections. The CSP client streams its configured car's samples over a local WebSocket; the host validates and timestamps them, retains latest state and bounded per-car history in RAM, and computes authoritative race/class order and estimated gaps from lap, normalized track position, track length, and speed. Connection health tracks sequence gaps, client round-trip latency, and stale/disconnected clients. The latest state, active race state, incidents, and short rolling evidence window stay in host memory for fast access. Durable information such as sessions, entries, completed laps, results, incidents, decisions, and audit events is persisted in PostgreSQL. Large telemetry evidence is stored as files, with references in the database; high-frequency raw telemetry is not stored as rows.

Browser interfaces and the in-game client consume role-scoped REST and WebSocket APIs. Race commands pass through the host, update authoritative state, emit an event, and leave an audit record. The CSP app is not the authority for race state or the full field; the telemetry adapter remains a separate integration point.

## Initial implementation boundary

The backend includes a liveness endpoint, session configuration and transitions, an in-memory authoritative race state, session/race-state REST endpoints, a bounded telemetry collector with timestamp-based interpolation, and optional PostgreSQL persistence. The CSP Lua client is deployed separately into the game’s Lua apps folder. Damage normalization, role authentication, and the working race-operations UI remain future work.

## Technology choices

- Backend: Python 3.11+, FastAPI, Uvicorn, Pydantic Settings.
- Frontend: React + TypeScript + Vite.
- Database: PostgreSQL for durable data, with SQLAlchemy mappings and Alembic migrations under `backend/`.
- Live telemetry: in-memory state and bounded rolling buffers.
- Deployment: local development first; Docker is deferred until the application works locally.
