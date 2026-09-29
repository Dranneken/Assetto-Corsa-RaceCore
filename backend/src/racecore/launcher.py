"""Command-line entry point for the packaged RaceCore host."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config

from racecore import __version__
from racecore.config import settings
from racecore.main import app


def _migrate() -> None:
    if not settings.database_url:
        raise SystemExit("RACECORE_DATABASE_URL is not configured; there is no database to migrate.")

    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    alembic_config = Config(str(bundle_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(bundle_root / "migrations"))
    command.upgrade(alembic_config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(prog=f"RaceCore-{__version__}")
    parser.add_argument("--version", action="version", version=f"RaceCore {__version__}")
    parser.add_argument("command", nargs="?", choices=("run", "migrate"), default="run")
    args = parser.parse_args()

    if args.command == "migrate":
        _migrate()
        return

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            access_log=True,
        )
    )
    app.state.uvicorn_server = server
    server.run()


if __name__ == "__main__":
    main()
