"""A planning session and its turns: `kako ask` and the session API.

A session is one Meko conversation, when Meko is in use, and its `session` row. A turn gathers the
brief, stores the turn's run, runs the orchestrator and its specialists through the model manager,
and keeps what it found: each what-if as a scenario with its run, the plan it proposes with its
recommendations, their sources and any reconciliation (`db.plan_store`), and every text's number
check. Then the turn goes to Meko with the steps taken (`plan`), why (`reasoning`) and the ids of
what Kako stored (`metadata`), so Meko's trace and Kako's tables say the same thing. Every model
call goes to `llm_call`, every tool call to `agent_step` and every Meko call to `meko_call`.

Which model answers is `KAKO_MODEL_MODE`'s choice: live Claude (or Foundry), recording a live run to
`KAKO_RECORDED_RESPONSES`, or replaying that file with no network.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.answers import TurnAnswer
from kako.agents.brief_store import gather_brief
from kako.agents.checks import record
from kako.agents.conversation import history
from kako.agents.lookups import documents_of
from kako.agents.model_manager import ModelManager
from kako.agents.orchestrator import answer_turn
from kako.agents.present import money
from kako.agents.prompt_registry import PromptVersion, versions_json
from kako.agents.reconciling import LABELS, render_resolution
from kako.agents.recorded import ChatBackend
from kako.agents.replan import Replan, changes_lines, why_lines
from kako.agents.replan_store import session_changes
from kako.agents.shown import LOCAL_PREFIX as LOCAL_PREFIX  # where other modules read it
from kako.agents.shown import TurnOut, turn_shown
from kako.agents.tools import TurnState
from kako.agents.turn import TurnContext
from kako.db.agent_steps import DbStepLog
from kako.db.calc_store import save_run
from kako.db.llm_log import DbLlmLog
from kako.db.meko_log import DbCallLog
from kako.db.models import LlmCall, Session
from kako.db.number_checks import DbCheckLog
from kako.db.plan_store import SavedAnswer, save_answer
from kako.db.proposal_store import Evidence, ProposalError, propose
from kako.db.turn_store import KeptContext, TurnStoreError, keep_turn
from kako.facts.proposals import PayloadError, idempotency_key
from kako.health import safe_error
from kako.meko.adapter import Meko, Turn
from kako.meko.client import MekoError
from kako.settings import Settings

SESSION = cast(Table, Session.__table__)
LLM_CALL = cast(Table, LlmCall.__table__)
AGENT = "kako:orchestrator"
# What answers a turn: the orchestrator with its specialists, or the single-agent baseline.
Answerer = Callable[[ModelManager, TurnContext, TurnState], Awaitable[TurnAnswer]]
REASONING_CHARS: Final = 4_000
# A turn's Meko calls at most: the conversation, the brief's search, one extra search for the
# orchestrator and each of its 4 specialist asks, and the turn itself.
MEKO_CALLS: Final = 8


class SessionError(Exception):
    """A session that can't be found or can't take a turn."""


@dataclass(frozen=True)
class Started:
    """A planning session: its row and its Meko conversation."""

    session_id: uuid.UUID
    household_id: uuid.UUID
    conversation_id: str  # LOCAL_PREFIX…: no Meko conversation
    title: str
    on: date  # the household's date for the session

    @property
    def in_meko(self) -> bool:
        return not self.conversation_id.startswith(LOCAL_PREFIX)


@dataclass(frozen=True)
class StoredProposal:
    """A change the household stated, kept as a pending proposal for its yes."""

    proposal_id: uuid.UUID
    kind: str
    shown: str  # in plain words


@dataclass(frozen=True)
class Asked:
    answer: TurnAnswer
    session_id: uuid.UUID
    seed: str
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal  # real calls only; a replay costs nothing
    saved: SavedAnswer | None = None
    calc_run_id: uuid.UUID | None = None
    conversation_id: str | None = None
    meko_message_id: str | None = None  # the turn in Meko's conversation
    meko_error: str | None = None  # why Meko didn't keep the turn, if it didn't
    what_if_runs: dict[str, uuid.UUID] = field(default_factory=dict)
    state: TurnState | None = None  # what the turn's tools read: the snapshot, refs and what-ifs
    proposed: tuple[StoredProposal, ...] = ()  # waiting for a person's yes
    proposal_errors: tuple[str, ...] = ()  # changes the store refused, with why
    before_run_id: uuid.UUID | None = None  # in a replan: the run it was compared with, stored
    shown: TurnOut | None = None  # the turn as the household is shown it, kept in `session_turn`

    @property
    def replan(self) -> Replan | None:
        return self.state.inputs.replan if self.state is not None else None


async def start_session(
    engine: AsyncEngine,
    meko: Meko | None,
    *,
    household_id: uuid.UUID,
    on: date,
    title: str,
    call_log: DbCallLog | None = None,
) -> Started:
    """A new session: its Meko conversation (with Meko), then its row. `call_log`, the log the
    Meko adapter counts calls in, is bound to the session once it exists."""
    started = datetime.now(UTC)
    session_id = uuid.uuid4()
    if meko is not None:
        conversation = await meko.create_conversation(
            agent_id=AGENT, title=title, session_key=f"kako-session-{session_id.hex}"
        )
    else:
        conversation = f"{LOCAL_PREFIX}{uuid.uuid4().hex}"  # the session still needs an id
    async with engine.begin() as conn:
        await conn.execute(
            SESSION.insert().values(
                id=session_id,
                household_id=household_id,
                meko_conversation_id=conversation,
                title=title,
                household_date=on,
                started_at=started,
            )
        )
    if call_log is not None:
        await call_log.bind(session_id)
    return Started(session_id, household_id, conversation, title, on)


async def load_session(engine: AsyncEngine, session_id: uuid.UUID) -> Started:
    async with engine.connect() as conn:
        row = (
            (await conn.execute(select(SESSION).where(SESSION.c.id == session_id)))
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise SessionError("no such session")
    if row["ended_at"] is not None:
        raise SessionError("the session has ended")
    return Started(
        row["id"],
        row["household_id"],
        row["meko_conversation_id"],
        row["title"],
        row["household_date"],
    )


async def run_turn(
    engine: AsyncEngine,
    meko: Meko | None,
    settings: Settings,
    backend: ChatBackend,
    session: Started,
    *,
    message: str,
    known_at: datetime | None,
    seed: str,
    answerer: Answerer = answer_turn,
    speaker: uuid.UUID | None = None,
) -> Asked:
    """Answer the household's `message` in `session`, as of the session's date (and as known at
    `known_at`), and keep it: the plan in Postgres, the turn in Meko. `answerer` is the
    orchestrator and its specialists; the agent test set also passes the single-agent baseline.
    `speaker`: the person who wrote the message, named on what it proposes.

    Once a person has approved a change stated in this session, its turns are a replan: as of the
    date the change takes effect, compared with the plan the household last decided on
    (`agents.replan`)."""
    if meko is not None and not session.in_meko:
        raise SessionError("this session has no Meko conversation")
    conversation = session.conversation_id if meko is not None else None
    async with engine.connect() as conn:
        changes = await session_changes(
            conn, session.household_id, session.session_id, session.on, known_at
        )
        brief, inputs = await gather_brief(
            conn,
            meko,
            household_id=session.household_id,
            on=changes.on if changes is not None else session.on,
            known_at=known_at,
            message=message,
            conversation_id=conversation,
            budget=settings.brief_token_budget,
            search_limit=settings.brief_search_limit,
            changes=changes,
            session_on=session.on,
            session_id=session.session_id,
            speaker=speaker,
        )
    before_run_id = None
    async with engine.connect() as conn:
        # The turn's run, stored with its figures: what the number check holds the texts to.
        calc_run_id = await save_run(conn, inputs.run, created_at=datetime.now(UTC))
        if inputs.replan is not None:  # and the run it is compared with, so each change traces
            before_run_id = await save_run(conn, inputs.replan.before, created_at=datetime.now(UTC))
    checks = DbCheckLog(engine, session_id=session.session_id, calc_run_id=calc_run_id)
    state = TurnState(
        brief,
        inputs,
        seed,
        meko,
        conversation,
        checks=checks,
        said_on=session.on,
        history=history(inputs.earlier, settings.history_token_budget),
        documents=documents_of(settings),
    )
    manager = ModelManager(settings, backend, DbLlmLog(engine))
    turn = manager.turn(
        seed, session_id=session.session_id, steps=DbStepLog(engine, session.session_id)
    )
    answer = await answerer(manager, turn, state)
    saved = await save_answer(
        engine,
        state,
        answer,
        session_id=session.session_id,
        calc_run_id=calc_run_id,
        conversation_id=session.conversation_id,
        what_if_steps=turn.what_if_steps,
    )
    for check in answer.checks:  # each text as shown: passed, or with its numbers flagged
        await checks.write(record(check, check.result, saved.subject_id(check)))
    # A turn as known at a time in the story proposes at that time (demo mode); else now.
    proposed, refused = await _keep_proposals(
        engine, state, session, seed, speaker, known_at or datetime.now(UTC)
    )
    message_id = meko_error = None
    if meko is not None and conversation is not None:
        meko_turn = trace_turn(
            message,
            answer,
            saved,
            state,
            calc_run_id,
            session,
            seed,
            proposed,
            before_run_id,
            speaker,
            turn.prompts.values(),
        )
        try:
            message_id = await meko.add_turn(conversation, meko_turn, agent_id=AGENT)
        except MekoError as exc:  # the answer is kept in Postgres; the caller is told
            meko_error = safe_error(exc)
    async with engine.connect() as conn:
        totals = (
            await conn.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(LLM_CALL.c.input_tokens), 0),
                    func.coalesce(func.sum(LLM_CALL.c.output_tokens), 0),
                    func.coalesce(
                        func.sum(LLM_CALL.c.cost_usd).filter(LLM_CALL.c.recorded_replay.is_(False)),
                        0,
                    ),
                ).where(
                    LLM_CALL.c.session_id == session.session_id,
                    LLM_CALL.c.meko_turn_seed == seed,
                )
            )
        ).one()
    asked = Asked(
        answer,
        session.session_id,
        seed,
        totals[0],
        totals[1],
        totals[2],
        Decimal(totals[3]),
        saved,
        calc_run_id,
        session.conversation_id,
        message_id,
        meko_error,
        dict(state.stored),
        state,
        proposed,
        refused,
        before_run_id,
    )
    # The turn as shown, kept for the session screen: what the household reads later is exactly
    # what it read then.
    shown = turn_shown(asked, settings)
    try:
        await keep_turn(
            engine,
            session_id=session.session_id,
            seed=seed,
            said_by=speaker,
            message=message,
            shown=shown.model_dump(mode="json"),
            created_at=datetime.now(UTC),
            context=kept_context(state, answer),
        )
    except TurnStoreError as exc:
        raise SessionError(str(exc)) from None
    return replace(asked, shown=shown)


def kept_context(state: TurnState, answer: TurnAnswer) -> KeptContext:
    """What the turn's agents were given (the brief, the conversation's window, the search) and
    the orchestrator's notes for the next turn, as `turn_context` keeps them."""
    window = state.history.as_json() if state.history is not None else {}
    inputs = state.inputs
    searched = inputs.context is not None
    return KeptContext(
        brief=state.brief.text,
        brief_tokens=state.brief.tokens,
        history=window,
        search_query=(inputs.search or inputs.message) if searched else None,
        topic=answer.topic,
        asks=answer.asks,
    )


async def _keep_proposals(
    engine: AsyncEngine,
    state: TurnState,
    session: Started,
    seed: str,
    speaker: uuid.UUID | None,
    at: datetime,
) -> tuple[tuple[StoredProposal, ...], tuple[str, ...]]:
    """Each change the household stated, as pending proposals with its words as evidence: a change
    in one transaction (a life event with its facts), checked again by the store. A refused change
    is reported, never dropped silently; the answer is kept either way."""
    kept: list[StoredProposal] = []
    refused: list[str] = []
    for change in state.proposed:
        try:
            async with engine.begin() as conn:
                mine = []
                for held in change.proposals:
                    done = await propose(
                        conn,
                        household_id=session.household_id,
                        kind=held.kind,
                        payload=held.payload,
                        explanation=change.explanation,
                        idempotency_key=idempotency_key(
                            f"{session.session_id}:{seed}", held.kind, held.target
                        ),
                        evidence=[
                            Evidence(
                                "turn", f"{session.conversation_id}:{seed}", change.quote, speaker
                            )
                        ],
                        today=session.on,
                        created_at=at,
                    )
                    mine.append(StoredProposal(done.proposal_id, held.kind, held.shown))
            kept += mine
        except (ProposalError, PayloadError) as exc:
            refused.append(f"{change.ref}: {exc}")
    return tuple(kept), tuple(refused)


def trace_turn(
    message: str,
    answer: TurnAnswer,
    saved: SavedAnswer,
    state: TurnState,
    calc_run_id: uuid.UUID,
    session: Started,
    seed: str,
    proposed: Sequence[StoredProposal] = (),
    before_run_id: uuid.UUID | None = None,
    speaker: uuid.UUID | None = None,
    prompts: Iterable[PromptVersion] = (),
) -> Turn:
    """The turn as Meko keeps it: the household's words and the reply, the steps taken, why, and
    the ids of what Kako stored, so the trace and the tables can be read side by side. Built by
    code from what the agents handed in; the texts are the number-checked ones."""
    asked = list(dict.fromkeys(p.specialist for p in answer.proposals))
    steps = ["Read the brief: the household's figures, facts, decisions and Meko's context"]
    if asked:
        steps.append(
            "Asked the " + _and(asked) + (" specialist" if len(asked) == 1 else " specialists")
        )
    resolution = answer.resolution
    if resolution is not None:
        found = _and([LABELS[c.kind] for c in resolution.conflicts])
        outcome = (
            f"chose {resolution.chosen} over {resolution.rejected}"
            if resolution.chosen
            else "left the choice to the household"
        )
        steps.append(f"Reconciled their proposals in code ({found}) and {outcome}")
    replan = state.inputs.replan
    if replan is not None:
        steps.insert(
            1,
            f"Replanned as of {state.snapshot.on.isoformat()} against {replan.since}: "
            f"{len(replan.moved)} figures moved, {len(replan.revisit)} decisions to revisit",
        )
    if proposed:
        steps.append(f"Proposed {len(proposed)} change(s) for the household's yes")
    if answer.options:
        steps.append(
            f"Offered {len(answer.options)} option{'s' if len(answer.options) != 1 else ''}, "
            + (f"recommending {answer.recommended}" if answer.recommended else "none recommended")
        )
    else:
        steps.append("Answered without options")
    reasons = [f"{p.specialist} specialist: {p.summary}" for p in answer.proposals]
    if resolution is not None:
        reasons.append(f"Reconciliation: {resolution.reason}")
    if answer.why:
        reasons.append(f"Why: {answer.why}")
    metadata: dict[str, Any] = {
        "kako_turn": seed,
        "kako_session_id": str(session.session_id),
        "kako_household_id": str(session.household_id),
        "kako_household_date": session.on.isoformat(),
        "kako_calc_run_id": str(calc_run_id),
        "kako_what_if_runs": {ref: str(run) for ref, run in state.stored.items()},
    }
    if versions := versions_json(prompts):  # the prompt texts behind the turn, by name
        metadata["kako_prompts"] = versions
    if speaker is not None:  # who wrote the message: dreaming names them on what it proposes
        metadata["kako_said_by"] = str(speaker)
    if state.history is not None and state.inputs.earlier:  # what the orchestrator read of it
        metadata["kako_context"] = {
            k: v
            for k, v in state.history.as_json().items()
            if k in ("verbatim", "digest", "left_out")
        }
    if answer.topic:
        metadata["kako_topic"] = answer.topic
    # Numbers the check couldn't match, by text: Meko keeps the texts as shown, so a reader of the
    # trace (or Meko's own extraction) can tell which numbers no figure, fact or said amount backs.
    checks = [*answer.checks, *(p.check for p in answer.proposals if p.check is not None)]
    flagged = {c.label: [n.text for n in c.unmatched] for c in checks if c.unmatched}
    if flagged:
        metadata["kako_flagged"] = flagged
    if proposed:
        metadata["kako_proposal_ids"] = [str(p.proposal_id) for p in proposed]
    if replan is not None and before_run_id is not None:
        metadata["kako_replan_before_run_id"] = str(before_run_id)
        if replan.since_decision is not None:
            metadata["kako_replan_since_decision_id"] = str(replan.since_decision)
        metadata["kako_revisit_decision_ids"] = [str(r.decision_id) for r in replan.revisit]
    if saved.plan_id is not None:
        metadata["kako_plan_id"] = str(saved.plan_id)
        metadata["kako_plan_version"] = saved.version
        metadata["kako_recommendation_ids"] = {
            label: [str(i) for i in ids] for label, ids in saved.recommendations.items()
        }
        if saved.reconciliations:
            metadata["kako_reconciliation_ids"] = [str(i) for i in saved.reconciliations]
    output = answer.reply
    if replan is not None:  # the three parts, as the household reads them
        output = "\n\n".join(
            [
                answer.reply,
                "\n".join(changes_lines(replan, state.entities)),
                "\n".join(
                    [
                        *(["Why: " + answer.why] if answer.why else []),
                        *why_lines(replan, state.entities),
                    ]
                ),
            ]
        )
    return Turn(
        input=message,
        output=output,
        plan=tuple(steps[:4]),
        reasoning="\n\n".join(reasons)[:REASONING_CHARS] or None,
        metadata=metadata,
        # Meko makes a turn's message id from its seed alone, so the same seed in two
        # conversations would be one id (and one trace observation): the seed names the session.
        seed=f"{session.session_id.hex}:{seed}",
    )


def _and(words: Sequence[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


async def ask(
    engine: AsyncEngine,
    meko: Meko | None,
    settings: Settings,
    backend: ChatBackend,
    *,
    household_id: uuid.UUID,
    message: str,
    on: date,
    known_at: datetime | None,
    title: str,
    seed: str,
    call_log: DbCallLog | None = None,
    answerer: Answerer = answer_turn,
    speaker: uuid.UUID | None = None,
) -> Asked:
    """`kako ask`: a new session for the household as of `on`, and one turn in it."""
    session = await start_session(
        engine, meko, household_id=household_id, on=on, title=title, call_log=call_log
    )
    return await run_turn(
        engine,
        meko,
        settings,
        backend,
        session,
        message=message,
        known_at=known_at,
        seed=seed,
        answerer=answerer,
        speaker=speaker,
    )


def render_answer(asked: Asked, settings: Settings | None = None) -> str:
    """The answer as the command prints it: the reply, each option with its allocations and
    cited figures, any number the number check couldn't match (flagged, never hidden), how a
    conflict between the specialists was resolved (and the option rejected), then each
    specialist's proposal and what the turn cost."""
    answer = asked.answer
    replan = asked.replan
    lines = (["The new plan:"] if replan is not None else []) + [answer.reply, ""]
    for option in answer.options:
        mark = " (recommended)" if option.label == answer.recommended else ""
        lines.append(f"{option.label}{mark}: {option.summary}")
        for a in option.allocations:
            lines.append(f"  {a.entity_ref}: {money(a.centavos)} a month ({a.spec})")
        for c in option.citations:
            lines.append(f"  cites {c.ref}" + (f" = {c.shown}" if c.figure is not None else ""))
    if not answer.options:
        lines.append("No options.")
    if replan is not None and asked.state is not None:
        lines += ["", *changes_lines(replan, asked.state.entities), ""]
        lines += ["Why:", *([answer.why] if answer.why else [])]
        lines += why_lines(replan, asked.state.entities)[1:]
    if asked.proposed:
        lines += ["", "Waiting for your yes (kako proposals approve <id>… --by <name>):"]
        lines += [f"  {p.proposal_id} {p.kind}: {p.shown}" for p in asked.proposed]
    for refused in asked.proposal_errors:
        lines.append(f"Not proposed: {refused}")
    checks = [*answer.checks, *(p.check for p in answer.proposals if p.check is not None)]
    flagged = [f"{n.text!r} in {c.label}" for c in checks for n in c.unmatched]
    if flagged:
        lines += ["", "Numbers that match no figure or fact (flagged): " + "; ".join(flagged)]
    if answer.resolution is not None:
        lines += ["", *render_resolution(answer.resolution)]
    lines.append("")
    for p in answer.proposals:
        lines.append(f"{p.specialist} ({p.what_if or 'no change'}): {p.summary}")
    saved = asked.saved
    if saved is not None and saved.plan_id is not None:
        count = sum(len(ids) for ids in saved.recommendations.values())
        lines += [
            "",
            f"Stored: plan v{saved.version} ({saved.plan_id}), proposed, with {count} "
            f"recommendations and {len(saved.reconciliations)} reconciliation rows.",
        ]
    if asked.meko_message_id is not None:
        trace = settings.meko_trace_url(asked.conversation_id or "") if settings else None
        lines.append(
            f"Meko kept the turn in conversation {asked.conversation_id}"
            + (f": {trace}" if trace else ".")
        )
    if asked.meko_error is not None:
        lines.append(f"Meko didn't keep the turn: {asked.meko_error}")
    lines += [
        "",
        f"Turn {asked.seed}, session {asked.session_id}: {asked.model_calls} model calls, "
        f"{asked.input_tokens:,} tokens in, {asked.output_tokens:,} out, "
        f"US${asked.cost_usd:.4f}.",
    ]
    return "\n".join(lines)
