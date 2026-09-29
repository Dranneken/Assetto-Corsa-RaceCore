"""Top-level API router."""

import secrets

from fastapi import APIRouter, Header, HTTPException, Request

from racecore.api.sessions import router as sessions_router
from racecore.config import settings
from racecore.domain.store import store

router = APIRouter()
router.include_router(sessions_router, prefix="/api/v1")


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return liveness information without depending on external services."""
    persistence = "postgresql" if store.persistence_enabled else "memory"
    return {"status": "ok", "service": "racecore", "persistence": persistence}


@router.post("/api/v1/system/shutdown", tags=["system"])
async def shutdown_host(
    request: Request,
    shutdown_token: str | None = Header(default=None, alias="X-RaceCore-Shutdown-Token"),
) -> dict[str, str]:
    """Stop a packaged local host when its private shutdown token is supplied."""
    if (
        not settings.shutdown_token
        or not shutdown_token
        or not secrets.compare_digest(shutdown_token, settings.shutdown_token)
    ):
        raise HTTPException(status_code=404, detail="Not found")

    server = getattr(request.app.state, "uvicorn_server", None)
    if server is None:
        raise HTTPException(status_code=503, detail="Host shutdown is unavailable")
    server.should_exit = True
    return {"status": "stopping", "service": "racecore"}
