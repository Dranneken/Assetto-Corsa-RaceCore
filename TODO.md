# RaceCore Roadmap

The original detailed plan is preserved in [`ToDoList.txt`](ToDoList.txt). Work is grouped here by delivery milestone.

## Architecture decision

- [x] Keep the RaceCore host/backend as a separate local process with PostgreSQL and browser interfaces.
- [x] Keep the CSP Lua app as a thin in-game companion, not the race-state authority.
- [x] Keep the source repository outside `assettocorsa/apps/lua`; deploy only `client/csp_lua/` into the game.

## Milestone 1: Project foundation

- [x] Establish repository layout and development documentation
- [x] Set up the backend virtual environment and API test suite
- [x] Provide user-level PostgreSQL 17 setup and lifecycle scripts
- [x] Select FastAPI for the backend
- [x] Set up Python package and environment configuration
- [x] Add API liveness endpoint
- [x] Initialize Git repository and CI
- [x] Choose and scaffold frontend framework
- [x] Add coding conventions, database schema, and migrations
- [x] Scaffold CSP Lua client shell and deployment script

## Milestone 2: Race session core

- [x] Session configuration and state machine
- [x] In-memory authoritative race state and audit events
- [x] Session and race-state REST APIs
- [x] PostgreSQL persistence for durable race data

## Milestone 3: Telemetry and client

- [x] Add configurable CSP WebSocket telemetry sender at 20 Hz
- [x] Add validated in-memory latest-state and bounded per-car telemetry history APIs
- [x] Interpolate continuous telemetry values at timestamps bracketed by buffered samples
- [x] Derive overall/class race order from lap and normalized track position
- [x] Track sequence gaps, packet age, client round-trip latency, and connected/stale/disconnected state
- [x] AC telemetry collector and connection health
- [x] In-memory live telemetry and rolling evidence buffer
- [x] Connect the CSP Lua client to the RaceCore host and add connection-loss handling
- [x] Integrate eight individually toggleable local HUD windows based on RennsportHUD 1.29, including the consolidated Session/Leaderboard and Gearbox/RPM layout, alongside the RC connection/configuration window
- [ ] Driver-specific live data API/WebSocket
- [ ] Validate two-player telemetry across separate home networks; see [`docs/remote-two-player-test-plan.md`](docs/remote-two-player-test-plan.md)

## Milestone 6: Host distribution

- [x] Decide how PostgreSQL is installed and started for a local RaceCore host
- [x] Package the FastAPI host as a separate user-level Windows app with start, stop, logs, and upgrade handling
- [ ] Add a first-run configuration flow for the database and Assetto Corsa telemetry adapter
- [ ] Prepare a public VPS deployment with a stable HTTPS/WSS endpoint; player connections should not require Tailscale
- [ ] Authenticate and authorize CSP telemetry WebSocket clients before any public exposure
- [ ] Load-test telemetry with increasing client counts through the 50-car target and document measured limits
- [x] Keep host installation and updates independent from the CSP Lua client deployment

## Milestone 4: Race operations

- [ ] Race Director control dashboard and commands
- [ ] Incident detection and steward review workflow
- [ ] Evidence viewer and export
- [ ] Broadcast interface and post-race results

## Milestone 5: Analytics and operations

- [ ] Race and driver reports
- [ ] Full user accounts and role-based access control (temporary admin HTTP Basic credential is available for testing)
- [ ] Monitoring, deployment, backup, and recovery
- [ ] Evaluate Redis and container deployment when the local application is established
