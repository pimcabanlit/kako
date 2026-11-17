"""The Meko call counter in Postgres: one `meko_call` row per tool call, made or refused.

Each write runs on its own connection and commits at once, so a call is counted even when the work
around it rolls back: the allowance it used is spent either way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import Table, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.db.models import MekoCall
from kako.meko.quota import COUNTED_AS, Outcome, Target, quota_refusal, tools_counted_with

MEKO_CALL = cast(Table, MekoCall.__table__)


class DbCallLog:
    """`CallLog` on the `meko_call` table."""

    def __init__(self, engine: AsyncEngine, session_id: uuid.UUID | None = None) -> None:
        self._engine = engine
        self._session_id = session_id

    async def reserve(
        self, target: Target, tool: str, agent_id: str, ceiling: int | None
    ) -> uuid.UUID:
        call_id = uuid.uuid4()
        refused = False
        async with self._engine.begin() as conn:
            if ceiling is not None:
                # One counter per allowance and target: callers queue here, so two can't both
                # take the last call. The lock ends with the transaction.
                key = f"kako.meko_call:{target}:{COUNTED_AS.get(tool, tool)}"
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key}
                )
                made = await conn.execute(
                    select(func.count()).where(
                        MEKO_CALL.c.target == target,
                        MEKO_CALL.c.tool.in_(tools_counted_with(tool)),
                        MEKO_CALL.c.outcome != "refused",
                    )
                )
                refused = made.scalar_one() >= ceiling
            await conn.execute(
                MEKO_CALL.insert().values(
                    id=call_id,
                    session_id=self._session_id,
                    target=target,
                    tool=tool,
                    agent_id=agent_id,
                    outcome="refused" if refused else "ok",
                    created_at=datetime.now(UTC),
                )
            )
        if refused and ceiling is not None:
            raise quota_refusal(tool, ceiling)
        return call_id

    async def finish(
        self, call_id: uuid.UUID, outcome: Outcome, latency_ms: int, result_count: int | None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(MEKO_CALL)
                .where(MEKO_CALL.c.id == call_id)
                .values(outcome=outcome, latency_ms=latency_ms, result_count=result_count)
            )

    async def used(self, target: Target) -> dict[str, int]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                select(MEKO_CALL.c.tool, func.count())
                .where(MEKO_CALL.c.target == target, MEKO_CALL.c.outcome != "refused")
                .group_by(MEKO_CALL.c.tool)
            )
            return {tool: count for tool, count in rows}
