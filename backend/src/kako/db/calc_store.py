"""Calculation runs in Postgres: a run, the facts it read (`calc_input`) and its figures.

A figure is never stored without its run, its formula and the facts it read (REVIEW.md rule 7). A
what-if's figures also cite hypothetical values, which aren't facts, so a run with overrides is
stored only with the scenario they belong to.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.models import CalcInput, CalcRun
from kako.db.models import Figure as FigureModel
from kako.engine.figures import Figure, FigureRef, FigureValue, Run

CALC_RUN = cast(Table, CalcRun.__table__)
CALC_INPUT = cast(Table, CalcInput.__table__)
FIGURE = cast(Table, FigureModel.__table__)


class CalcStoreError(Exception):
    """A run that can't be stored or found."""


async def save_run(
    conn: AsyncConnection,
    run: Run,
    *,
    created_at: datetime,
    scenario_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Store a run and its figures in one transaction. `known_at` defaults to `created_at`: a
    snapshot taken without one used everything Kako knew when it was computed."""
    if created_at.tzinfo is None:
        raise CalcStoreError("created_at must carry its time zone (UTC)")
    if scenario_id is None and any(f.input_override_ids for f in run.figures):
        raise CalcStoreError("a what-if's run is stored with its scenario")
    run_id = uuid.uuid4()
    ids = {f.ref: uuid.uuid4() for f in run.figures}
    facts = sorted({i for f in run.figures for i in f.input_fact_ids}, key=str)
    async with conn.begin_nested() if conn.in_transaction() else conn.begin():
        await conn.execute(
            CALC_RUN.insert().values(
                id=run_id,
                household_id=run.household_id,
                as_of_date=run.as_of,
                known_at=run.known_at or created_at,
                snapshot_hash=run.snapshot_hash,
                scenario_id=scenario_id,
                engine_version=run.engine_version,
                created_at=created_at,
            )
        )
        if facts:
            await conn.execute(
                CALC_INPUT.insert(), [{"calc_run_id": run_id, "fact_id": f} for f in facts]
            )
        if run.figures:
            await conn.execute(FIGURE.insert(), [_row(f, run_id, ids) for f in run.figures])
    return run_id


def _row(figure: Figure, run_id: uuid.UUID, ids: dict[FigureRef, uuid.UUID]) -> dict[str, Any]:
    value = figure.value
    return {
        "id": ids[figure.ref],
        "calc_run_id": run_id,
        "key": figure.key,
        "entity_id": figure.entity_id,
        "unit": figure.unit,
        "value_numeric": None if value is None or isinstance(value, date) else Decimal(value),
        "value_date": value if isinstance(value, date) else None,
        "flag": figure.flag,
        "formula": figure.formula,
        "input_fact_ids": list(figure.input_fact_ids),
        "input_figure_ids": [ids[r] for r in figure.input_figures],
    }


async def load_run(conn: AsyncConnection, run_id: uuid.UUID) -> Run:
    """A stored run, as the engine returned it (without a what-if's override ids)."""
    head = (
        (await conn.execute(select(CALC_RUN).where(CALC_RUN.c.id == run_id)))
        .mappings()
        .one_or_none()
    )
    if head is None:
        raise CalcStoreError(f"calculation run {run_id} doesn't exist")
    rows = list(
        (await conn.execute(select(FIGURE).where(FIGURE.c.calc_run_id == run_id))).mappings()
    )
    refs = {r["id"]: FigureRef(r["key"], r["entity_id"]) for r in rows}
    figures = [
        Figure(
            key=r["key"],
            entity_id=r["entity_id"],
            unit=r["unit"],
            value=_value(r["unit"], r["value_numeric"], r["value_date"]),
            flag=r["flag"],
            formula=r["formula"],
            input_fact_ids=tuple(sorted(r["input_fact_ids"], key=str)),
            input_override_ids=(),
            input_figures=tuple(
                sorted(
                    (refs[i] for i in r["input_figure_ids"]),
                    key=lambda x: (x.key, str(x.entity_id)),
                )
            ),
        )
        for r in rows
    ]
    return Run(
        household_id=head["household_id"],
        as_of=head["as_of_date"],
        known_at=head["known_at"],
        snapshot_hash=head["snapshot_hash"],
        engine_version=head["engine_version"],
        figures=tuple(sorted(figures, key=lambda f: (f.key, str(f.entity_id or "")))),
    )


def _value(unit: str, numeric: Decimal | None, day: date | None) -> FigureValue | None:
    if unit == "date":
        return day
    if numeric is None:
        return None
    if unit == "ratio":
        return numeric
    return int(numeric)
