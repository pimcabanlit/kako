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

from kako.agents.present import money
from kako.agents.reconciling import LABELS
from kako.agents.replan import changes_lines, why_lines
from kako.settings import Settings

if TYPE_CHECKING:
    from kako.agents.ask import Asked

LOCAL_PREFIX: Final = "local-"  # a session's id with no Meko conversation


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
            sources=[SourceOut(kind=c.kind, ref=c.ref, shown=c.shown) for c in o.citations],
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
        ),
    )
