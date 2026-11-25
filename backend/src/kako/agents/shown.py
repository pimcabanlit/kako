"""A turn as the household is shown it: the session API's answer, and what `session_turn` keeps.

Built by code from what the turn kept (`agents.ask.Asked`): the reply and the texts as
number-checked, each option's allocations and sources, how a conflict ended, the numbers the check
flagged, the changes waiting for a yes, a replan's other two parts, the plan's ids and what the
turn cost. A session read later shows exactly this, so the screen never rebuilds an answer from
parts.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel

from kako.agents.answers import Citation, TurnAnswer
from kako.agents.present import figure_value, money
from kako.agents.reconciling import LABELS
from kako.agents.replan import changes_lines, why_lines
from kako.agents.scenarios import shown_value
from kako.facts.model import EntityRow
from kako.planning.why import HEADLINE, figure_title
from kako.settings import Settings
from kako.upkeep.sentences import PHRASES

if TYPE_CHECKING:
    from kako.agents.ask import Asked
    from kako.agents.calculator import Calculation
    from kako.agents.scenarios import Change
    from kako.agents.tools import TurnState, WhatIf

LOCAL_PREFIX: Final = "local-"  # a session's id with no Meko conversation
SOURCE_CHARS: Final = 600  # the most of a source's words shown (a document is cited whole)


class AllocationOut(BaseModel):
    entity: str  # the stable ref, such as debt:credit-card
    name: str  # the entity's name, as the household wrote it
    centavos: int
    shown: str
    spec: str


class SourceOut(BaseModel):
    kind: str
    ref: str
    shown: str


class OptionOut(BaseModel):
    label: str
    summary: str
    what_if: str
    recommended: bool
    allocations: list[AllocationOut]
    sources: list[SourceOut]
    specialists: list[str]
    recommendation_ids: list[uuid.UUID]


class ResolutionOut(BaseModel):
    conflicts: list[str]
    described: list[str]
    together: str
    splits: list[str]
    chosen: str | None
    rejected: str | None
    reason: str
    reconciliation_ids: list[uuid.UUID]


class FlaggedOut(BaseModel):
    text: str
    where: str


class ProposalOut(BaseModel):
    specialist: str
    what_if: str | None
    summary: str


class ChangeOut(BaseModel):
    """A change the household stated, pending until a person approves it (`/api/v1/proposals`)."""

    proposal_id: uuid.UUID
    kind: str
    shown: str


class ReplanOut(BaseModel):
    """A replan's other two parts: what changed (from code's diff) and why."""

    since: str
    what_changed: list[str]
    why: str | None  # the orchestrator's, number-checked
    because: list[str]  # the facts behind it and the decisions to revisit, from code
    before_run_id: uuid.UUID | None
    revisit_decision_ids: list[uuid.UUID]


class PlanOut(BaseModel):
    id: uuid.UUID
    version: int
    status: Literal["proposed"]


class MekoTurnOut(BaseModel):
    conversation_id: str | None
    message_id: str | None
    error: str | None
    trace_url: str | None


class CostOut(BaseModel):
    model_calls: int
    input_tokens: int
    output_tokens: int
    usd: str  # a decimal string: money is never a float
    # The brief every agent of the turn was sent, estimated high, and its budget then (the
    # metrics page). None on a turn kept before they were.
    brief_tokens: int | None = None
    brief_budget: int | None = None


class FigureChangeOut(BaseModel):
    """One figure a what-if moves, before and after, in words."""

    title: str  # "Money left over each month"
    before: str  # "₱9,050.00", or "none" for a new item's
    after: str


class ScenarioOut(BaseModel):
    """A what-if the answer rests on that changes facts or adds items: never saved as a fact,
    shown with what it assumed and what it moves ("Scenario, nothing saved")."""

    what_if: str
    changes: list[str]  # each change in words: "Jun's salary (take-home pay a month): A → B"
    assumptions: list[str]  # the values Kako assumed, not the household's
    figures: list[FigureChangeOut]
    note: str  # how it was run


class CalculationOut(BaseModel):
    """A calculation the answer cites, with its working."""

    ref: str
    label: str
    formula: str
    inputs: list[str]  # "income = ₱60,000.00 (figure: monthly income)"
    result: str


class TurnOut(BaseModel):
    session_id: uuid.UUID
    seed: str
    reply: str
    options: list[OptionOut]
    recommended: str | None
    resolution: ResolutionOut | None
    flagged: list[FlaggedOut]
    proposals: list[ProposalOut]
    changes: list[ChangeOut]  # waiting for the household's yes
    not_proposed: list[str]  # changes the store refused, with why
    replan: ReplanOut | None
    plan: PlanOut | None
    calc_run_id: uuid.UUID | None
    meko: MekoTurnOut
    cost: CostOut
    # The kind of answer, what it rests on, and how it was worked out (none on a turn kept before
    # answers had them): the labels under the reply, its sources, the scenarios and calculations.
    kind: str | None = None
    labels: list[str] = []
    sources: list[SourceOut] = []
    scenarios: list[ScenarioOut] = []
    calculations: list[CalculationOut] = []


SCENARIO_NOTE: Final = (
    "Worked out by Kako's engine for this question only. Nothing was saved, and the household's "
    "facts are unchanged. Changes are run as if they start today."
)
MAX_SCENARIO_FIGURES: Final = 10


def _change_words(change: Change, names: dict[uuid.UUID, str]) -> str:
    phrase = PHRASES.get(change.attribute, change.attribute)
    thing = names.get(change.entity_id, change.name) if change.entity_id else "The household"
    after = shown_value(change.attribute, change.after)
    if change.before is None:
        return f"{thing} ({phrase}): {after}"
    return f"{thing} ({phrase}): {shown_value(change.attribute, change.before)} → {after}"


def scenario_shown(state: TurnState, what_if: WhatIf) -> ScenarioOut:
    """A hypothetical what-if as the household reads it: what it changed, what Kako assumed, and
    the headline figures before and after."""
    names = {e.id: e.name for e in (*state.entities, *(n.entity for n in what_if.new))}
    every = [*what_if.changes, *(v for n in what_if.new for v in n.values)]
    changes = [_change_words(c, names) for c in what_if.changes]
    for item in what_if.new:
        values = ", ".join(
            f"{PHRASES.get(v.attribute, v.attribute)} {shown_value(v.attribute, v.after)}"
            for v in item.values
        )
        changes.append(f"New {item.entity.kind}, {item.entity.name}: {values}")
    changes += [
        f"{names.get(a.entity_id, a.entity_ref)} (planned amount a month): {money(a.centavos)}"
        for a in what_if.allocations
    ]
    base = {f.ref: f for f in state.run.figures}
    rank = {key: n for n, key in enumerate(HEADLINE)}
    moved = [
        f
        for f in what_if.run.figures
        if base.get(f.ref) is None or (base[f.ref].value, base[f.ref].flag) != (f.value, f.flag)
    ]
    nobody = uuid.UUID(int=0)
    moved.sort(
        key=lambda f: (rank.get(f.key, len(rank)), f.key, names.get(f.entity_id or nobody, ""))
    )
    figures = [
        FigureChangeOut(
            title=figure_title(f.key, _entity(f.entity_id, names)),
            before=figure_value(base[f.ref]) if f.ref in base else "none",
            after=figure_value(f),
        )
        for f in moved[:MAX_SCENARIO_FIGURES]
    ]
    return ScenarioOut(
        what_if=what_if.ref,
        changes=changes,
        assumptions=[_change_words(c, names) for c in every if c.assumed],
        figures=figures,
        note=SCENARIO_NOTE,
    )


def _entity(entity_id: uuid.UUID | None, names: dict[uuid.UUID, str]) -> EntityRow | None:
    if entity_id is None or entity_id not in names:
        return None
    return EntityRow(entity_id, uuid.UUID(int=0), "", names[entity_id], None, None)


def calculation_shown(calc: Calculation) -> CalculationOut:
    return CalculationOut(
        ref=calc.ref,
        label=calc.label,
        formula=calc.formula,
        inputs=[
            f"{i.name} = {i.shown} ({'assumed by Kako' if i.assumed else i.source})"
            for i in calc.inputs
        ],
        result=calc.shown,
    )


def labels_of(answer: TurnAnswer, state: TurnState | None) -> list[str]:
    """The labels under a reply, from what it is and what it cites: General information,
    Scenario, nothing saved, Calculated, From your documents."""
    labels: list[str] = []
    if answer.kind in ("inform", "advise") and not any(
        c.kind in ("figure", "fact", "history") for c in answer.sources
    ):
        labels.append("General information")
    hypothetical = state is not None and any(
        c.what_if in state.what_ifs and state.what_ifs[c.what_if].hypothetical
        for c in answer.sources
        if c.what_if is not None
    )
    if hypothetical:
        labels.append("Scenario, nothing saved")
    if any(c.kind == "calculation" for c in answer.sources):
        labels.append("Calculated")
    if any(c.kind == "knowledge" for c in answer.sources):
        labels.append("From your documents")
    return labels


def _source_out(c: Citation) -> SourceOut:
    return SourceOut(kind=c.kind, ref=c.ref, shown=c.shown[:SOURCE_CHARS])


def turn_shown(asked: Asked, settings: Settings) -> TurnOut:
    """The turn as the household is shown it, built by code from what the turn kept."""
    answer, saved = asked.answer, asked.saved
    recs = saved.recommendations if saved is not None else {}
    names = {e.id: e.name for e in asked.state.entities} if asked.state is not None else {}
    options = [
        OptionOut(
            label=o.label,
            summary=o.summary,
            what_if=o.what_if,
            recommended=o.label == answer.recommended,
            allocations=[
                AllocationOut(
                    entity=a.entity_ref,
                    name=names.get(a.entity_id, a.entity_ref),
                    centavos=a.centavos,
                    shown=money(a.centavos),
                    spec=a.spec,
                )
                for a in o.allocations
            ],
            sources=[_source_out(c) for c in o.citations],
            specialists=list(o.specialists),
            recommendation_ids=list(recs.get(o.label, ())),
        )
        for o in answer.options
    ]
    resolution = None
    if answer.resolution is not None:
        r = answer.resolution
        resolution = ResolutionOut(
            conflicts=[LABELS[c.kind] for c in r.conflicts],
            described=list(r.described),
            together=r.together,
            splits=[f"{s.what_if}: {'fits' if s.fits else 'refused'}" for s in r.splits],
            chosen=r.chosen,
            rejected=r.rejected,
            reason=r.reason,
            reconciliation_ids=list(saved.reconciliations) if saved is not None else [],
        )
    checks = [*answer.checks, *(p.check for p in answer.proposals if p.check is not None)]
    flagged = [FlaggedOut(text=n.text, where=c.label) for c in checks for n in c.unmatched]
    plan = None
    if saved is not None and saved.plan_id is not None and saved.version is not None:
        plan = PlanOut(id=saved.plan_id, version=saved.version, status="proposed")
    replan = None
    if asked.replan is not None and asked.state is not None:
        entities = asked.state.entities
        replan = ReplanOut(
            since=asked.replan.since,
            what_changed=[line[2:] for line in changes_lines(asked.replan, entities)[1:]],
            why=answer.why,
            because=[line[2:] for line in why_lines(asked.replan, entities)[1:]],
            before_run_id=asked.before_run_id,
            revisit_decision_ids=[r.decision_id for r in asked.replan.revisit],
        )
    state = asked.state
    scenarios: list[ScenarioOut] = []
    calculations: list[CalculationOut] = []
    if state is not None:
        cited_what_ifs = dict.fromkeys(
            c.what_if for c in answer.sources if c.what_if in state.what_ifs
        )
        scenarios = [
            scenario_shown(state, state.what_ifs[ref])
            for ref in cited_what_ifs
            if ref is not None and state.what_ifs[ref].hypothetical
        ]
        calculations = [
            calculation_shown(state.calculations[c.source_id])
            for c in answer.sources
            if c.kind == "calculation" and c.source_id in state.calculations
        ]
    conversation = asked.conversation_id
    in_meko = conversation is not None and not conversation.startswith(LOCAL_PREFIX)
    return TurnOut(
        session_id=asked.session_id,
        seed=asked.seed,
        reply=answer.reply,
        options=options,
        recommended=answer.recommended,
        resolution=resolution,
        flagged=flagged,
        proposals=[
            ProposalOut(specialist=p.specialist, what_if=p.what_if, summary=p.summary)
            for p in answer.proposals
        ],
        changes=[
            ChangeOut(proposal_id=p.proposal_id, kind=p.kind, shown=p.shown) for p in asked.proposed
        ],
        not_proposed=list(asked.proposal_errors),
        replan=replan,
        plan=plan,
        calc_run_id=asked.calc_run_id,
        meko=MekoTurnOut(
            conversation_id=conversation if in_meko else None,
            message_id=asked.meko_message_id,
            error=asked.meko_error,
            trace_url=settings.meko_trace_url(conversation) if in_meko and conversation else None,
        ),
        cost=CostOut(
            model_calls=asked.model_calls,
            input_tokens=asked.input_tokens,
            output_tokens=asked.output_tokens,
            usd=f"{asked.cost_usd:.6f}",
            brief_tokens=asked.state.brief.tokens if asked.state is not None else None,
            brief_budget=asked.state.brief.budget if asked.state is not None else None,
        ),
        kind=answer.kind,
        labels=labels_of(answer, state),
        sources=[_source_out(c) for c in answer.sources],
        scenarios=scenarios,
        calculations=calculations,
    )
