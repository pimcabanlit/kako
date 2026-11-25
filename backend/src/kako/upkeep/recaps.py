"""Session recaps in Meko: one of Kako's own memories for each ended session (docs/data-model.md,
"What Kako keeps in Meko").

When a session has ended, Meko upkeep adds a memory that recaps it, written by code from its kept
turns (`agents.conversation.recap`: what it was about, the household's words, the options offered,
the changes filed with where they stood, what it decided, Kako's last question), as `kako:upkeep`
with `kako_source: "session_recap"`, and links it to the session (`meko_link`, `kako_table` =
`session`, with the text written). Written once: a recap is the session as it ended. A later
session's `context_search` can then find an older session the brief's recaps (the newest three)
leave out. A recap is Kako's record of what was said, never household knowledge: the brief marks it
as such, dreaming leaves it alone (it carries Kako's `kako_` metadata), and no number in it is a
figure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import Table, and_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.brief_store import session_decisions, session_turns, statuses_of
from kako.agents.conversation import recap
from kako.agents.kept import TEST_SET_TITLE, PastSession
from kako.agents.present import day
from kako.db.models import Household, MekoLink, Session, SessionTurn

SESSION = cast(Table, Session.__table__)
SESSION_TURN = cast(Table, SessionTurn.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
SOURCE = "session_recap"


@dataclass(frozen=True)
class Recap:
    """A recap upkeep owes Meko: the ended session and the sentence to add."""

    session_id: uuid.UUID
    text: str


def recap_sentence(household: str, past: PastSession, statuses: dict[uuid.UUID, str]) -> str:
    """The memory's words: the household and the session named, then the recap."""
    return f"In the {household}, {past.title} ({day(past.on)}): {recap(past, statuses)}"


def recap_metadata(session_id: uuid.UUID) -> dict[str, Any]:
    return {"kako_source": SOURCE, "kako_session_id": str(session_id)}


async def recaps_owed(conn: AsyncConnection, household_id: uuid.UUID) -> list[Recap]:
    """The household's ended sessions with kept turns and no recap in Meko yet, oldest first. The
    agent test set's sessions are never recapped: a question is asked on its own."""
    name = (
        await conn.execute(select(HOUSEHOLD.c.name).where(HOUSEHOLD.c.id == household_id))
    ).scalar_one()
    linked = (
        select(MEKO_LINK.c.kako_id)
        .where(
            and_(
                MEKO_LINK.c.kako_table == "session",
                MEKO_LINK.c.kako_id == SESSION.c.id,
                MEKO_LINK.c.meko_kind == "memory",
            )
        )
        .exists()
    )
    has_turns = select(SESSION_TURN.c.id).where(SESSION_TURN.c.session_id == SESSION.c.id).exists()
    rows = list(
        await conn.execute(
            select(SESSION.c.id, SESSION.c.title, SESSION.c.household_date)
            .where(
                SESSION.c.household_id == household_id,
                SESSION.c.ended_at.is_not(None),
                ~SESSION.c.title.startswith(TEST_SET_TITLE, autoescape=True),
                has_turns,
                ~linked,
            )
            .order_by(SESSION.c.ended_at, SESSION.c.id)
        )
    )
    owed = []
    for row in rows:
        turns = await session_turns(conn, household_id, row.id)
        decisions = await session_decisions(conn, household_id, row.id)
        past = PastSession("S", row.title, row.household_date, turns, decisions, ended=True)
        filed = {c.proposal_id for t in turns for c in t.changes if c.proposal_id is not None}
        statuses = await statuses_of(conn, household_id, filed, None)
        owed.append(Recap(row.id, recap_sentence(name, past, statuses)))
    return owed
