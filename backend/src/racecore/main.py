"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from racecore import __version__
from racecore.api.routes import router
from racecore.domain.store import store


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    try:
        yield
    finally:
        store.close()

app = FastAPI(
    title="Assetto Corsa RaceCore API",
    version=__version__,
    description="Local race-control API for Assetto Corsa.",
    lifespan=lifespan,
)
app.include_router(router)
