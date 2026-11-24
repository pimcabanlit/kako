"""One planning turn from the command line: `kako ask` (and, later, the API).

It starts a session for the household (a Meko conversation, when Meko is in use, and its `session`
row), gathers the brief, runs the orchestrator and its specialists through the model manager, and
returns the checked answer with what the turn cost. Every model call goes to `llm_call` and every
tool call to `agent_step`, so a real run can be read back afterwards (docs/tuning-log.md).

Which model answers is `KAKO_MODEL_MODE`'s choice: live Foundry, recording a live run to
`KAKO_RECORDED_RESPONSES`, or replaying that file with no network.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.answers import TurnAnswer
from kako.agents.brief_store import gather_brief
from kako.agents.checks import record
from kako.agents.model_manager import ModelManager
from kako.agents.orchestrator import answer_turn
from kako.agents.present import money
from kako.agents.reconciling import render_resolution
from kako.agents.recorded import ChatBackend
from kako.agents.tools import TurnState
from kako.db.agent_steps import DbStepLog
from kako.db.calc_store import save_run
from kako.db.llm_log import DbLlmLog
from kako.db.models import LlmCall, Session
from kako.db.number_checks import DbCheckLog
from kako.meko.adapter import Meko
from kako.settings import Settings

SESSION = cast(Table, Session.__table__)
LLM_CALL = cast(Table, LlmCall.__table__)
AGENT = "kako:orchestrator"


@dataclass(frozen=True)
class Asked:
    answer: TurnAnswer
    session_id: uuid.UUID
    seed: str
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal  # real calls only; a replay costs nothing


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
) -> Asked:
    """Answer `message` for the household as of `on` (and as known at `known_at`)."""
    started = datetime.now(UTC)
    if meko is not None:
        conversation = await meko.create_conversation(
            agent_id=AGENT, title=title, session_key=f"kako-ask-{seed}-{uuid.uuid4().hex[:8]}"
        )
    else:
        conversation = f"local-{uuid.uuid4().hex}"  # no Meko: the session still needs an id
    session_id = uuid.uuid4()
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
    async with engine.connect() as conn:
        brief, inputs = await gather_brief(
            conn,
            meko,
            household_id=household_id,
            on=on,
            known_at=known_at,
            message=message,
            conversation_id=conversation if meko is not None else None,
            budget=settings.brief_token_budget,
            search_limit=settings.brief_search_limit,
        )
    async with engine.connect() as conn:
        # The turn's run, stored with its figures: what the number check holds the texts to.
        calc_run_id = await save_run(conn, inputs.run, created_at=datetime.now(UTC))
    checks = DbCheckLog(engine, session_id=session_id, calc_run_id=calc_run_id)
    state = TurnState(
        brief, inputs, seed, meko, conversation if meko is not None else None, checks=checks
    )
    manager = ModelManager(settings, backend, DbLlmLog(engine))
    turn = manager.turn(seed, session_id=session_id, steps=DbStepLog(engine, session_id))
    answer = await answer_turn(manager, turn, state)
    for check in answer.checks:  # each text as shown: passed, or with its numbers flagged
        await checks.write(record(check, check.result))
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
                ).where(LLM_CALL.c.session_id == session_id)
            )
        ).one()
    return Asked(answer, session_id, seed, totals[0], totals[1], totals[2], Decimal(totals[3]))


def render_answer(asked: Asked) -> str:
    """The answer as the command prints it: the reply, each option with its allocations and
    cited figures, any number the number check couldn't match (flagged, never hidden), how a
    conflict between the specialists was resolved (and the option rejected), then each
    specialist's proposal and what the turn cost."""
    answer = asked.answer
    lines = [answer.reply, ""]
    for option in answer.options:
        mark = " (recommended)" if option.label == answer.recommended else ""
        lines.append(f"{option.label}{mark}: {option.summary}")
        for a in option.allocations:
            lines.append(f"  {a.entity_ref}: {money(a.centavos)} a month ({a.spec})")
        for c in option.citations:
            lines.append(f"  cites {c.ref}" + (f" = {c.shown}" if c.figure is not None else ""))
    if not answer.options:
        lines.append("No options.")
    checks = [*answer.checks, *(p.check for p in answer.proposals if p.check is not None)]
    flagged = [f"{n.text!r} in {c.label}" for c in checks for n in c.unmatched]
    if flagged:
        lines += ["", "Numbers that match no figure or fact (flagged): " + "; ".join(flagged)]
    if answer.resolution is not None:
        lines += ["", *render_resolution(answer.resolution)]
    lines.append("")
    for p in answer.proposals:
        lines.append(f"{p.specialist} ({p.what_if or 'no change'}): {p.summary}")
    lines += [
        "",
        f"Turn {asked.seed}, session {asked.session_id}: {asked.model_calls} model calls, "
        f"{asked.input_tokens:,} tokens in, {asked.output_tokens:,} out, "
        f"US${asked.cost_usd:.4f}.",
    ]
    return "\n".join(lines)
