"""The conversation test set: sessions where a turn only makes sense with the turns before it.

`data/test-set/conversations.toml` holds each conversation: its date, its time as known, and its
turns, each with who wrote it and what a good answer does. `run_conversations` plays each one as a
new session on the demo household through the same `start_session` and `run_turn` a household's
session uses, and scores every turn in code:

- on what the orchestrator was sent in the turn's first call (true of a scripted model too): the
  brief names who wrote the message, every earlier turn reached it (word for word, in the digest, or
  left out with `read_turns` to fetch it), the last reply's question is carried, and the options on
  the table are listed with their moves;
- on the answer (a recorded or live run): it was answered, its numbers passed the number check, and
  the turn's own expectations (files a change or not, words used or not, how many options).

No model judges a turn. `kako conversations` replays
`data/recorded/conversations-<architecture>.json` with no network; only `KAKO_MODEL_MODE=record`
calls Foundry, which needs Pim's yes first.
"""

from __future__ import annotations

import re
import time
import tomllib
import uuid
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import MEKO_CALLS, Asked, run_turn, start_session
from kako.agents.chat import ChatReply, ChatRequest
from kako.agents.recorded import ChatBackend
from kako.agents.tools import ORCHESTRATOR
from kako.api.proposals import people
from kako.db.meko_log import DbCallLog
from kako.evals.questions import TEST_SET, session_title
from kako.evals.runner import ANSWERERS, TURN_ERRORS, Architecture
from kako.evals.scoring import Check
from kako.health import safe_error
from kako.meko.mcp import open_meko
from kako.settings import Settings

CONVERSATIONS: Final = TEST_SET.with_name("conversations.toml")
ID: Final = re.compile(r"^c\d{2}$")
PERSON: Final = re.compile(r"^[a-z]+$")
TURN_KEYS: Final = frozenset({"by", "message", "proposes", "words", "any", "lacks", "options"})
CONVERSATION_KEYS: Final = frozenset({"id", "title", "on", "known_at", "turn"})


class ConversationSetError(Exception):
    """The conversation file can't be used as it is."""


@dataclass(frozen=True)
class Turn:
    by: str  # a person's key, such as "jun"
    message: str
    proposes: bool | tuple[str, ...] | None = None  # False, or words each change filed holds
    words: tuple[str, ...] = ()
    any: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    options: tuple[int, int] | None = None


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    on: date
    known_at: datetime
    turns: tuple[Turn, ...]

    def seed(self, number: int) -> str:
        return f"{self.id}:t{number}"


def read_conversations(path: Path = CONVERSATIONS) -> tuple[Conversation, ...]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConversationSetError(f"{path}: {exc}") from None
    if raw.get("version") != 1:
        raise ConversationSetError(f"{path}: version must be 1")
    items = raw.get("conversation")
    if not isinstance(items, list) or not items:
        raise ConversationSetError(f"{path}: no [[conversation]] entries")
    conversations = tuple(_conversation(item) for item in items)
    ids = [c.id for c in conversations]
    if len(set(ids)) != len(ids):
        raise ConversationSetError(f"{path}: two conversations share an id")
    return conversations


def _conversation(item: Any) -> Conversation:
    if not isinstance(item, dict):
        raise ConversationSetError("each [[conversation]] is a table")
    cid = item.get("id")
    if not isinstance(cid, str) or not ID.match(cid):
        raise ConversationSetError(f"conversation id {cid!r} must look like c01")

    def fail(what: str) -> ConversationSetError:
        return ConversationSetError(f"{cid}: {what}")

    unknown = set(item) - CONVERSATION_KEYS
    if unknown:
        raise fail(f"unknown fields {sorted(unknown)}")
    title, on, known_at = item.get("title"), item.get("on"), item.get("known_at")
    if not isinstance(title, str) or not title.strip():
        raise fail("title must be a non-empty string")
    if not isinstance(on, date) or isinstance(on, datetime):
        raise fail("on must be a date, such as 2026-09-15")
    if not isinstance(known_at, datetime) or known_at.tzinfo is None:
        raise fail("known_at must be a time with its zone, such as 2026-09-15T09:00:00+08:00")
    turns = item.get("turn")
    if not isinstance(turns, list) or not turns:
        raise fail("no [[conversation.turn]] entries")
    return Conversation(
        cid,
        title.strip(),
        on,
        known_at,
        tuple(_turn(t, n, fail) for n, t in enumerate(turns, start=1)),
    )


def _turn(raw: Any, number: int, fail: Callable[[str], ConversationSetError]) -> Turn:
    def bad(what: str) -> ConversationSetError:
        return fail(f"turn {number}: {what}")

    if not isinstance(raw, dict):
        raise bad("each turn is a table")
    unknown = set(raw) - TURN_KEYS
    if unknown:
        raise bad(f"unknown fields {sorted(unknown)}")
    by, message = raw.get("by"), raw.get("message")
    if not isinstance(by, str) or not PERSON.match(by):
        raise bad("by must be a person's key, such as jun")
    if not isinstance(message, str) or not message.strip():
        raise bad("message must be a non-empty string")

    def strings(name: str) -> tuple[str, ...]:
        value = raw.get(name, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise bad(f"{name} must be a list of words")
        return tuple(v.strip() for v in value)

    proposes = raw.get("proposes")
    wanted: bool | tuple[str, ...] | None
    if proposes is None or proposes is False:
        wanted = proposes
    elif isinstance(proposes, list) and proposes:
        wanted = strings("proposes")
    else:
        raise bad("proposes is false, or the words each change filed must hold")
    options = raw.get("options")
    bounds: tuple[int, int] | None = None
    if options is not None:
        if not (
            isinstance(options, list)
            and len(options) == 2
            and all(isinstance(n, int) for n in options)
            and 0 <= options[0] <= options[1] <= 4
        ):
            raise bad("options must be [min, max] within 0 to 4")
        bounds = (options[0], options[1])
    return Turn(
        by,
        message.strip(),
        wanted,
        strings("words"),
        strings("any"),
        strings("lacks"),
        bounds,
    )


class Watching:
    """A backend that passes every call on and keeps each request by its call key, so the checks
    can read what the orchestrator was sent."""

    def __init__(self, inner: ChatBackend) -> None:
        self.inner = inner
        self.requests: dict[str, ChatRequest] = {}

    @property
    def replays(self) -> bool:
        return self.inner.replays

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        self.requests.setdefault(key, request)
        return await self.inner.chat(request, deployment=deployment, key=key)


def _has(text: str, word: str) -> bool:
    """`word` in `text` as a whole word (or phrase), in any case."""
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", text, re.IGNORECASE) is not None


def given_checks(
    number: int, asked: Asked, request: ChatRequest | None, earlier: Sequence[Asked]
) -> list[Check]:
    """What the orchestrator was sent in the turn's first call, against the session so far."""
    if request is None or asked.state is None:
        return [Check("sent", False, "no request from the orchestrator")]
    sent = request.messages
    brief = sent[-1].content or ""
    checks = [
        Check(
            "writer",
            "wrote this turn's message." in brief and _has(brief, asked_name(asked)),
            "the brief doesn't say who wrote it",
        )
    ]
    history = asked.state.history
    reached = (
        set(history.verbatim) | set(history.digest) | set(history.left_out) if history else set()
    )
    wanted = set(range(1, number))
    missing = sorted(wanted - reached)
    reads = any(t.name == "read_turns" for t in request.tools)
    same = history is not None and tuple(sent[1:-1]) == history.messages
    checks.append(
        Check(
            "conversation",
            not missing and same and (not history or not history.left_out or reads),
            (f"turns {missing} missing" if missing else "")
            or ("" if same else "the history sent isn't the one kept")
            or "turns left out with no read_turns",
        )
    )
    if earlier:
        last = earlier[-1].answer.asks
        if last:
            checks.append(
                Check(
                    "asked",
                    f"Kako's last reply (turn {number - 1}) asked: " in brief,
                    "the brief doesn't carry the question",
                )
            )
        offered = next((a for a in reversed(earlier) if a.answer.options), None)
        if offered is not None:
            labels = [o.label for o in offered.answer.options]
            checks.append(
                Check(
                    "options",
                    "Options Kako offered at turn" in brief and all(lab in brief for lab in labels),
                    "the brief doesn't list the options on the table",
                )
            )
    return checks


def asked_name(asked: Asked) -> str:
    writer = asked.state.inputs.writer if asked.state is not None else None
    return writer[0] if writer else "\0"


def reply_checks(turn: Turn, asked: Asked | None) -> list[Check]:
    """The turn's answer against what a good one does."""
    if asked is None:
        return [Check("answered", False, "the turn failed")]
    answer = asked.answer
    checks = [Check("answered", True)]
    flagged = [n.text for c in answer.checks for n in c.unmatched]
    checks.append(Check("numbers", not flagged, ", ".join(flagged)))
    shown = " ".join([answer.reply, *(f"{o.label} {o.summary}" for o in answer.options)])
    if turn.proposes is False:
        checks.append(
            Check(
                "files nothing",
                not asked.proposed,
                "; ".join(p.shown for p in asked.proposed),
            )
        )
    elif isinstance(turn.proposes, tuple):
        filed = " ".join(p.shown for p in asked.proposed)
        checks.append(
            Check(
                "files " + ", ".join(turn.proposes),
                bool(asked.proposed) and all(_has(filed, w) for w in turn.proposes),
                filed or "nothing filed",
            )
        )
    for word in turn.words:
        checks.append(Check(f"says {word!r}", _has(shown, word)))
    if turn.any:
        named = ", ".join(map(repr, turn.any))
        checks.append(Check(f"says one of {named}", any(_has(shown, w) for w in turn.any)))
    for word in turn.lacks:
        checks.append(Check(f"doesn't say {word!r}", not _has(shown, word)))
    if turn.options is not None:
        low, high = turn.options
        n = len(answer.options)
        checks.append(Check(f"{low} to {high} options", low <= n <= high, f"{n} offered"))
    return checks


@dataclass(frozen=True)
class TurnOutcome:
    number: int
    turn: Turn
    given: tuple[Check, ...]
    reply: tuple[Check, ...]
    error: str | None = None
    asks: str | None = None
    text: str = ""

    @property
    def checks(self) -> tuple[Check, ...]:
        return self.given + self.reply

    @property
    def score(self) -> float:
        if self.error is not None:
            return 0.0
        checks = self.checks
        return sum(c.passed for c in checks) / len(checks) if checks else 0.0


@dataclass(frozen=True)
class ConversationOutcome:
    conversation: Conversation
    turns: tuple[TurnOutcome, ...]
    session_id: uuid.UUID | None = None
    seconds: float = 0.0

    @property
    def score(self) -> float:
        """The mean of its turns' scores; a turn that didn't run scores 0."""
        n = len(self.conversation.turns)
        return sum(t.score for t in self.turns) / n if n else 0.0


@dataclass(frozen=True)
class ConversationReport:
    architecture: Architecture
    mode: str
    run_at: datetime
    outcomes: tuple[ConversationOutcome, ...] = field(default_factory=tuple)

    @property
    def score(self) -> float:
        if not self.outcomes:
            return 0.0
        return sum(o.score for o in self.outcomes) / len(self.outcomes)

    @property
    def _turns(self) -> list[TurnOutcome]:
        return [t for o in self.outcomes for t in o.turns]

    def as_json(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "mode": self.mode,
            "run_at": self.run_at.isoformat(timespec="seconds"),
            "conversations": len(self.outcomes),
            "score": round(self.score, 4),
            "checks_passed": sum(c.passed for t in self._turns for c in t.checks),
            "checks_total": sum(len(t.checks) for t in self._turns),
            "results": [
                {
                    "id": o.conversation.id,
                    "title": o.conversation.title,
                    "score": round(o.score, 4),
                    "turns": [
                        {
                            "turn": t.number,
                            "by": t.turn.by,
                            "message": t.turn.message,
                            "score": round(t.score, 4),
                            "error": t.error,
                            "checks": [
                                {
                                    "name": c.name,
                                    "passed": c.passed,
                                    **({"detail": c.detail} if c.detail and not c.passed else {}),
                                }
                                for c in t.checks
                            ],
                        }
                        for t in o.turns
                    ],
                }
                for o in self.outcomes
            ],
        }


async def run_conversation(
    engine: AsyncEngine,
    settings: Settings,
    backend: ChatBackend,
    conversation: Conversation,
    *,
    household_id: uuid.UUID,
    architecture: Architecture = "specialists",
    use_meko: bool = True,
    replies: bool = True,
) -> ConversationOutcome:
    """One conversation, a new session: each turn run and scored. `replies=False` scores only what
    the orchestrator was sent (a scripted model's replies say nothing about Kako)."""
    began = time.monotonic()
    watching = Watching(backend)
    calls = DbCallLog(engine)
    async with engine.connect() as conn:
        by_name = await people(conn, household_id)
    outcomes: list[TurnOutcome] = []
    earlier: list[Asked] = []
    session_id = None
    async with AsyncExitStack() as stack:
        meko = (
            await stack.enter_async_context(
                open_meko(settings, calls, max_calls=1 + MEKO_CALLS * len(conversation.turns))
            )
            if use_meko
            else None
        )
        started = await start_session(
            engine,
            meko,
            household_id=household_id,
            on=conversation.on,
            title=session_title(conversation.id, architecture),
            call_log=calls,
        )
        session_id = started.session_id
        for number, turn in enumerate(conversation.turns, start=1):
            speaker = by_name.get(turn.by)
            if speaker is None:
                raise ConversationSetError(f"{conversation.id}: no one called {turn.by!r}")
            seed = conversation.seed(number)
            try:
                asked = await run_turn(
                    engine,
                    meko,
                    settings,
                    watching,
                    started,
                    message=turn.message,
                    known_at=conversation.known_at,
                    seed=seed,
                    answerer=ANSWERERS[architecture],
                    speaker=speaker,
                )
            except TURN_ERRORS as exc:
                outcomes.append(
                    TurnOutcome(number, turn, (), tuple(reply_checks(turn, None)), safe_error(exc))
                )
                break  # the turns after it would read a session that isn't the one scripted
            request = watching.requests.get(f"{seed}/{ORCHESTRATOR}/1")
            given = given_checks(number, asked, request, earlier)
            reply = reply_checks(turn, asked) if replies else []
            outcomes.append(
                TurnOutcome(
                    number,
                    turn,
                    tuple(given),
                    tuple(reply),
                    asks=asked.answer.asks,
                    text=asked.answer.reply,
                )
            )
            earlier.append(asked)
    return ConversationOutcome(conversation, tuple(outcomes), session_id, time.monotonic() - began)


async def run_conversations(
    engine: AsyncEngine,
    settings: Settings,
    backend: ChatBackend,
    conversations: Sequence[Conversation],
    *,
    household_id: uuid.UUID,
    architecture: Architecture = "specialists",
    use_meko: bool = True,
    progress: Callable[[ConversationOutcome], None] | None = None,
) -> ConversationReport:
    outcomes = []
    for conversation in conversations:
        outcome = await run_conversation(
            engine,
            settings,
            backend,
            conversation,
            household_id=household_id,
            architecture=architecture,
            use_meko=use_meko,
        )
        outcomes.append(outcome)
        if progress is not None:
            progress(outcome)
    return ConversationReport(architecture, settings.model_mode, datetime.now(UTC), tuple(outcomes))


def render_conversations(report: ConversationReport) -> str:
    """The report as the command prints it: a line a turn, the missed checks under it."""
    lines = []
    for o in report.outcomes:
        lines.append(f"{o.conversation.id}  {o.score:5.0%}  {o.conversation.title}")
        for t in o.turns:
            passed = sum(c.passed for c in t.checks)
            lines.append(
                f"  turn {t.number} ({t.turn.by})  {t.score:5.0%}  {passed}/{len(t.checks)}"
            )
            if t.error:
                lines.append(f"     failed: {t.error}")
            lines += [
                f"     missed: {c.name}" + (f" ({c.detail})" if c.detail else "")
                for c in t.checks
                if not c.passed and t.error is None
            ]
    data = report.as_json()
    lines.append(
        f"\n{report.architecture}: {report.score:.1%} over {data['conversations']} conversations "
        f"({data['checks_passed']}/{data['checks_total']} checks, {report.mode})"
    )
    return "\n".join(lines)
