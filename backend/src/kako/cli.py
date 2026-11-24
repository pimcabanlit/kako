"""The `kako` command: `uv run kako --help`."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

from kako.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncConnection

    from kako.engine.figures import Figure

MIGRATIONS = Path(__file__).parent / "db" / "migrations"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kako", description="Kako's backend commands.")
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="run the API on http://127.0.0.1:8000/api/v1")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true", help="restart on code changes")

    commands.add_parser("migrate", help="bring the database to the latest schema (Alembic)")
    commands.add_parser(
        "check-models",
        help="settings, Entra ID sign-in, and one tiny call per Foundry deployment",
    )

    demo = commands.add_parser("demo", help="the synthetic demo household")
    demo_commands = demo.add_subparsers(dest="demo_command", required=True)
    load = demo_commands.add_parser(
        "load", help="load data/demo-household (the seed) into a database that doesn't hold it"
    )
    load.add_argument(
        "--through",
        type=datetime.fromisoformat,
        help="also replay the approved changes up to this time, such as 2026-12-01T12:00+08:00",
    )
    load.add_argument("--data", type=Path, help="the demo folder (default: data/demo-household)")
    upload = demo_commands.add_parser(
        "upload",
        help="upload the demo's statements and reference documents to Meko's knowledge base",
    )
    upload.add_argument("--data", type=Path, help="the demo folder (default: data/demo-household)")

    validate = commands.add_parser(
        "validate", help="rules V-01 to V-08 and V-16 over a household's facts; exit 1 on any"
    )
    validate.add_argument("--household", type=uuid.UUID, help="needed when there are several")

    figures = commands.add_parser("figures", help="compute a household's figures")
    figures.add_argument("--household", type=uuid.UUID, help="needed when there are several")
    figures.add_argument(
        "--on", type=date.fromisoformat, help="the date (default: the household's as-of date)"
    )
    figures.add_argument(
        "--known-at",
        type=datetime.fromisoformat,
        help="as Kako knew it then, such as 2026-09-15T18:00+08:00 (default: everything)",
    )
    figures.add_argument("--save", action="store_true", help="store the run and its figures")

    ask = commands.add_parser(
        "ask",
        help="one planning turn: the orchestrator and specialists answer a message "
        "(KAKO_MODEL_MODE: live, record or replay)",
    )
    ask.add_argument("message", help="what the household says")
    ask.add_argument("--household", type=uuid.UUID, help="needed when there are several")
    ask.add_argument(
        "--on", type=date.fromisoformat, help="the date (default: the household's as-of date)"
    )
    ask.add_argument(
        "--known-at",
        type=datetime.fromisoformat,
        help="as Kako knew it then, such as 2026-09-15T09:00+08:00 (default: everything)",
    )
    ask.add_argument("--title", default="Planning session", help="the session's title")
    ask.add_argument(
        "--seed",
        default="ask:t1",
        help="the turn's seed, which keys recorded responses (default: ask:t1)",
    )
    ask.add_argument("--no-meko", action="store_true", help="no Meko search for this turn")

    args = parser.parse_args(argv)
    if args.command == "api":
        return _api(args.host, args.port, reload=args.reload)
    if args.command == "migrate":
        return _migrate()
    if args.command == "check-models":
        return _check_models()
    if args.command == "demo" and args.demo_command == "upload":
        return asyncio.run(_demo_upload(args.data))
    if args.command == "demo":
        return asyncio.run(_demo_load(args.through, args.data))
    if args.command == "validate":
        return asyncio.run(_validate(args.household))
    if args.command == "figures":
        return asyncio.run(_figures(args.household, args.on, args.known_at, save=args.save))
    if args.command == "ask":
        return asyncio.run(
            _ask(
                args.message,
                household_id=args.household,
                on=args.on,
                known_at=args.known_at,
                title=args.title,
                seed=args.seed,
                use_meko=not args.no_meko,
            )
        )
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


def _check_models() -> int:
    from kako.agents.model_manager import check_models

    lines = check_models(get_settings())
    for line in lines:
        print(line)
    return 0 if all(line.ok for line in lines) else 1


async def _connected(work: Callable[[AsyncConnection], Awaitable[int]]) -> int:
    """Run `work(conn)` on one connection; exit 1 when the database isn't configured."""
    from kako.db.engine import make_engine

    url = get_settings().database_url
    if url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    engine = make_engine(url)
    try:
        async with engine.connect() as conn:
            return await work(conn)
    finally:
        await engine.dispose()


async def _demo_load(through: datetime | None, folder: Path | None) -> int:
    from kako.demo.files import DEMO_DIR, DemoDataError, read_demo
    from kako.demo.load import DemoLoadError, load_demo

    try:
        demo = read_demo(folder or DEMO_DIR)
    except DemoDataError as exc:
        print(f"The demo files don't fit the data model: {exc}", file=sys.stderr)
        return 1

    async def work(conn: AsyncConnection) -> int:
        try:
            household_id = await load_demo(conn, demo, through=through)
        except DemoLoadError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        applied = sum(1 for c in demo.changes if through is not None and c.recorded_at <= through)
        print(f"Loaded {demo.household.name} ({household_id}): {len(demo.facts)} seed facts, "
              f"{applied} approved changes.")  # fmt: skip
        return 0

    return await _connected(work)


async def _demo_upload(folder: Path | None) -> int:
    """Every demo document into Meko's knowledge base, each call counted in `meko_call`."""
    from kako.db.engine import make_engine
    from kako.db.meko_log import DbCallLog
    from kako.demo.files import DEMO_DIR, DemoDataError, read_demo
    from kako.demo.kb import AGENT, upload_demo_documents
    from kako.meko.client import MekoError
    from kako.meko.mcp import open_meko

    settings = get_settings()
    if settings.database_url is None:
        print("KAKO_DATABASE_URL is not set: every Meko call is counted there.", file=sys.stderr)
        return 1
    try:
        demo = read_demo(folder or DEMO_DIR)
    except DemoDataError as exc:
        print(f"The demo files don't fit the data model: {exc}", file=sys.stderr)
        return 1
    checks = 10
    engine = make_engine(settings.database_url)
    try:
        # One conversation (the same one on every run), an upload and its status checks per file.
        bound = 1 + len(demo.documents) * (1 + checks)
        async with open_meko(settings, DbCallLog(engine), max_calls=bound) as meko:
            conversation_id = await meko.create_conversation(
                agent_id=AGENT, title="Demo knowledge base", session_key="kako-demo-kb"
            )
            documents = await upload_demo_documents(
                meko, demo, conversation_id, checks=checks, pause=2.0
            )
    except MekoError as exc:
        print(f"Meko ({settings.meko_target}): {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    new = sum(1 for d in documents if not d.already_uploaded)
    print(f"{len(documents)} documents searchable in Meko ({settings.meko_target}); {new} new.")
    return 0


async def _household(conn: AsyncConnection, household_id: uuid.UUID | None) -> uuid.UUID | None:
    from sqlalchemy import select

    from kako.db.models import Household

    table = Household.__table__
    rows = list(await conn.execute(select(table.c.id, table.c.name).order_by(table.c.name)))
    if household_id is not None:
        if any(r.id == household_id for r in rows):
            return household_id
        print(f"No household {household_id}.", file=sys.stderr)
        return None
    if len(rows) == 1:
        return rows[0].id  # type: ignore[no-any-return]
    if not rows:
        print("No household yet: run `kako demo load`.", file=sys.stderr)
    else:
        names = ", ".join(f"{r.name} ({r.id})" for r in rows)
        print(f"Several households; choose one with --household: {names}", file=sys.stderr)
    return None


async def _validate(household_id: uuid.UUID | None) -> int:
    from kako.db.fact_store import validate_household

    async def work(conn: AsyncConnection) -> int:
        chosen = await _household(conn, household_id)
        if chosen is None:
            return 1
        violations = await validate_household(conn, chosen)
        for v in violations:
            print(f"{v.rule} {v.table} {v.row_id}: {v.message}")
        print("Every rule passes." if not violations else f"{len(violations)} violations.")
        return 1 if violations else 0

    return await _connected(work)


async def _figures(
    household_id: uuid.UUID | None, on: date | None, known_at: datetime | None, *, save: bool
) -> int:
    from sqlalchemy import select

    from kako.db.calc_store import save_run
    from kako.db.fact_store import load_entities, snapshot
    from kako.db.models import Household
    from kako.engine import EngineInputError, compute

    if known_at is not None and known_at.tzinfo is None:
        print("--known-at needs its time zone, such as +08:00.", file=sys.stderr)
        return 1

    async def work(conn: AsyncConnection) -> int:
        chosen = await _household(conn, household_id)
        if chosen is None:
            return 1
        table = Household.__table__
        head = (await conn.execute(select(table).where(table.c.id == chosen))).mappings().one()
        day = on or head["as_of_date"]
        entities = await load_entities(conn, chosen)
        try:
            run = compute(await snapshot(conn, chosen, day, known_at), entities)
        except EngineInputError as exc:
            print(f"The engine can't read these facts: {exc}", file=sys.stderr)
            return 1
        names = {e.id: e.name for e in entities}
        print(f"{head['name']} on {day}" + (f", as known at {known_at}" if known_at else ""))
        for figure in run.figures:
            label = figure.key + (f" ({names[figure.entity_id]})" if figure.entity_id else "")
            print(f"  {label:<52} {_shown(figure)}")
        if save:
            run_id = await save_run(conn, run, created_at=datetime.now(UTC))
            await conn.commit()
            print(f"Stored as calculation run {run_id}.")
        return 0

    return await _connected(work)


async def _ask(
    message: str,
    *,
    household_id: uuid.UUID | None,
    on: date | None,
    known_at: datetime | None,
    title: str,
    seed: str,
    use_meko: bool,
) -> int:
    from contextlib import AsyncExitStack

    from sqlalchemy import select

    from kako.agents.ask import ask, render_answer
    from kako.agents.brief_store import BriefStoreError
    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.agents.orchestrator import OrchestratorError
    from kako.db.engine import make_engine
    from kako.db.meko_log import DbCallLog
    from kako.db.models import Household
    from kako.meko.client import MekoError
    from kako.meko.mcp import open_meko

    settings = get_settings()
    if settings.database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if known_at is not None and known_at.tzinfo is None:
        print("--known-at needs its time zone, such as +08:00.", file=sys.stderr)
        return 1
    engine = make_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            chosen = await _household(conn, household_id)
            if chosen is None:
                return 1
            table = Household.__table__
            as_of = (
                await conn.execute(select(table.c.as_of_date).where(table.c.id == chosen))
            ).scalar_one()
        async with AsyncExitStack() as stack:
            # The brief's search, a conversation, and one extra search per specialist ask.
            meko = (
                await stack.enter_async_context(open_meko(settings, DbCallLog(engine), max_calls=8))
                if use_meko
                else None
            )
            asked = await ask(
                engine,
                meko,
                settings,
                chat_backend(settings),
                household_id=chosen,
                message=message,
                on=on or as_of,
                known_at=known_at,
                title=title,
                seed=seed,
            )
        print(render_answer(asked))
        return 0
    except (ModelError, MekoError, BriefStoreError, OrchestratorError) as exc:
        print(f"The turn stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def _shown(figure: Figure) -> str:
    """A figure in plain words: pesos with centavos, whole months, a ratio, a date."""
    value = figure.value
    flag = f"  [{figure.flag}]" if figure.flag else ""
    if value is None:
        return f"no value{flag}"
    if figure.unit == "centavos" and isinstance(value, int):
        sign = "-" if value < 0 else ""
        pesos, centavos = divmod(abs(value), 100)
        return f"{sign}₱{pesos:,}.{centavos:02d}{flag}"
    if figure.unit == "months":
        return f"{value} months{flag}"
    if figure.unit == "ratio" and isinstance(value, Decimal):
        return f"{value}{flag}"
    return f"{value}{flag}"


if __name__ == "__main__":
    raise SystemExit(main())
