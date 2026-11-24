"""The `kako` command: `uv run kako --help`."""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kako.settings import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

    from kako.engine.figures import Figure

MIGRATIONS = Path(__file__).parent / "db" / "migrations"
LOOPBACK = frozenset({"127.0.0.1", "localhost"})  # the API's Host check allows these


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kako", description="Kako's backend commands.")
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="run the API on http://127.0.0.1:8000/api/v1")
    api.add_argument(
        "--host", default="127.0.0.1", help="a loopback address only, until there is sign-in"
    )
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
    run = demo_commands.add_parser(
        "run",
        help="demo mode: the demo household with its whole story, its documents in local Meko, "
        "and the scripted sessions replayed from recordings (no Azure settings needed)",
    )
    run.add_argument(
        "--test-set",
        action="store_true",
        help="also replay the agent test set for each architecture that has its recording",
    )
    run.add_argument(
        "--strict",
        action="store_true",
        help="refuse a call whose request differs from its recording (by default its reply is "
        "replayed and the difference reported)",
    )

    record = demo_commands.add_parser(
        "record",
        help="record one scripted session on Foundry, on an empty database and local Meko "
        "(KAKO_MODEL_MODE=record: it spends; log a prediction in docs/tuning-log.md first)",
    )
    record.add_argument("session", help="the session file's name, such as session-4")

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
    ask.add_argument("--by", help="who says it, by name: named on any change it proposes")

    test_set = commands.add_parser(
        "test-set",
        help="the agent test set: every question a turn on the demo household, scored in code. "
        "It replays data/recorded/test-set-<architecture>.json; only KAKO_MODEL_MODE=record calls "
        "Foundry (and records)",
    )
    test_set.add_argument(
        "--architecture",
        choices=("specialists", "single"),
        default="specialists",
        help="the orchestrator with its specialists, or the single-agent baseline",
    )
    test_set.add_argument("--only", help="question ids, such as q01,q07")
    test_set.add_argument("--household", type=uuid.UUID, help="needed when there are several")
    test_set.add_argument(
        "--save",
        action="store_true",
        help="write the report to data/test-set/results/<architecture>.json (whole set only)",
    )

    dream = commands.add_parser(
        "dream",
        help="dreaming: after a session ends, propose what the household stated that Kako "
        "doesn't hold (pending until a person approves)",
    )
    dream_commands = dream.add_subparsers(dest="dream_command", required=True)
    end = dream_commands.add_parser("end", help="end a session and queue its dreaming run")
    end.add_argument("session", type=uuid.UUID, help="the session's id")
    end.add_argument(
        "--at", type=datetime.fromisoformat, help="when it ended, with its zone (default: now)"
    )
    dream_run = dream_commands.add_parser(
        "run",
        help="run the queued dreaming runs (or one session's), one at a time "
        "(KAKO_MODEL_MODE: live, record or replay)",
    )
    dream_run.add_argument("--session", type=uuid.UUID, help="only this session's run")
    dream_run.add_argument(
        "--at",
        type=datetime.fromisoformat,
        help="the time its proposals are made, with its zone (default: now)",
    )
    dream_eval = dream_commands.add_parser(
        "eval",
        help="dreaming's labelled set on the demo household, scored in code. It replays "
        "data/recorded/dreaming.json; only KAKO_MODEL_MODE=record calls Foundry (and records)",
    )
    dream_eval.add_argument("--only", help="case ids, such as d01,d03")
    dream_eval.add_argument("--household", type=uuid.UUID, help="needed when there are several")
    dream_eval.add_argument(
        "--save",
        action="store_true",
        help="write the report to data/dreaming/results.json (whole set only)",
    )

    proposals = commands.add_parser(
        "proposals", help="what waits for the household's yes or no, and their decision"
    )
    proposal_commands = proposals.add_subparsers(dest="proposal_command", required=True)
    listed = proposal_commands.add_parser("list", help="the household's proposals")
    listed.add_argument(
        "--status",
        choices=("pending", "approved", "rejected", "expired", "all"),
        default="pending",
    )
    listed.add_argument("--household", type=uuid.UUID, help="needed when there are several")
    for action in ("approve", "reject"):
        decide = proposal_commands.add_parser(
            action,
            help=f"{action} proposals by id"
            + (" and write what each names, together" if action == "approve" else ""),
        )
        decide.add_argument("ids", nargs="+", type=uuid.UUID, help="the proposals' ids")
        decide.add_argument("--by", required=True, help="the adult who decides, by name")
        decide.add_argument("--household", type=uuid.UUID, help="needed when there are several")

    args = parser.parse_args(argv)
    if args.command == "proposals":
        if args.proposal_command == "list":
            return asyncio.run(_proposals(args.status, args.household))
        return asyncio.run(
            _decide(args.proposal_command, args.ids, by=args.by, household_id=args.household)
        )
    if args.command == "api":
        return _api(args.host, args.port, reload=args.reload)
    if args.command == "migrate":
        return _migrate()
    if args.command == "check-models":
        return _check_models()
    if args.command == "demo" and args.demo_command == "run":
        from kako.demo.mode import DemoModeError, check_target

        try:  # before the migration, so a wrong target is never touched
            check_target(get_settings())
        except DemoModeError as exc:
            print(f"Demo mode can't start: {exc}", file=sys.stderr)
            return 1
        return _migrate() or asyncio.run(_demo_run(test_set=args.test_set, strict=args.strict))
    if args.command == "demo" and args.demo_command == "record":
        from kako.demo.mode import DemoModeError, check_target

        settings = get_settings()
        try:
            check_target(settings)
        except DemoModeError as exc:
            print(f"Can't record: {exc}", file=sys.stderr)
            return 1
        if settings.model_mode != "record":
            print(
                "Recording calls Foundry and spends: set KAKO_MODEL_MODE=record.", file=sys.stderr
            )
            return 1
        return _migrate() or asyncio.run(_demo_record(args.session))
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
                by=args.by,
            )
        )
    if args.command == "test-set":
        return asyncio.run(
            _test_set(args.architecture, args.only, household_id=args.household, save=args.save)
        )
    if args.command == "dream":
        if args.dream_command == "end":
            return asyncio.run(_dream_end(args.session, args.at))
        if args.dream_command == "run":
            return asyncio.run(_dream_run(args.session, args.at))
        return asyncio.run(_dream_eval(args.only, household_id=args.household, save=args.save))
    parser.error(f"unknown command {args.command}")
    return 2


def _api(host: str, port: int, *, reload: bool) -> int:
    import uvicorn

    if host not in LOOPBACK:
        # No sign-in yet, and a turn spends money: never open the API to the network.
        print(f"kako api: {host} isn't a loopback address; use 127.0.0.1", file=sys.stderr)
        return 2
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


async def _demo_run(*, test_set: bool, strict: bool) -> int:
    """Demo mode: everything from local services and recordings (`demo/mode.py`)."""
    from kako.agents.ask import render_answer
    from kako.agents.brief_store import BriefStoreError
    from kako.agents.chat import ModelError
    from kako.agents.orchestrator import OrchestratorError
    from kako.agents.recorded import ReplayBackend
    from kako.db.engine import make_engine
    from kako.demo.files import DemoDataError, read_demo
    from kako.demo.load import DemoLoadError
    from kako.demo.mode import (
        DemoModeError,
        check_target,
        prepare,
        replay_session,
        written,
        written_by_sessions,
    )
    from kako.demo.sessions import RECORDED_DIR, DemoSessionError, check_writes, read_sessions
    from kako.evals.questions import TestSetError, read_test_set
    from kako.evals.runner import run_test_set
    from kako.meko.client import MekoError

    settings = get_settings().model_copy(update={"model_mode": "replay", "replay_strict": strict})
    try:
        check_target(settings)
        demo = read_demo()
        sessions = read_sessions(people=frozenset(p.key for p in demo.people))
        check_writes(sessions, demo)
    except (DemoModeError, DemoDataError, DemoSessionError) as exc:
        print(f"Demo mode can't start: {exc}", file=sys.stderr)
        return 1
    database_url = settings.database_url
    if database_url is None:  # check_target refuses it; this keeps the type narrow
        return 1
    engine = make_engine(database_url)
    try:
        prepared = await prepare(engine, settings, demo, skip=written_by_sessions(sessions))
        print(
            f"{demo.household.name}: "
            + ("loaded with its whole story" if prepared.loaded else "already loaded")
            + f"; {prepared.documents} documents searchable in local Meko "
            f"({prepared.new_documents} new).\n"
        )
        played = 0
        for session in sessions:
            if not session.recording.exists():
                print(f"{session.title}: no recording yet ({session.recording.name}), skipped.\n")
                continue
            if session.writes:
                found = await written(engine, demo, session, prepared.household_id)
                if all(found.values()):
                    print(
                        f"{session.title}: the changes it approves are in this database already "
                        "(an earlier run), so it isn't replayed again; use an empty database to "
                        "replay it.\n"
                    )
                    continue
                if any(found.values()):
                    raise DemoModeError(
                        f"{session.title}: this database holds part of what it writes; use an "
                        "empty database"
                    )

            def show(asked: Any, title: str = session.title) -> None:
                print(f"== {title}, turn {asked.seed} ==")
                print(render_answer(asked, settings) + "\n")

            replayed = await replay_session(
                engine, settings, demo, session, prepared.household_id, strict=strict, shown=show
            )
            print(_drift(session.title, replayed.calls, replayed.drifted))
            played += 1
        if test_set:
            questions = read_test_set()
            for architecture in ("specialists", "single"):
                path = RECORDED_DIR / f"test-set-{architecture}.json"
                if not path.exists():
                    print(f"Agent test set ({architecture}): no recording yet, skipped.")
                    continue
                replay = settings.model_copy(update={"recorded_responses": path})
                backend = ReplayBackend(path, strict=strict)
                report = await run_test_set(
                    engine,
                    replay,
                    backend,
                    questions,
                    household_id=prepared.household_id,
                    architecture="single" if architecture == "single" else "specialists",
                )
                data = report.as_json()
                print(
                    f"Agent test set ({architecture}): {report.score:.1%} over "
                    f"{data['questions']} questions ({data['checks_passed']}/"
                    f"{data['checks_total']} checks), {data['answered']} answered, "
                    f"{data['model_calls']} model calls replayed."
                )
                print(
                    _drift(f"Agent test set ({architecture})", data["model_calls"], backend.drifted)
                )
    except (
        DemoModeError,
        DemoLoadError,
        TestSetError,
        ModelError,
        MekoError,
        BriefStoreError,
        OrchestratorError,
    ) as exc:
        print(f"Demo mode stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(
        f"\nDemo mode replayed {played} session(s) from recordings: no Azure settings, no model "
        "calls. Look around with `uv run kako api` and the web app; asking new questions needs "
        "live mode with a Foundry deployment."
    )
    return 0


def _drift(what: str, calls: int, drifted: Sequence[str]) -> str:
    if not drifted:
        return f"{what}: every request matched its recording."
    return (
        f"{what}: {len(drifted)} of {calls} requests differed from the recording, most likely "
        "because this machine's Meko ranked the brief's search results differently; their "
        "recorded replies were replayed (`--strict` refuses them)."
    )


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


async def _proposals(status: str, household_id: uuid.UUID | None) -> int:
    from kako.api.proposals import describe
    from kako.db.fact_store import load_entities, load_facts
    from kako.db.proposal_store import list_proposals

    async def work(conn: AsyncConnection) -> int:
        chosen = await _household(conn, household_id)
        if chosen is None:
            return 1
        views = await list_proposals(
            conn,
            chosen,
            status=None if status == "all" else status,  # type: ignore[arg-type]
        )
        entities, facts = await load_entities(conn, chosen), await load_facts(conn, chosen)
        for v in views:
            decided = (
                f", {v.status} by {v.decided_by} on {v.decided_at:%Y-%m-%d %H:%M %Z}"
                if (v.decided_at is not None and v.decided_by)
                else (f", {v.status}" if v.status != "pending" else "")
            )
            print(f"{v.id} {v.kind}{decided}")
            print(f"  {describe(v, entities, facts)}")
            print(f"  Why: {v.explanation}")
            for e in v.evidence:
                who = f"{e.said_by}: " if e.said_by else ""
                print(f'  Evidence ({e.kind} {e.ref}): {who}"{e.quote}"')
        print(f"{len(views)} proposal(s)." if views else "No proposals.")
        return 0

    return await _connected(work)


async def _decide(
    action: str, ids: Sequence[uuid.UUID], *, by: str, household_id: uuid.UUID | None
) -> int:
    from kako.api.proposals import people
    from kako.db.proposal_store import ProposalError, approve, list_proposals, reject

    async def work(conn: AsyncConnection) -> int:
        chosen = await _household(conn, household_id)
        if chosen is None:
            return 1
        person = (await people(conn, chosen)).get(by.strip().lower())
        if person is None:
            print(f"No one called {by} in the household.", file=sys.stderr)
            return 1
        mine = await list_proposals(conn, chosen, proposal_ids=ids)
        if len(mine) != len(set(ids)):
            print("Not every id is a proposal of this household.", file=sys.stderr)
            return 1
        decide = approve if action == "approve" else reject
        try:
            decided = await decide(conn, ids, person_id=person, decided_at=datetime.now(UTC))
            await conn.commit()
        except ProposalError as exc:
            await conn.rollback()
            print(f"Nothing was {action}d: {exc}", file=sys.stderr)
            return 1
        for d in decided:
            wrote = ", ".join(f"{w.table} {w.row_id}" for w in d.written)
            state = f"already {d.status}; nothing changed" if d.already else d.status
            print(f"{d.proposal_id} {d.kind}: {state}" + (f" ({wrote})" if wrote else ""))
        return 0

    return await _connected(work)


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
    by: str | None = None,
) -> int:
    from contextlib import AsyncExitStack

    from sqlalchemy import select

    from kako.agents.ask import MEKO_CALLS, ask, render_answer
    from kako.agents.brief_store import BriefStoreError
    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.agents.orchestrator import OrchestratorError
    from kako.api.proposals import people
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
            speaker = None
            if by is not None:
                speaker = (await people(conn, chosen)).get(by.strip().lower())
                if speaker is None:
                    print(f"No one called {by} in the household.", file=sys.stderr)
                    return 1
        async with AsyncExitStack() as stack:
            calls = DbCallLog(engine)
            meko = (
                await stack.enter_async_context(open_meko(settings, calls, max_calls=MEKO_CALLS))
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
                call_log=calls,
                speaker=speaker,
            )
        print(render_answer(asked, settings))
        return 0
    except (ModelError, MekoError, BriefStoreError, OrchestratorError) as exc:
        print(f"The turn stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


async def _demo_record(name: str) -> int:
    """One scripted session on Foundry, recorded: on an empty database, the story loaded without
    the rows the session writes, each turn and approval as demo mode plays them."""
    from kako.agents.ask import render_answer
    from kako.agents.brief_store import BriefStoreError
    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.agents.orchestrator import OrchestratorError
    from kako.db.engine import make_engine
    from kako.demo.files import DemoDataError, read_demo
    from kako.demo.load import DemoLoadError
    from kako.demo.mode import DemoModeError, prepare, replay_session
    from kako.demo.sessions import DemoSessionError, check_writes, read_sessions
    from kako.meko.client import MekoError

    settings = get_settings()
    try:
        demo = read_demo()
        sessions = read_sessions(people=frozenset(p.key for p in demo.people))
        check_writes(sessions, demo)
    except (DemoDataError, DemoSessionError) as exc:
        print(f"Can't record: {exc}", file=sys.stderr)
        return 1
    session = next((s for s in sessions if s.name == name), None)
    if session is None:
        print(f"No session {name!r} in data/demo-household/sessions/.", file=sys.stderr)
        return 1
    path = settings.recorded_responses or session.recording
    if path.exists():
        print(f"{path} exists: move it aside first (keep it as a past run).", file=sys.stderr)
        return 1
    database_url = settings.database_url
    if database_url is None:
        return 1
    engine = make_engine(database_url)
    try:
        prepared = await prepare(engine, settings, demo, skip=session.writes)
        if not prepared.loaded:
            print("Record on an empty database: this one holds the household.", file=sys.stderr)
            return 1
        recording = settings.model_copy(update={"recorded_responses": path})

        def show(asked: Any) -> None:
            print(f"== {session.title}, turn {asked.seed} ==")
            print(render_answer(asked, settings) + "\n")

        await replay_session(
            engine,
            recording,
            demo,
            session,
            prepared.household_id,
            shown=show,
            backend=chat_backend(recording),
        )
        print(f"Recorded to {path}.")
        return 0
    except (
        DemoModeError,
        DemoLoadError,
        ModelError,
        MekoError,
        BriefStoreError,
        OrchestratorError,
    ) as exc:
        print(f"Recording stopped: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def settings_for_test_set(settings: Settings, architecture: str) -> Settings:
    """The test set replays unless asked to record: a whole run on Foundry costs real money, so
    `live` (the default mode) replays too, and only `KAKO_MODEL_MODE=record` calls the model."""
    from kako.evals.questions import TEST_SET

    mode = "record" if settings.model_mode == "record" else "replay"
    recording = settings.recorded_responses
    if recording is None:
        recording = TEST_SET.parent.parent / "recorded" / f"test-set-{architecture}.json"
    return settings.model_copy(update={"model_mode": mode, "recorded_responses": recording})


async def _test_set(
    architecture: str, only: str | None, *, household_id: uuid.UUID | None, save: bool
) -> int:
    import json

    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.db.engine import make_engine
    from kako.evals.questions import TEST_SET, TestSetError, read_test_set
    from kako.evals.runner import Outcome, render_report, run_test_set

    settings = get_settings()
    database_url = settings.database_url
    if database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if settings.meko_target != "local":
        # Every question is a Meko conversation: never spent from Meko Cloud's lifetime 1,000.
        print("The test set runs on local Meko only (MEKO_MCP_URL).", file=sys.stderr)
        return 1
    settings = settings_for_test_set(settings, architecture)
    try:
        questions = read_test_set()
    except TestSetError as exc:
        print(f"The test set can't be read: {exc}", file=sys.stderr)
        return 1
    if only:
        wanted = {q.strip() for q in only.split(",") if q.strip()}
        unknown = wanted - {q.id for q in questions}
        if unknown:
            print(f"No such questions: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        if save:
            print("--save writes a whole run: leave out --only.", file=sys.stderr)
            return 1
        questions = tuple(q for q in questions if q.id in wanted)
    try:
        backend = chat_backend(settings)
    except ModelError as exc:
        print(f"No model to answer with: {exc}", file=sys.stderr)
        return 1
    engine = make_engine(database_url)
    try:
        async with engine.connect() as conn:
            chosen = await _household(conn, household_id)
        if chosen is None:
            return 1

        def progress(o: Outcome) -> None:
            note = f" ({o.error})" if o.error else ""
            print(f"{o.question.id}: {o.score.value:.0%}{note}", file=sys.stderr, flush=True)

        report = await run_test_set(
            engine,
            settings,
            backend,
            questions,
            household_id=chosen,
            architecture="single" if architecture == "single" else "specialists",
            progress=progress,
        )
    finally:
        await engine.dispose()
    print(render_report(report))
    if save:
        path = TEST_SET.parent / "results" / f"{architecture}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.as_json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Saved {path}")
    return 0


async def _dream_end(session_id: uuid.UUID, at: datetime | None) -> int:
    from kako.db.engine import make_engine
    from kako.dreaming.job import DreamError, end_session

    settings = get_settings()
    if settings.database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if at is not None and at.tzinfo is None:
        print("--at needs its time zone, such as +08:00.", file=sys.stderr)
        return 1
    engine = make_engine(settings.database_url)
    try:
        run_id = await end_session(engine, session_id, at or datetime.now(UTC))
    except DreamError as exc:
        print(f"Can't end it: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    print(f"Session {session_id} ended; dreaming run {run_id} is queued (kako dream run).")
    return 0


async def _dream_run(session_id: uuid.UUID | None, at: datetime | None) -> int:
    from sqlalchemy import select

    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.db.engine import make_engine
    from kako.db.meko_log import DbCallLog
    from kako.dreaming.job import DREAM_RUN, DreamError, queued_runs, run_dream
    from kako.health import safe_error
    from kako.meko.client import MekoError
    from kako.meko.mcp import open_meko

    settings = get_settings()
    if settings.database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    if at is not None and at.tzinfo is None:
        print("--at needs its time zone, such as +08:00.", file=sys.stderr)
        return 1
    try:
        backend = chat_backend(settings)
    except ModelError as exc:
        print(f"No model to dream with: {exc}", file=sys.stderr)
        return 1
    engine = make_engine(settings.database_url)
    failed = 0
    try:
        if session_id is None:
            runs = await queued_runs(engine)
        else:
            async with engine.connect() as conn:
                found = (
                    await conn.execute(
                        select(DREAM_RUN.c.id).where(DREAM_RUN.c.session_id == session_id)
                    )
                ).scalar_one_or_none()
            if found is None:
                print("That session has no dreaming run: end it first.", file=sys.stderr)
                return 1
            runs = [found]
        if not runs:
            print("No dreaming run is waiting.")
        for run_id in runs:
            calls = DbCallLog(engine)
            try:
                async with open_meko(settings, calls, max_calls=4) as meko:
                    report = await run_dream(
                        engine, meko, settings, backend, run_id, now=at or datetime.now(UTC)
                    )
            except (DreamError, MekoError, ModelError) as exc:
                print(f"Dreaming run {run_id} failed: {safe_error(exc)}", file=sys.stderr)
                failed += 1
                continue
            if not report.ran:
                print(f"Dreaming run {run_id}: {report.status} already, nothing to do.")
                continue
            print(
                f"Dreaming run {run_id} (session {report.session_id}): "
                f"{len(report.proposed)} proposal(s) waiting for a yes."
            )
            for o in report.outcomes:
                why = f": {o.reason}" if o.reason else ""
                print(f"- {o.outcome}: {o.finding.shown}{why}")
    finally:
        await engine.dispose()
    return 1 if failed else 0


async def _dream_eval(only: str | None, *, household_id: uuid.UUID | None, save: bool) -> int:
    import json

    from sqlalchemy import select

    from kako.agents.chat import ModelError
    from kako.agents.model_manager import chat_backend
    from kako.db.engine import make_engine
    from kako.db.models import Household
    from kako.demo.sessions import RECORDED_DIR
    from kako.evals.dreaming import (
        LABELLED,
        CaseResult,
        LabelledError,
        read_labelled,
        render_labelled,
        run_labelled,
    )

    settings = get_settings()
    database_url = settings.database_url
    if database_url is None:
        print("KAKO_DATABASE_URL is not set.", file=sys.stderr)
        return 1
    # Like the test set: it replays unless asked to record, since a whole run spends.
    mode = "record" if settings.model_mode == "record" else "replay"
    recording = settings.recorded_responses or RECORDED_DIR / "dreaming.json"
    settings = settings.model_copy(update={"model_mode": mode, "recorded_responses": recording})
    try:
        cases = read_labelled()
    except LabelledError as exc:
        print(f"The labelled set can't be read: {exc}", file=sys.stderr)
        return 1
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        unknown = wanted - {c.id for c in cases}
        if unknown:
            print(f"No such cases: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
        if save:
            print("--save writes a whole run: leave out --only.", file=sys.stderr)
            return 1
        cases = tuple(c for c in cases if c.id in wanted)
    try:
        backend = chat_backend(settings)
    except ModelError as exc:
        print(f"No model to dream with: {exc}", file=sys.stderr)
        return 1
    engine = make_engine(database_url)
    try:
        async with engine.connect() as conn:
            chosen = await _household(conn, household_id)
            if chosen is None:
                return 1
            table = Household.__table__
            name = (
                await conn.execute(select(table.c.name).where(table.c.id == chosen))
            ).scalar_one()

        def progress(r: CaseResult) -> None:
            note = f" ({r.error})" if r.error else ""
            print(
                f"{r.case.id}: {len(r.found)} of {len(r.case.expect)} found{note}",
                file=sys.stderr,
                flush=True,
            )

        try:
            report = await run_labelled(
                engine,
                settings,
                backend,
                cases,
                household_id=chosen,
                household_name=name,
                progress=progress,
            )
        except LabelledError as exc:
            print(f"The labelled set doesn't fit this household: {exc}", file=sys.stderr)
            return 1
    finally:
        await engine.dispose()
    print(render_labelled(report))
    if save:
        path = LABELLED.parent / "results.json"
        path.write_text(
            json.dumps(report.as_json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Saved {path}")
    return 0 if report.passed else 1


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
