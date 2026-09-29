# Development conventions

## Python

- Target Python 3.11 or newer. Use four spaces, type hints on public functions, and 100-character lines.
- Run `ruff check src migrations` from `backend/`; use `ruff format src migrations` to apply the agreed formatting.
- Keep race rules and state transitions in the domain layer, separate from HTTP routes and persistence adapters.
- Use Pydantic schemas at HTTP boundaries; do not expose SQLAlchemy models directly from routes.
- Raise domain errors for invalid state changes and translate them to HTTP errors at the API boundary.

## Database

- PostgreSQL is the durable store. Define schema changes in Alembic revisions under `backend/migrations/versions/`.
- Never edit an applied revision. Add a new revision with a reversible downgrade for each schema change.
- Keep live telemetry and the rolling evidence window in memory; do not write raw high-frequency samples to PostgreSQL.
- Persist sessions, entries, laps, results, incidents, penalties, steward reviews, and audit events.
- Store large telemetry/evidence files outside PostgreSQL and persist only their references.
- Use UTC timestamps and explicit foreign keys, constraints, and indexes for durable records.

## Race rules and audit

- Race commands are validated domain operations. Each accepted command changes authoritative state and creates an audit event.
- Incident detection records evidence and classification candidates. It never applies an automatic penalty; stewards decide.
- Keep client update rates bounded and reject updates for cars not configured in the session.

## Frontend

- Use React with TypeScript and Vite. Keep API calls in `control/src/api/`, and keep display components free of race-rule decisions.
- Prefer small functional components, explicit API response types, and semantic HTML.
- Run `npm run build` from `control/` before opening a change.

## Configuration and secrets

- Read local configuration from `RACECORE_` environment variables or an untracked `.env` file.
- Keep credentials, local database URLs, logs, and generated evidence out of version control.
- Keep the dependency lockfile checked in once dependencies are installed on a machine with Node/npm.
