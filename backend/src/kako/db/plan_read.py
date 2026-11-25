"""What the plan screen reads: the household's plans, and one plan with its "why".

Reads only, and only the household's rows. A plan's "why" goes down to the rows behind it:

- each option's sources (`recommendation_source`): the figures it cites, with each figure's formula,
  the facts it read and the figures it was built from, all the way down; the facts, each with
  where it came from (the starting figures, a session, dreaming) and who approved it; the
  decisions; the memories and documents Meko gave, with the fact each memory is kept for; the
  household's own words;
- what the number check found in each option's texts (`number_check`);
- the turn's Meko calls (`meko_call`, between the turn before and this one being kept), and the
  trace link on Meko Cloud;
- what changed against the last plan: F-DIFF-1 from the household's previous plan's run, or, for
  the first plan, from the run the household last decided on, recomputed from the facts as Kako
  knew them then (facts are never overwritten, so it is the run they saw).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import RowMapping, Table, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.agents.present import Refs as EntityRefs
from kako.agents.present import day, fact_value, figure_value, money
from kako.agents.replan_store import last_decision
from kako.db.calc_store import load_run
from kako.db.fact_store import load_entities, load_facts
from kako.db.models import (
    CalcRun,
    Decision,
    DecisionAssumption,
    DecisionOption,
    DreamRun,
    MekoCall,
    MekoLink,
    NumberCheck,
    Person,
    Plan,
    Proposal,
    ProposalEvidence,
    Recommendation,
    RecommendationSource,
    Reconciliation,
    ScenarioOverride,
    Session,
    SessionTurn,
)
from kako.db.models import Figure as FigureModel
from kako.db.provenance import provenance
from kako.engine import Run, compute
from kako.engine.diff import diff
from kako.engine.figures import Figure
from kako.facts.model import EntityRow, FactRow
from kako.facts.snapshot import take_snapshot
from kako.planning.why import (
    ChangedFact,
    Changes,
    Refs,
    changed_fact,
    fact_title,
    figure_title,
    flag_words,
    formula_words,
    matched_words,
    what_changed,
)

PLAN = cast(Table, Plan.__table__)
REC = cast(Table, Recommendation.__table__)
SOURCE = cast(Table, RecommendationSource.__table__)
RECONCILIATION = cast(Table, Reconciliation.__table__)
CALC_RUN = cast(Table, CalcRun.__table__)
DREAM_RUN = cast(Table, DreamRun.__table__)
FIGURE = cast(Table, FigureModel.__table__)
OVERRIDE = cast(Table, ScenarioOverride.__table__)
SESSION = cast(Table, Session.__table__)
SESSION_TURN = cast(Table, SessionTurn.__table__)
PERSON = cast(Table, Person.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
EVIDENCE = cast(Table, ProposalEvidence.__table__)
DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
ASSUMPTION = cast(Table, DecisionAssumption.__table__)
MEKO_LINK = cast(Table, MekoLink.__table__)
MEKO_CALL = cast(Table, MekoCall.__table__)
NUMBER_CHECK = cast(Table, NumberCheck.__table__)
MAX_FIGURES = 400  # a "why" is bounded: a run has a few dozen figures, so this is never reached


@dataclass(frozen=True)
class PlanRow:
    id: uuid.UUID
    version: int
    status: str
    session_id: uuid.UUID
    session_title: str
    created_at: datetime
    as_of: date
    recommended_option: str | None
    options: int


@dataclass(frozen=True)
class FigureWhy:
    id: uuid.UUID
    title: str
    value: str
    flag: str | None
    formula: str
    formula_words: str
    what_if: str | None  # the what-if it was computed in, in words; None: the turn's own figures
    facts: list[uuid.UUID]
    inputs: list[uuid.UUID]


@dataclass(frozen=True)
class FactWhy:
    id: uuid.UUID
    title: str
    value: str
    valid_from: date
    valid_to: date | None
    status: str
    source: str  # where it came from, in words
    shared: str | None  # when it was shared with every agent in Meko, if it was
    replaced: str | None  # the value it replaced, if any


@dataclass(frozen=True)
class RejectedOption:
    label: str
    reason: str


@dataclass(frozen=True)
class DecisionWhy:
    id: uuid.UUID
    question: str
    chosen: str
    reasoning: str
    session_title: str
    on: date
    status: str
    rejected: list[RejectedOption]


@dataclass(frozen=True)
class MemoryWhy:
    kind: str  # memory or knowledge
    source_id: str
    quote: str | None
    fact_id: uuid.UUID | None  # the fact Kako keeps this memory for, if it is one of Kako's


@dataclass(frozen=True)
class Words:
    quote: str
    said_by: str | None


@dataclass(frozen=True)
class Why:
    figures: list[uuid.UUID]
    facts: list[uuid.UUID]
    decisions: list[DecisionWhy]
    memories: list[MemoryWhy]
    words: list[Words]


@dataclass(frozen=True)
class Allocation:
    recommendation_id: uuid.UUID
    entity_id: uuid.UUID | None
    name: str
    area: str
    specialist: str
    centavos: int | None
    shown: str


@dataclass(frozen=True)
class CheckedNumber:
    text: str
    matched: str | None  # what it matched, in words; None: nothing (flagged)


@dataclass(frozen=True)
class Check:
    text: str
    result: str  # pass, fail
    numbers: list[CheckedNumber]


@dataclass(frozen=True)
class OptionView:
    label: str
    recommended: bool
    summary: str
    specialists: list[str]
    allocations: list[Allocation]
    why: Why
    checks: list[Check]


@dataclass(frozen=True)
class ReconciliationView:
    kind: str
    specialists: list[str]
    resolution: str
    rejected: str | None
    attempts: int


@dataclass(frozen=True)
class MekoCallView:
    tool: str
    agent_id: str
    ms: int | None
    results: int | None
    outcome: str
    at: datetime


@dataclass(frozen=True)
class TurnView:
    session_id: uuid.UUID
    seed: str | None
    conversation_id: str
    message: str | None
    said_by: str | None
    kept_at: datetime | None
    meko_calls: list[MekoCallView]


@dataclass(frozen=True)
class Revisit:
    decision_id: uuid.UUID
    question: str
    chosen: str
    session_title: str
    decided_on: date
    because: list[ChangedFact]


@dataclass(frozen=True)
class Changed:
    since: str  # what the plan is compared with, in words
    since_plan: uuid.UUID | None
    changes: Changes
    revisit: list[Revisit]


@dataclass(frozen=True)
class PlanView:
    plan: PlanRow
    summary: str
    options: list[OptionView]
    reconciliations: list[ReconciliationView]
    turn: TurnView
    changed: Changed | None  # None: the household's first plan, with nothing decided before it
    figures: dict[uuid.UUID, FigureWhy] = field(default_factory=dict)
    facts: dict[uuid.UUID, FactWhy] = field(default_factory=dict)


# --- The list -------------------------------------------------------------------------------------


def _plan_query() -> Any:
    options = (
        select(func.count(func.distinct(REC.c.option)))
        .where(REC.c.plan_id == PLAN.c.id)
        .scalar_subquery()
    )
    return (
        select(
            PLAN.c.id,
            PLAN.c.version,
            PLAN.c.status,
            PLAN.c.session_id,
            SESSION.c.title.label("session_title"),
            PLAN.c.created_at,
            CALC_RUN.c.as_of_date.label("as_of"),
            PLAN.c.recommended_option,
            options.label("options"),
        )
        .join(SESSION, SESSION.c.id == PLAN.c.session_id)
        .join(CALC_RUN, CALC_RUN.c.id == PLAN.c.calc_run_id)
    )


async def list_plans(conn: AsyncConnection, household_id: uuid.UUID) -> list[PlanRow]:
    """The household's plans, the newest version first."""
    rows = await conn.execute(
        _plan_query().where(PLAN.c.household_id == household_id).order_by(PLAN.c.version.desc())
    )
    return [PlanRow(**dict(r._mapping)) for r in rows]


# --- One plan -------------------------------------------------------------------------------------


async def read_plan(
    conn: AsyncConnection, household_id: uuid.UUID, plan_id: uuid.UUID
) -> PlanView | None:
    """One of the household's plans with its why, or None when it has no such plan."""
    head = (
        await conn.execute(
            _plan_query()
            .add_columns(
                PLAN.c.summary,
                PLAN.c.calc_run_id,
                SESSION.c.meko_conversation_id,
                SESSION.c.started_at,
            )
            .where(PLAN.c.id == plan_id, PLAN.c.household_id == household_id)
        )
    ).first()
    if head is None:
        return None
    m = head._mapping
    plan = PlanRow(**{k: m[k] for k in PlanRow.__dataclass_fields__})
    entities = await load_entities(conn, household_id)
    by_entity = {e.id: e for e in entities}
    facts = await load_facts(conn, household_id)
    facts_by_id = {f.id: f for f in facts}

    recs = list(
        (
            await conn.execute(
                select(REC).where(REC.c.plan_id == plan_id).order_by(REC.c.option, REC.c.id)
            )
        ).mappings()
    )
    rec_ids = [r["id"] for r in recs]
    sources = (
        list(
            (
                await conn.execute(
                    select(SOURCE)
                    .where(SOURCE.c.recommendation_id.in_(rec_ids))
                    .order_by(SOURCE.c.source_kind, SOURCE.c.source_id)
                )
            ).mappings()
        )
        if rec_ids
        else []
    )
    turn = await _turn(conn, plan_id, plan.session_id, m["meko_conversation_id"], recs)
    turn_calls = await _meko_calls(conn, plan.session_id, turn.kept_at, m["started_at"], turn.seed)
    turn = TurnView(**{**turn.__dict__, "meko_calls": turn_calls})

    # The figures each option cites, and every figure and fact below them.
    cited_figures = {uuid.UUID(s["source_id"]) for s in sources if s["source_kind"] == "figure"}
    figure_rows = await _figure_closure(conn, cited_figures)
    what_ifs = await _what_ifs(conn, {r["calc_run_id"] for r in figure_rows.values()}, by_entity)
    figures = {
        fid: FigureWhy(
            id=fid,
            title=figure_title(r["key"], by_entity.get(r["entity_id"])),
            value=figure_value(_figure(r)),
            flag=flag_words(r["flag"]),
            formula=r["formula"],
            formula_words=formula_words(r["formula"]),
            what_if=what_ifs.get(r["calc_run_id"]),
            facts=sorted(r["input_fact_ids"], key=str),
            inputs=sorted(r["input_figure_ids"], key=str),
        )
        for fid, r in figure_rows.items()
    }
    fact_ids = {i for f in figures.values() for i in f.facts}
    fact_ids |= {uuid.UUID(s["source_id"]) for s in sources if s["source_kind"] == "fact"}
    why_facts = await _facts(
        conn, [facts_by_id[i] for i in fact_ids if i in facts_by_id], by_entity, facts_by_id
    )

    decisions = await _decisions(
        conn,
        {uuid.UUID(s["source_id"]) for s in sources if s["source_kind"] == "decision"},
    )
    memory_ids = [s["source_id"] for s in sources if s["source_kind"] in ("memory", "knowledge")]
    kept_for = await _kept_for(conn, memory_ids)
    checks = await _checks(conn, rec_ids, entities)

    options: list[OptionView] = []
    for label in dict.fromkeys(r["option"] for r in recs):
        mine = [r for r in recs if r["option"] == label]
        ids = {r["id"] for r in mine}
        own = _dedupe(s for s in sources if s["recommendation_id"] in ids)
        options.append(
            OptionView(
                label=label,
                recommended=label == plan.recommended_option,
                summary=mine[0]["text"],
                specialists=list(dict.fromkeys(r["specialist"] for r in mine)),
                allocations=sorted(
                    (_allocation(r, by_entity) for r in mine), key=lambda a: (a.area, a.name)
                ),
                why=Why(
                    figures=[
                        uuid.UUID(s["source_id"]) for s in own if s["source_kind"] == "figure"
                    ],
                    facts=[uuid.UUID(s["source_id"]) for s in own if s["source_kind"] == "fact"],
                    decisions=[
                        decisions[uuid.UUID(s["source_id"])]
                        for s in own
                        if s["source_kind"] == "decision" and uuid.UUID(s["source_id"]) in decisions
                    ],
                    memories=[
                        MemoryWhy(
                            s["source_kind"],
                            s["source_id"],
                            s["quote"],
                            kept_for.get(s["source_id"]),
                        )
                        for s in own
                        if s["source_kind"] in ("memory", "knowledge")
                    ],
                    words=[
                        Words(s["quote"] or turn.message or "", turn.said_by)
                        for s in own
                        if s["source_kind"] == "conversation"
                    ],
                ),
                checks=[c for r in mine for c in checks.get(r["id"], [])],
            )
        )
    # The memories' facts are part of the why too.
    extra = [facts_by_id[i] for i in kept_for.values() if i in facts_by_id and i not in why_facts]
    why_facts.update(await _facts(conn, extra, by_entity, facts_by_id))

    reconciliations = [
        ReconciliationView(
            kind=r["kind"],
            specialists=list(r["specialists"]),
            resolution=r["resolution"],
            rejected=r["rejected"],
            attempts=r["attempts"],
        )
        for r in (
            await conn.execute(
                select(RECONCILIATION)
                .where(RECONCILIATION.c.plan_id == plan_id)
                .order_by(RECONCILIATION.c.kind, RECONCILIATION.c.id)
            )
        ).mappings()
    ]
    changed = await _changed(conn, household_id, plan, m["calc_run_id"], entities, facts, by_entity)
    return PlanView(
        plan=plan,
        summary=m["summary"],
        options=options,
        reconciliations=reconciliations,
        turn=turn,
        changed=changed,
        figures=figures,
        facts=why_facts,
    )


def _dedupe(rows: Iterable[RowMapping]) -> list[RowMapping]:
    """An option's sources, once each: every allocation of an option carries the same ones."""
    seen: dict[tuple[str, str], RowMapping] = {}
    for row in rows:
        seen.setdefault((row["source_kind"], row["source_id"]), row)
    return list(seen.values())


def _allocation(row: RowMapping, entities: Mapping[uuid.UUID, EntityRow]) -> Allocation:
    entity = entities.get(row["entity_id"]) if row["entity_id"] else None
    centavos = row["allocation"]
    return Allocation(
        recommendation_id=row["id"],
        entity_id=row["entity_id"],
        name=entity.name if entity is not None else "the household",
        area=row["area"],
        specialist=row["specialist"],
        centavos=centavos,
        shown=f"{money(centavos)} a month" if centavos is not None else "no amount",
    )


def _figure(row: RowMapping) -> Figure:
    unit, numeric, value_date = row["unit"], row["value_numeric"], row["value_date"]
    value: Any
    if unit == "date":
        value = value_date
    elif numeric is None:
        value = None
    elif unit == "ratio":
        value = numeric
    else:
        value = int(numeric)
    return Figure(
        key=row["key"],
        entity_id=row["entity_id"],
        unit=unit,
        value=value,
        flag=row["flag"],
        formula=row["formula"],
        input_fact_ids=(),
        input_override_ids=(),
        input_figures=(),
    )


async def _figure_closure(
    conn: AsyncConnection, start: set[uuid.UUID]
) -> dict[uuid.UUID, RowMapping]:
    """The cited figures and every figure they were built from, a level at a time."""
    found: dict[uuid.UUID, RowMapping] = {}
    wanted = set(start)
    while wanted and len(found) < MAX_FIGURES:
        rows = (await conn.execute(select(FIGURE).where(FIGURE.c.id.in_(wanted)))).mappings()
        wanted = set()
        for row in rows:
            found[row["id"]] = row
            wanted |= {i for i in row["input_figure_ids"] if i not in found}
    return found


async def _what_ifs(
    conn: AsyncConnection, run_ids: set[uuid.UUID], entities: Mapping[uuid.UUID, EntityRow]
) -> dict[uuid.UUID, str]:
    """Each what-if run among `run_ids`, as the amounts it tried: "Credit card ₱10,000.00 a
    month; Emergency fund ₱15,050.00 a month"."""
    if not run_ids:
        return {}
    rows = await conn.execute(
        select(CALC_RUN.c.id, OVERRIDE.c.entity_id, OVERRIDE.c.attribute, OVERRIDE.c.value_money)
        .join(OVERRIDE, OVERRIDE.c.scenario_id == CALC_RUN.c.scenario_id)
        .where(CALC_RUN.c.id.in_(run_ids))
    )
    parts: dict[uuid.UUID, list[str]] = {}
    for run_id, entity_id, attr, value in rows:
        entity = entities.get(entity_id) if entity_id else None
        name = entity.name if entity is not None else "the household"
        if attr == "plan.allocation" and value is not None:
            parts.setdefault(run_id, []).append(f"{name} {money(value)} a month")
        else:
            parts.setdefault(run_id, []).append(f"{name} {attr}")
    return {run_id: "; ".join(sorted(p)) for run_id, p in parts.items()}


async def _facts(
    conn: AsyncConnection,
    rows: Sequence[FactRow],
    entities: Mapping[uuid.UUID, EntityRow],
    every: Mapping[uuid.UUID, FactRow],
) -> dict[uuid.UUID, FactWhy]:
    """Each fact with where it came from and who said yes to it."""
    found = await provenance(conn, rows)
    out: dict[uuid.UUID, FactWhy] = {}
    for fact in rows:
        entity = entities.get(fact.entity_id) if fact.entity_id else None
        old = every.get(fact.replaces) if fact.replaces else None
        shared_on = found[fact.id].shared_on
        out[fact.id] = FactWhy(
            id=fact.id,
            title=fact_title(fact, entity),
            value=fact_value(fact),
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            status=fact.status,
            source=found[fact.id].source,
            shared=f"Shared with every agent in Meko on {day(shared_on)}" if shared_on else None,
            replaced=fact_value(old) if old is not None else None,
        )
    return out


async def _decisions(conn: AsyncConnection, ids: set[uuid.UUID]) -> dict[uuid.UUID, DecisionWhy]:
    if not ids:
        return {}
    heads = list(
        (
            await conn.execute(
                select(
                    DECISION.c.id,
                    DECISION.c.question,
                    DECISION.c.reasoning,
                    DECISION.c.valid_from,
                    DECISION.c.status,
                    DECISION.c.chosen_option_id,
                    SESSION.c.title,
                )
                .join(SESSION, SESSION.c.id == DECISION.c.session_id)
                .where(DECISION.c.id.in_(ids))
            )
        ).mappings()
    )
    options: dict[uuid.UUID, list[RowMapping]] = {}
    for row in (
        await conn.execute(
            select(OPTION).where(OPTION.c.decision_id.in_(ids)).order_by(OPTION.c.label)
        )
    ).mappings():
        options.setdefault(row["decision_id"], []).append(row)
    out = {}
    for d in heads:
        mine = options.get(d["id"], [])
        chosen = next((o["label"] for o in mine if o["id"] == d["chosen_option_id"]), "")
        out[d["id"]] = DecisionWhy(
            id=d["id"],
            question=d["question"],
            chosen=chosen,
            reasoning=d["reasoning"],
            session_title=d["title"],
            on=d["valid_from"],
            status=d["status"],
            rejected=[
                RejectedOption(o["label"], o["rejected_reason"] or "")
                for o in mine
                if o["id"] != d["chosen_option_id"]
            ],
        )
    return out


async def _kept_for(conn: AsyncConnection, memory_ids: Sequence[str]) -> dict[str, uuid.UUID]:
    """The fact each Meko memory is kept for, when Kako wrote it (`meko_link`)."""
    if not memory_ids:
        return {}
    rows = await conn.execute(
        select(MEKO_LINK.c.meko_id, MEKO_LINK.c.kako_id).where(
            MEKO_LINK.c.meko_id.in_(list(memory_ids)), MEKO_LINK.c.kako_table == "fact"
        )
    )
    return {meko_id: kako_id for meko_id, kako_id in rows}


async def _checks(
    conn: AsyncConnection, rec_ids: Sequence[uuid.UUID], entities: Sequence[EntityRow]
) -> dict[uuid.UUID, list[Check]]:
    """The final number check on each recommendation's texts: what each number matched."""
    if not rec_ids:
        return {}
    refs = EntityRefs.of(entities)
    words = Refs({ref: e for e in entities if (ref := refs.by_id.get(e.id))})
    out: dict[uuid.UUID, list[Check]] = {}
    seen: set[tuple[uuid.UUID, str]] = set()
    rows = await conn.execute(
        select(
            NUMBER_CHECK.c.subject_id,
            NUMBER_CHECK.c.checked_text,
            NUMBER_CHECK.c.numbers,
            NUMBER_CHECK.c.result,
        )
        .where(
            NUMBER_CHECK.c.subject == "recommendation",
            NUMBER_CHECK.c.subject_id.in_(list(rec_ids)),
            NUMBER_CHECK.c.result.in_(("pass", "fail")),
        )
        .order_by(NUMBER_CHECK.c.created_at, NUMBER_CHECK.c.id)
    )
    for subject_id, checked, numbers, result in rows:
        if (subject_id, checked) in seen:
            continue
        seen.add((subject_id, checked))
        out.setdefault(subject_id, []).append(
            Check(
                text=checked,
                result=result,
                numbers=[
                    CheckedNumber(str(n.get("text", "")), matched_words(n.get("match"), words))
                    for n in numbers or []
                    if n.get("kind") != "code"
                ],
            )
        )
    return out


async def _turn(
    conn: AsyncConnection,
    plan_id: uuid.UUID,
    session_id: uuid.UUID,
    conversation_id: str,
    recs: Sequence[RowMapping],
) -> TurnView:
    """The turn that proposed the plan: the kept turn that names it, else its recommendations'."""
    row = (
        await conn.execute(
            select(
                SESSION_TURN.c.meko_turn_seed,
                SESSION_TURN.c.message,
                SESSION_TURN.c.created_at,
                PERSON.c.display_name,
            )
            .outerjoin(PERSON, PERSON.c.id == SESSION_TURN.c.said_by)
            .where(
                SESSION_TURN.c.session_id == session_id,
                SESSION_TURN.c.shown["plan"]["id"].astext == str(plan_id),
            )
        )
    ).first()
    if row is not None:
        return TurnView(session_id, row[0], conversation_id, row[1], row[3], row[2], [])
    seed = recs[0]["meko_turn_seed"] if recs else None
    return TurnView(session_id, seed, conversation_id, None, None, None, [])


async def _meko_calls(
    conn: AsyncConnection,
    session_id: uuid.UUID,
    kept_at: datetime | None,
    started_at: datetime,
    seed: str | None,
) -> list[MekoCallView]:
    """The Meko calls the turn made: the session's, after the turn before it was kept and up to
    this one being kept. Unknown (empty) when the turn wasn't kept on screen."""
    if kept_at is None or seed is None:
        return []
    before = (
        await conn.execute(
            select(func.max(SESSION_TURN.c.created_at)).where(
                SESSION_TURN.c.session_id == session_id, SESSION_TURN.c.created_at < kept_at
            )
        )
    ).scalar_one()
    since = before or started_at
    rows = await conn.execute(
        select(
            MEKO_CALL.c.tool,
            MEKO_CALL.c.agent_id,
            MEKO_CALL.c.latency_ms,
            MEKO_CALL.c.result_count,
            MEKO_CALL.c.outcome,
            MEKO_CALL.c.created_at,
        )
        .where(
            MEKO_CALL.c.session_id == session_id,
            MEKO_CALL.c.created_at > since,
            MEKO_CALL.c.created_at <= kept_at,
        )
        .order_by(MEKO_CALL.c.created_at, MEKO_CALL.c.id)
    )
    return [MekoCallView(*r) for r in rows]


async def _changed(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    plan: PlanRow,
    run_id: uuid.UUID,
    entities: list[EntityRow],
    facts: list[FactRow],
    by_entity: Mapping[uuid.UUID, EntityRow],
) -> Changed | None:
    """What changed against the household's previous plan, or, for its first, against the run it
    last decided on (as Kako knew it then). None when there is neither."""
    after = await load_run(conn, run_id)
    # As Kako knew things when the plan's figures were taken: never a decision made on this plan.
    known_at = after.known_at or plan.created_at
    previous = (
        await conn.execute(
            select(PLAN.c.id, PLAN.c.version, PLAN.c.calc_run_id, PLAN.c.created_at)
            .where(PLAN.c.household_id == household_id, PLAN.c.version < plan.version)
            .order_by(PLAN.c.version.desc())
            .limit(1)
        )
    ).first()
    before: Run
    since_plan: uuid.UUID | None = None
    if previous is not None:
        before = await load_run(conn, previous.calc_run_id)
        since = f"plan v{previous.version} of {day(before.as_of)}"
        since_plan = previous.id
    else:
        last = await last_decision(conn, household_id, after.as_of, known_at)
        if last is None:
            return None
        _, on, decided_at, since = last
        before = compute(take_snapshot(household_id, facts, on, decided_at), entities)
    decisions = await _active_decisions(conn, household_id, after.as_of, known_at)
    assumed: dict[uuid.UUID, list[uuid.UUID]] = {d: [] for d in decisions}
    if decisions:
        for decision_id, fact_id in await conn.execute(
            select(ASSUMPTION.c.decision_id, ASSUMPTION.c.fact_id).where(
                ASSUMPTION.c.decision_id.in_(list(decisions))
            )
        ):
            assumed[decision_id].append(fact_id)
    found = diff(before, after, facts, assumed)
    revisit = [
        Revisit(
            decision_id=r.decision_id,
            question=decisions[r.decision_id][0],
            chosen=decisions[r.decision_id][1],
            session_title=decisions[r.decision_id][2],
            decided_on=decisions[r.decision_id][3],
            because=[changed_fact(f, by_entity) for f in r.facts],
        )
        for r in found.decisions
    ]
    return Changed(since, since_plan, what_changed(found, entities), revisit)


async def _active_decisions(
    conn: AsyncConnection, household_id: uuid.UUID, on: date, known_at: datetime
) -> dict[uuid.UUID, tuple[str, str, str, date]]:
    """The decisions in force on `on`, as Kako knew them at `known_at`: question, chosen option,
    session and date."""
    rows = await conn.execute(
        select(
            DECISION.c.id,
            DECISION.c.question,
            OPTION.c.label,
            SESSION.c.title,
            DECISION.c.valid_from,
        )
        .join(PROPOSAL, PROPOSAL.c.id == DECISION.c.proposal_id)
        .join(OPTION, OPTION.c.id == DECISION.c.chosen_option_id)
        .join(SESSION, SESSION.c.id == DECISION.c.session_id)
        .where(
            DECISION.c.household_id == household_id,
            DECISION.c.valid_from <= on,
            PROPOSAL.c.decided_at <= known_at,
            (DECISION.c.valid_to.is_(None)) | (DECISION.c.valid_to > on),
        )
        .order_by(DECISION.c.valid_from, DECISION.c.id)
    )
    return {r[0]: (r[1], r[2], r[3], r[4]) for r in rows}
