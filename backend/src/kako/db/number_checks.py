"""The number check in Postgres: one `number_check` row per text checked (V-10).

A row is written when a text is sent back for its numbers (`regenerated`) and when a text is final
(`pass`, or `fail` with its unmatched numbers flagged). Each write commits on its own, like the
agents' steps, so a turn that later fails still shows what was checked. Never edited.
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.checks import CheckRecord
from kako.db.models import NumberCheck

NUMBER_CHECK = cast(Table, NumberCheck.__table__)


class DbCheckLog:
    """`CheckLog` on the `number_check` table, for one session and the run its texts are checked
    against (the turn's run; its what-ifs are runs of the same snapshot)."""

    def __init__(
        self, engine: AsyncEngine, *, session_id: uuid.UUID | None, calc_run_id: uuid.UUID
    ) -> None:
        self._engine = engine
        self._session_id = session_id
        self._calc_run_id = calc_run_id

    async def write(self, record: CheckRecord) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                NUMBER_CHECK.insert().values(
                    id=uuid.uuid4(),
                    session_id=self._session_id,
                    calc_run_id=self._calc_run_id,
                    subject=record.subject,
                    subject_id=record.subject_id,
                    checked_text=record.checked_text,
                    numbers=[n.as_json() for n in record.numbers],
                    result=record.result,
                    created_at=record.created_at,
                )
            )
