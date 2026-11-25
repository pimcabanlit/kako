"""What "before and after" reads: a plan's turn and its options, to set each option beside today's
plan (`planning.compare`).

Reads only, and only the household's rows. Today's plan is the snapshot the turn's run read: the
facts true on its date as Kako knew them then (`calc_run.as_of_date`, `calc_run.known_at`). Facts
are never overwritten, so it is taken again exactly, and its hash must be the stored run's; each
option is that snapshot with its allocations (`recommendation.allocation`) as overrides, the
what-if the agents ran. Nothing is written.
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.calc_store import load_run
from kako.db.fact_store import load_entities, load_facts
from kako.db.models import Plan, Recommendation
from kako.engine import EngineInputError, Override
from kako.facts.snapshot import take_snapshot
from kako.planning.compare import Comparison, comparison

PLAN = cast(Table, Plan.__table__)
REC = cast(Table, Recommendation.__table__)


class NotComparable(Exception):
    """The plan's turn can't be taken again exactly, so its options aren't compared."""


async def read_compare(
    conn: AsyncConnection, household_id: uuid.UUID, plan_id: uuid.UUID
) -> Comparison | None:
    """The plan's options beside today's plan, or None when the household has no such plan.
    Raises NotComparable when its snapshot can't be taken again as it was."""
    run_id = (
        await conn.execute(
            select(PLAN.c.calc_run_id).where(
                PLAN.c.id == plan_id, PLAN.c.household_id == household_id
            )
        )
    ).scalar_one_or_none()
    if run_id is None:
        return None
    run = await load_run(conn, run_id)
    facts = await load_facts(conn, household_id)
    entities = await load_entities(conn, household_id)
    snapshot = take_snapshot(household_id, facts, run.as_of, run.known_at)
    if snapshot.hash != run.snapshot_hash:
        raise NotComparable(
            "the facts this plan was worked out from can't be read back as they were"
        )
    recs = (
        await conn.execute(
            select(REC.c.option, REC.c.entity_id, REC.c.allocation)
            .where(REC.c.plan_id == plan_id)
            .order_by(REC.c.option, REC.c.id)
        )
    ).all()
    options: dict[str, list[Override]] = {}
    for label, entity_id, allocation in recs:
        found = options.setdefault(label, [])
        if entity_id is not None and allocation is not None:
            found.append(
                Override(uuid.uuid4(), entity_id, "plan.allocation", int(allocation), run.as_of)
            )
    try:
        return comparison(plan_id, snapshot, entities, list(options.items()))
    except EngineInputError as exc:
        raise NotComparable(f"the engine can't run this plan's options: {exc}") from None
