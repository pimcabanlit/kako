"""The `kako` command: `uv run kako --help`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kako.settings import get_settings

MIGRATIONS = Path(__file__).parent / "db" / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kako", description="Kako's backend commands.")
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="run the API on http://127.0.0.1:8000/api/v1")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true", help="restart on code changes")

    commands.add_parser("migrate", help="bring the database to the latest schema (Alembic)")

    args = parser.parse_args(argv)
    if args.command == "api":
        return _api(args.host, args.port, reload=args.reload)
    if args.command == "migrate":
        return _migrate()
    parser.error(f"unknown command {args.command}")
    return 2


def _api(host: str, port: int, *, reload: bool) -> int:
    import uvicorn

    uvicorn.run("kako.api.app:create_app", factory=True, host=host, port=port, reload=reload)
    return 0


def _migrate() -> int:
    from alembic import command
    from alembic.config import Config

    if get_settings().database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    command.upgrade(config, "head")
    print("Database is at the latest schema.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
