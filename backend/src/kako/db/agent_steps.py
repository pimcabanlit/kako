"""The agents' steps in Postgres: one `agent_step` row per tool call, written as it happens.

Each write commits on its own connection, so the steps of a turn that later fails are still there
to show what the agents did.
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.turn import StepRecord
from kako.db.models import AgentStep

AGENT_STEP = cast(Table, AgentStep.__table__)


class DbStepLog:
    """`StepLog` on the `agent_step` table. A step belongs to a session, so one is required."""

    def __init__(self, engine: AsyncEngine, session_id: uuid.UUID) -> None:
        self._engine = engine
        self._session_id = session_id

    async def write(self, step: StepRecord) -> None:
        if step.session_id != self._session_id:
            raise ValueError("a step must belong to this log's session")
        async with self._engine.begin() as conn:
            await conn.execute(
                AGENT_STEP.insert().values(
                    id=step.id,
                    session_id=step.session_id,
                    meko_turn_seed=step.meko_turn_seed,
                    agent=step.agent,
                    seq=step.seq,
                    tool=step.tool,
                    input_summary=step.input_summary,
                    result_summary=step.result_summary,
                    calc_run_id=step.calc_run_id,
                    outcome=step.outcome,
                    created_at=step.created_at,
                )
            )
