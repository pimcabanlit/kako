"""Demo mode (Phase 3, task 9): the scripted sessions on local Meko, with recorded answers.

`kako demo run` is one command for judges and for the video's dry runs. It needs local Postgres (an
empty database, or one demo mode set up before) and local Meko running, and no Azure settings at
all: every model reply comes from a recording in `data/recorded/`, replayed strictly, so the turns
are the ones recorded on Foundry. It:

1. loads the demo household with its whole story (`prepare`), unless this database holds it already;
2. uploads the demo's documents to Meko's knowledge base (each file once: a second run adds none);
3. replays each session in `data/demo-household/sessions/` that has its recording, each turn kept
   like any other: the plan in Postgres, the turn in a new Meko conversation;
4. with `--test-set`, replays the agent test set for each architecture that has its recording.

Asking anything else needs live mode with a Foundry deployment (`kako ask`, `kako api`).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import MEKO_CALLS, Asked, run_turn, start_session
from kako.agents.recorded import ReplayBackend
from kako.db.meko_log import DbCallLog
from kako.db.models import Household, Proposal
from kako.demo.files import DemoHousehold
from kako.demo.kb import AGENT, upload_demo_documents
from kako.demo.load import load_demo
from kako.demo.sessions import DemoSession
from kako.meko.mcp import open_meko
from kako.settings import Settings

HOUSEHOLD = cast(Table, Household.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
STATUS_CHECKS: Final = 10


class DemoModeError(Exception):
    """Demo mode can't run here, such as on Meko Cloud or a database with part of the story."""


@dataclass(frozen=True)
class Prepared:
    household_id: uuid.UUID
    loaded: bool  # False: the database held the demo already
    documents: int
    new_documents: int


def check_target(settings: Settings) -> None:
    """Demo mode runs on local Meko and replays: it never spends Meko Cloud or Foundry."""
    if settings.database_url is None:
        raise DemoModeError(
            "KAKO_DATABASE_URL is not set: point it at a local Postgres database for the demo"
        )
    if settings.meko_target != "local":
        raise DemoModeError(
            "demo mode runs on local Meko: set MEKO_MCP_URL to http://127.0.0.1:7777/mcp"
        )


async def prepare(engine: AsyncEngine, settings: Settings, demo: DemoHousehold) -> Prepared:
    """The household with its whole story, and its documents searchable in Meko."""
    async with engine.connect() as conn:
        found = (
            await conn.execute(
                select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.name == demo.household.name)
            )
        ).scalar_one_or_none()
        loaded = found is None
        if found is None:
            through = max(c.recorded_at for c in demo.changes) if demo.changes else None
            household_id = await load_demo(conn, demo, through=through)
            await conn.commit()
        else:
            household_id = found
            approved = (
                await conn.execute(
                    select(func.count()).where(
                        PROPOSAL.c.household_id == household_id, PROPOSAL.c.status == "approved"
                    )
                )
            ).scalar_one()
            if approved < len(demo.changes):
                raise DemoModeError(
                    f"this database holds {demo.household.name} with {approved} of its "
                    f"{len(demo.changes)} changes: demo mode needs the whole story, so use an "
                    "empty database"
                )
    calls = DbCallLog(engine)
    bound = 1 + len(demo.documents) * (1 + STATUS_CHECKS)
    async with open_meko(settings, calls, max_calls=bound) as meko:
        conversation_id = await meko.create_conversation(
            agent_id=AGENT, title="Demo knowledge base", session_key="kako-demo-kb"
        )
        documents = await upload_demo_documents(
            meko, demo, conversation_id, checks=STATUS_CHECKS, pause=2.0
        )
    new = sum(1 for d in documents if not d.already_uploaded)
    return Prepared(household_id, loaded, len(documents), new)


async def replay_session(
    engine: AsyncEngine,
    settings: Settings,
    session: DemoSession,
    household_id: uuid.UUID,
    *,
    shown: Callable[[Asked], None] | None = None,
) -> list[Asked]:
    """One scripted session: a new session, each turn answered from its recording."""
    backend = ReplayBackend(session.recording, strict=True)
    replay = settings.model_copy(
        update={"model_mode": "replay", "recorded_responses": session.recording}
    )
    calls = DbCallLog(engine)
    asked: list[Asked] = []
    async with open_meko(replay, calls, max_calls=1 + MEKO_CALLS * len(session.turns)) as meko:
        started = await start_session(
            engine,
            meko,
            household_id=household_id,
            on=session.on,
            title=session.title,
            call_log=calls,
        )
        for turn in session.turns:
            answer = await run_turn(
                engine,
                meko,
                replay,
                backend,
                started,
                message=turn.message,
                known_at=session.known_at,
                seed=turn.seed,
            )
            asked.append(answer)
            if shown is not None:
                shown(answer)
    return asked
