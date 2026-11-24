"""Running the agent test set: each question a turn in a new session, scored, with what it cost.

`kako test-set` calls `run_test_set`. Each question is asked of the demo household as of its date
and as known at its time, through the same `run_turn` a household's session uses, so the plan, the
steps, the number checks and the Meko turn are all kept, and the answer is scored in code
(`evals.scoring`). `kako test-set` replays a recording with no network unless
`KAKO_MODEL_MODE=record`, which calls Foundry and costs money, so it needs Pim's yes first.

A report (`Report.as_json`) holds the score, each question's checks, and its model calls, tokens,
cost, Meko calls and seconds. Saved under `data/test-set/results/`, it is what the metrics page
shows.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import MEKO_CALLS, Answerer, Asked, ask
from kako.agents.brief_store import BriefStoreError
from kako.agents.chat import ModelError
from kako.agents.orchestrator import OrchestratorError, answer_turn
from kako.agents.recorded import ChatBackend
from kako.agents.single import answer_alone
from kako.db.meko_log import DbCallLog
from kako.db.models import LlmCall, MekoCall
from kako.evals.questions import Question
from kako.evals.scoring import Score, score
from kako.health import safe_error
from kako.meko.client import MekoError
from kako.meko.mcp import open_meko
from kako.settings import Settings

LLM_CALL = cast(Table, LlmCall.__table__)
MEKO_CALL = cast(Table, MekoCall.__table__)
Architecture = Literal["specialists", "single"]
ANSWERERS: Final[dict[str, Answerer]] = {"specialists": answer_turn, "single": answer_alone}
# A turn that can't finish: the model, a recording, Meko, the brief or the orchestrator failed.
TURN_ERRORS: Final = (ModelError, MekoError, BriefStoreError, OrchestratorError)


@dataclass(frozen=True)
class Outcome:
    """One question's run: its score, and what it took."""

    question: Question
    score: Score
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)  # as recorded: a replay keeps the cost of the call it replays
    meko_calls: int = 0
    seconds: float = 0.0
    session_id: uuid.UUID | None = None
    error: str | None = None
    deployments: frozenset[str] = frozenset()  # the deployments its calls name, as logged

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.question.id,
            "on": self.question.on.isoformat(),
            "known_at": self.question.known_at.isoformat(),
            "message": self.question.message,
            "score": round(self.score.value, 4),
            "passed": self.score.passed,
            "total": self.score.total,
            "checks": [
                {"name": c.name, "passed": c.passed, **({"detail": c.detail} if c.detail else {})}
                for c in self.score.checks
            ],
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": str(self.cost_usd),
            "meko_calls": self.meko_calls,
            "seconds": round(self.seconds, 1),
            "error": self.error,
        }


@dataclass(frozen=True)
class Report:
    architecture: Architecture
    mode: str  # live, record or replay
    run_at: datetime
    deployments: dict[str, str]
    outcomes: tuple[Outcome, ...] = field(default_factory=tuple)

    @property
    def score(self) -> float:
        """The mean of the questions' scores."""
        if not self.outcomes:
            return 0.0
        return sum(o.score.value for o in self.outcomes) / len(self.outcomes)

    def as_json(self) -> dict[str, Any]:
        outcomes = self.outcomes
        return {
            "architecture": self.architecture,
            "mode": self.mode,
            "run_at": self.run_at.isoformat(timespec="seconds"),
            "deployments": self.deployments,
            "questions": len(outcomes),
            "score": round(self.score, 4),
            "checks_passed": sum(o.score.passed for o in outcomes),
            "checks_total": sum(o.score.total for o in outcomes),
            "answered": sum(o.error is None for o in outcomes),
            "model_calls": sum(o.model_calls for o in outcomes),
            "input_tokens": sum(o.input_tokens for o in outcomes),
            "output_tokens": sum(o.output_tokens for o in outcomes),
            "cost_usd": str(sum((o.cost_usd for o in outcomes), Decimal(0))),
            "meko_calls": sum(o.meko_calls for o in outcomes),
            "results": [o.as_json() for o in outcomes],
        }


async def run_test_set(
    engine: AsyncEngine,
    settings: Settings,
    backend: ChatBackend,
    questions: Sequence[Question],
    *,
    household_id: uuid.UUID,
    architecture: Architecture,
    progress: Callable[[Outcome], None] | None = None,
) -> Report:
    """Every question in turn (never at the same time: one turn at a time, as in a session)."""
    outcomes = []
    for question in questions:
        outcome = await _one(engine, settings, backend, question, household_id, architecture)
        outcomes.append(outcome)
        if progress is not None:
            progress(outcome)
    if backend.replays:  # the deployments the recording was made on, as its calls were logged
        names = sorted(frozenset().union(*(o.deployments for o in outcomes)))
        deployments = {"recorded": ", ".join(names)} if names else {}
    else:
        deployments = dict(settings.deployments)
    return Report(
        architecture, settings.model_mode, datetime.now(UTC), deployments, tuple(outcomes)
    )


async def _one(
    engine: AsyncEngine,
    settings: Settings,
    backend: ChatBackend,
    question: Question,
    household_id: uuid.UUID,
    architecture: Architecture,
) -> Outcome:
    started = time.monotonic()
    calls = DbCallLog(engine)
    asked: Asked | None = None
    error = None
    try:
        async with AsyncExitStack() as stack:
            meko = await stack.enter_async_context(open_meko(settings, calls, max_calls=MEKO_CALLS))
            asked = await ask(
                engine,
                meko,
                settings,
                backend,
                household_id=household_id,
                message=question.message,
                on=question.on,
                known_at=question.known_at,
                title=f"Agent test set {question.id} ({architecture})",
                seed=question.seed,
                call_log=calls,
                answerer=ANSWERERS[architecture],
            )
    except TURN_ERRORS as exc:
        error = safe_error(exc)
    seconds = time.monotonic() - started
    result = score(question, asked.answer if asked else None, asked.state if asked else None)
    if asked is None:
        return Outcome(question, result, seconds=seconds, error=error)
    async with engine.connect() as conn:
        llm = (
            await conn.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(LLM_CALL.c.input_tokens), 0),
                    func.coalesce(func.sum(LLM_CALL.c.output_tokens), 0),
                    func.coalesce(func.sum(LLM_CALL.c.cost_usd), 0),
                ).where(LLM_CALL.c.session_id == asked.session_id)
            )
        ).one()
        meko_calls = (
            await conn.execute(
                select(func.count()).where(MEKO_CALL.c.session_id == asked.session_id)
            )
        ).scalar_one()
        names = (
            await conn.execute(
                select(LLM_CALL.c.deployment)
                .where(LLM_CALL.c.session_id == asked.session_id)
                .distinct()
            )
        ).scalars()
    return Outcome(
        question,
        result,
        model_calls=llm[0],
        input_tokens=llm[1],
        output_tokens=llm[2],
        cost_usd=Decimal(llm[3]),
        meko_calls=meko_calls,
        seconds=seconds,
        session_id=asked.session_id,
        deployments=frozenset(names),
    )


def render_report(report: Report) -> str:
    """The report as the command prints it: one line a question, the failed checks under it."""
    lines = []
    for o in report.outcomes:
        lines.append(
            f"{o.question.id}  {o.score.value:5.0%}  {o.score.passed}/{o.score.total}  "
            f"{o.model_calls} calls  {o.input_tokens + o.output_tokens:,} tokens  "
            f"US${o.cost_usd:.4f}  {o.seconds:.0f}s"
        )
        if o.error:
            lines.append(f"     failed: {o.error}")
        lines += [
            f"     missed: {c.name}" + (f" ({c.detail})" if c.detail else "")
            for c in o.score.checks
            if not c.passed and o.error is None
        ]
    data = report.as_json()
    lines.append(
        f"\n{report.architecture}: {report.score:.1%} over {data['questions']} questions "
        f"({data['checks_passed']}/{data['checks_total']} checks), {data['model_calls']} model "
        f"calls, {data['input_tokens'] + data['output_tokens']:,} tokens, US${data['cost_usd']}, "
        f"{data['meko_calls']} Meko calls ({report.mode})"
    )
    return "\n".join(lines)
