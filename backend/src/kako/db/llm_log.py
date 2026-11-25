"""The model call log in Postgres: one `llm_call` row per call, made or refused.

Each write runs on its own connection and commits at once, like the Meko call counter, so a call
that cost money is counted even when the turn around it rolls back.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.prompt_registry import versions_json
from kako.agents.spend import LlmCallRecord
from kako.db.models import LlmCall

LLM_CALL = cast(Table, LlmCall.__table__)


class DbLlmLog:
    """`LlmLog` on the `llm_call` table."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def write(self, record: LlmCallRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                LLM_CALL.insert().values(
                    id=record.id,
                    session_id=record.session_id,
                    meko_turn_seed=record.meko_turn_seed,
                    agent=record.agent,
                    deployment=record.deployment,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cached_tokens=record.cached_tokens,
                    latency_ms=record.latency_ms,
                    cost_usd=record.cost_usd,
                    outcome=record.outcome,
                    recorded_replay=record.recorded_replay,
                    prompts=versions_json(record.prompts),
                    created_at=record.created_at,
                )
            )

    async def spent_since(self, since: datetime) -> Decimal:
        async with self._engine.connect() as conn:
            spent = await conn.execute(
                select(func.coalesce(func.sum(LLM_CALL.c.cost_usd), 0)).where(
                    LLM_CALL.c.recorded_replay.is_(False), LLM_CALL.c.created_at >= since
                )
            )
            return Decimal(spent.scalar_one())
