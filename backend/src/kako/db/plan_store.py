"""A turn's answer in Postgres: its what-ifs as scenarios, and the plan it proposes.

- Each what-if is a `scenario` with one `scenario_override` per allocation (`plan.allocation`,
  never a fact), and its run is stored with the scenario. The tools run what-ifs in memory and
  write nothing; every what-if of a turn is kept when the turn is, and the `agent_step` rows that
  ran it are then given its run. A turn that fails leaves no scenario behind.
- A turn that offers options, or found a conflict, proposes a `plan` (`save_answer`): the reply is
  its summary, each option's allocations are its `recommendation` rows with the option's cited
  sources, and each conflict is a `reconciliation` row. The plan stays `proposed` until the
  household accepts one option (Phase 4).

Every write here is one transaction: a plan is never left half written.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.agents.answers import Allocation, Citation, Option, TurnAnswer
from kako.agents.checks import TextCheck
from kako.agents.present import money
from kako.agents.tools import TurnState, WhatIf
from kako.db.calc_store import figure_ids, save_run
from kako.db.models import (
    AgentStep,
    Household,
    Plan,
    Recommendation,
    RecommendationSource,
    Reconciliation,
    Scenario,
    ScenarioOverride,
)
from kako.engine.figures import FigureRef
from kako.planning.reconcile import OWNER

AGENT_STEP = cast(Table, AgentStep.__table__)
HOUSEHOLD = cast(Table, Household.__table__)
PLAN = cast(Table, Plan.__table__)
RECOMMENDATION = cast(Table, Recommendation.__table__)
SOURCE = cast(Table, RecommendationSource.__table__)
RECONCILIATION = cast(Table, Reconciliation.__table__)
SCENARIO = cast(Table, Scenario.__table__)
OVERRIDE = cast(Table, ScenarioOverride.__table__)
QUOTE_CHARS = 500  # the most of a memory, document or message kept as a source's quote


class PlanStoreError(Exception):
    """A turn's answer that can't be stored as it is."""


def allocations_text(allocations: tuple[Allocation, ...]) -> str:
    return "; ".join(f"{a.entity_ref} {money(a.centavos)} a month" for a in allocations)


async def save_what_if(conn: AsyncConnection, what_if: WhatIf, *, on: date) -> uuid.UUID:
    """A what-if as a scenario, its overrides and its run, in the caller's transaction."""
    scenario_id = uuid.uuid4()
    await conn.execute(
        SCENARIO.insert().values(
            id=scenario_id,
            household_id=what_if.run.household_id,
            name=f"{what_if.ref}: {allocations_text(what_if.allocations)}"[:500],
            base_as_of=on,
        )
    )
    if what_if.allocations:
        await conn.execute(
            OVERRIDE.insert(),
            [
                {
                    "id": uuid.uuid4(),
                    "scenario_id": scenario_id,
                    "entity_id": a.entity_id,
                    "attribute": "plan.allocation",
                    "value_money": a.centavos,
                    "valid_from": on,
                }
                for a in what_if.allocations
            ],
        )
    return await save_run(conn, what_if.run, created_at=datetime.now(UTC), scenario_id=scenario_id)


@dataclass(frozen=True)
class SavedAnswer:
    """What a stored answer became: the plan, each option's recommendations, the conflicts."""

    plan_id: uuid.UUID | None  # None: no options and no conflict, so no plan
    version: int | None
    recommendations: dict[str, tuple[uuid.UUID, ...]] = field(default_factory=dict)  # by label
    reconciliations: tuple[uuid.UUID, ...] = ()

    def subject_id(self, check: TextCheck) -> uuid.UUID | None:
        """The row a final number check is about: the plan for the reply, an option's first
        recommendation for its label and summary, the first conflict for the reason."""
        if check.subject == "reply":
            return self.plan_id
        if check.subject == "reconciliation":
            return self.reconciliations[0] if self.reconciliations else None
        for label, ids in self.recommendations.items():
            if check.label in (f"option {label!r}'s label", f"option {label!r}'s summary"):
                return ids[0] if ids else None
        return None


async def save_answer(
    engine: AsyncEngine,
    state: TurnState,
    answer: TurnAnswer,
    *,
    session_id: uuid.UUID,
    calc_run_id: uuid.UUID,
    conversation_id: str,
    what_if_steps: Mapping[str, Sequence[uuid.UUID]],
) -> SavedAnswer:
    """Keep every what-if of the turn, name its run on the steps that ran it (`what_if_steps`, by
    ref), then the plan the answer proposes, in one transaction."""
    async with engine.begin() as conn:
        for ref, what_if in state.what_ifs.items():
            if ref not in state.stored:
                state.stored[ref] = await save_what_if(conn, what_if, on=state.snapshot.on)
        for ref, step_ids in what_if_steps.items():
            if ref not in state.stored:
                raise PlanStoreError(f"a step ran {ref}, which isn't a what-if of this turn")
            await conn.execute(
                AGENT_STEP.update()
                .where(AGENT_STEP.c.id.in_(list(step_ids)), AGENT_STEP.c.session_id == session_id)
                .values(calc_run_id=state.stored[ref])
            )
        if not answer.options and answer.resolution is None:
            return SavedAnswer(None, None)
        household_id = state.run.household_id
        # One plan version at a time per household: the row lock queues a second writer.
        await conn.execute(
            select(HOUSEHOLD.c.id).where(HOUSEHOLD.c.id == household_id).with_for_update()
        )
        version = (
            await conn.execute(
                select(func.coalesce(func.max(PLAN.c.version), 0) + 1).where(
                    PLAN.c.household_id == household_id
                )
            )
        ).scalar_one()
        plan_id = uuid.uuid4()
        await conn.execute(
            PLAN.insert().values(
                id=plan_id,
                household_id=household_id,
                version=version,
                session_id=session_id,
                calc_run_id=calc_run_id,
                status="proposed",
                summary=answer.reply,
                recommended_option=answer.recommended,
                created_at=datetime.now(UTC),
            )
        )
        figures = _Figures(conn, calc_run_id, state.stored)
        recommendations: dict[str, tuple[uuid.UUID, ...]] = {}
        kinds = state.kinds()
        for option in answer.options:
            sources = await _sources(figures, option, state, conversation_id)
            ids = []
            for a in option.allocations:
                rec_id = uuid.uuid4()
                area = OWNER.get(kinds[a.entity_id])
                if area is None:
                    raise PlanStoreError(f"{a.entity_ref} isn't a debt, an account or a goal")
                # Whose move it is: the area's own specialist if the option draws on it, else
                # the first specialist it draws on, else the area's.
                drawn = option.specialists
                specialist = area if area in drawn or not drawn else drawn[0]
                await conn.execute(
                    RECOMMENDATION.insert().values(
                        id=rec_id,
                        plan_id=plan_id,
                        option=option.label,
                        area=area,
                        specialist=specialist,
                        text=option.summary,
                        entity_id=a.entity_id,
                        allocation=a.centavos,
                        meko_turn_seed=state.turn_seed,
                    )
                )
                await conn.execute(
                    SOURCE.insert(), [{"recommendation_id": rec_id, **s} for s in sources]
                )
                ids.append(rec_id)
            recommendations[option.label] = tuple(ids)
        reconciliations = []
        resolution = answer.resolution
        if resolution is not None:
            if resolution.chosen:
                text = f"Chose {resolution.chosen}. {resolution.reason}"
                rejected = (
                    f"{resolution.rejected}: {allocations_text(resolution.rejected_allocations)}"
                )
            else:
                text, rejected = f"Left to the household. {resolution.reason}", None
            for conflict in resolution.conflicts:
                ids_shown = [
                    await figures.id(shown.run, shown.figure.ref) for shown in conflict.figures
                ]
                row_id = uuid.uuid4()
                await conn.execute(
                    RECONCILIATION.insert().values(
                        id=row_id,
                        plan_id=plan_id,
                        kind=conflict.kind,
                        specialists=list(conflict.specialists),
                        figure_ids=ids_shown,
                        resolution=text,
                        rejected=rejected,
                        attempts=resolution.attempts,
                    )
                )
                reconciliations.append(row_id)
    return SavedAnswer(plan_id, version, recommendations, tuple(reconciliations))


class _Figures:
    """Figure ids of the turn's run and its what-ifs' runs, read once each."""

    def __init__(
        self, conn: AsyncConnection, base: uuid.UUID, stored: dict[str, uuid.UUID]
    ) -> None:
        self._conn = conn
        self._runs = {"": base, **stored}
        self._ids: dict[str, dict[FigureRef, uuid.UUID]] = {}

    async def id(self, run: str, ref: FigureRef) -> uuid.UUID:
        if run not in self._ids:
            if run not in self._runs:
                raise PlanStoreError(f"{run!r} isn't a stored run of this turn")
            self._ids[run] = await figure_ids(self._conn, self._runs[run])
        found = self._ids[run].get(ref)
        if found is None:
            raise PlanStoreError(f"no figure {ref.key} in {run or 'the turn'}'s run")
        return found


async def _sources(
    figures: _Figures, option: Option, state: TurnState, conversation_id: str
) -> list[dict[str, str | None]]:
    """The option's citations as `recommendation_source` rows, one per kind and id."""
    rows: dict[tuple[str, str], str | None] = {}
    for c in option.citations:
        source_id, quote = await _source(figures, c, state, conversation_id)
        rows.setdefault((c.kind, source_id), quote)
    return [
        {"source_kind": kind, "source_id": source_id, "quote": quote}
        for (kind, source_id), quote in rows.items()
    ]


async def _source(
    figures: _Figures, c: Citation, state: TurnState, conversation_id: str
) -> tuple[str, str | None]:
    if c.kind == "figure":
        if c.figure is None:
            raise PlanStoreError(f"{c.ref} names no figure")
        return str(await figures.id(c.what_if or "", c.figure.ref)), None
    if c.kind == "conversation":  # the household's own words in this turn
        return conversation_id, state.message[:QUOTE_CHARS]
    if c.kind in ("memory", "knowledge"):
        return c.source_id, c.shown[:QUOTE_CHARS]
    return c.source_id, None
