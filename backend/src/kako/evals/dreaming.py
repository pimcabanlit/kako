"""Dreaming's labelled set (`data/dreaming/labelled.toml`): read, run and scored.

Each case is a scripted session on the demo household with the proposals a person would expect
(`expect`) and those that are fine either way (`maybe`). Running a case is dreaming without storing
anything: extraction (the one model step) and the checks in code (`dreaming.dream_over`), as of the
case's date and as known at its time. Scoring is in code:

- **found**: each expected proposal dreaming would make (the set's score is found / expected);
- **wrong**: each proposal it would make that is neither expected nor a maybe;
- **unquoted**: each proposal with a number that isn't in its quotes (V-09), which must be none.

The set passes at 90% found with nothing unquoted (docs/build-plan.md, Phase 4, task 3).
"""

from __future__ import annotations

import re
import tomllib
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

from sqlalchemy import Table, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.chat import ModelError
from kako.agents.model_manager import ModelManager
from kako.agents.present import Refs
from kako.agents.recorded import ChatBackend
from kako.agents.turn import MemoryStepLog
from kako.db.llm_log import DbLlmLog
from kako.db.models import LlmCall
from kako.dreaming.claims import SaidTurn
from kako.dreaming.classify import Finding, Known
from kako.dreaming.extract import DreamInputs, said_turns
from kako.dreaming.job import PERSON, dream_over, household_known
from kako.facts.attributes import CATALOG
from kako.facts.evidence import unquoted
from kako.facts.model import FactValue
from kako.facts.proposals import LIFE_EVENT_KINDS, parse_fact, parse_life_event, parse_retract
from kako.facts.snapshot import take_snapshot
from kako.facts.values import parse_stated
from kako.health import safe_error
from kako.settings import Settings

LABELLED: Final = Path(__file__).resolve().parents[4] / "data" / "dreaming" / "labelled.toml"
ID: Final = re.compile(r"^d\d{2}$")
SEED: Final = re.compile(r"^d\d{2}:t\d+$")
FACT_KINDS: Final = ("new_fact", "replace_fact")
PASS_FOUND: Final = Decimal("0.9")


class LabelledError(Exception):
    """The labelled set isn't as the scorer needs it."""


@dataclass(frozen=True)
class Expected:
    """One proposal, as a person would expect it."""

    kind: str
    entity: str = ""  # a ref, or "" for the household
    attribute: str = ""
    value: FactValue | None = None
    valid_from: date | None = None
    event: str = ""
    on: date | None = None

    def shown(self) -> str:
        if self.kind == "life_event":
            return f"life_event {self.event} on {self.on}"
        if self.kind == "retract_fact":
            return f"retract {self.entity or 'household'}/{self.attribute}"
        return f"{self.kind} {self.entity or 'household'}/{self.attribute} = {self.value} from " + (
            f"{self.valid_from}"
        )


@dataclass(frozen=True)
class CaseTurn:
    speaker: str
    seed: str
    message: str


@dataclass(frozen=True)
class Case:
    id: str
    on: date
    known_at: datetime
    why: str
    turns: tuple[CaseTurn, ...]
    expect: tuple[Expected, ...]
    maybe: tuple[Expected, ...] = ()


def _when(raw: Any, where: str) -> datetime:
    if not isinstance(raw, datetime) or raw.tzinfo is None:
        raise LabelledError(f"{where}: known_at is a time with its zone")
    return raw


def _expected(raw: Any, where: str) -> Expected:
    if not isinstance(raw, dict):
        raise LabelledError(f"{where} is a table")
    kind = raw.get("kind")
    if kind == "life_event":
        if set(raw) != {"kind", "event", "on"} or raw["event"] not in LIFE_EVENT_KINDS:
            raise LabelledError(f"{where}: a life event has kind, event (a kind of event) and on")
        if not isinstance(raw["on"], date):
            raise LabelledError(f"{where}: on is a day")
        return Expected(kind, event=raw["event"], on=raw["on"])
    entity, key = raw.get("entity"), raw.get("attribute")
    if not isinstance(entity, str) or not isinstance(key, str) or key not in CATALOG:
        raise LabelledError(f'{where}: entity is a ref or "", attribute one in the catalog')
    if kind == "retract_fact":
        if set(raw) != {"kind", "entity", "attribute"}:
            raise LabelledError(f"{where}: a retraction has kind, entity and attribute")
        return Expected(kind, entity, key)
    if kind not in FACT_KINDS or set(raw) != {"kind", "entity", "attribute", "value", "valid_from"}:
        raise LabelledError(f"{where}: a fact has kind, entity, attribute, value and valid_from")
    if not isinstance(raw["valid_from"], date) or not isinstance(raw["value"], str):
        raise LabelledError(f"{where}: value is a string, valid_from a day")
    try:
        value = parse_stated(key, raw["value"])
    except ValueError as exc:
        raise LabelledError(f"{where}: {exc}") from None
    return Expected(kind, entity, key, value, raw["valid_from"])


def read_labelled(path: Path = LABELLED) -> tuple[Case, ...]:
    """The cases, checked: an error names the case and the field."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LabelledError(f"{path.name}: {exc}") from None
    if raw.get("version") != 1:
        raise LabelledError("version must be 1")
    cases: list[Case] = []
    seeds: set[str] = set()
    for item in raw.get("case") or ():
        cid = item.get("id")
        if not isinstance(cid, str) or not ID.match(cid) or any(c.id == cid for c in cases):
            raise LabelledError(f"case id {cid!r}: d01, d02, … and each once")
        on = item.get("on")
        if not isinstance(on, date) or isinstance(on, datetime):
            raise LabelledError(f"{cid}: on is a day")
        turns = []
        for n, t in enumerate(item.get("turns") or (), start=1):
            if not isinstance(t, dict) or set(t) != {"speaker", "seed", "message"}:
                raise LabelledError(f"{cid}: turn {n} has speaker, seed and message")
            if not SEED.match(str(t["seed"])) or t["seed"] in seeds:
                raise LabelledError(f"{cid}: turn {n}'s seed is d01:t1 and so on, each once")
            seeds.add(t["seed"])
            turns.append(CaseTurn(str(t["speaker"]), t["seed"], str(t["message"])))
        if not turns:
            raise LabelledError(f"{cid}: at least one turn")
        cases.append(
            Case(
                cid,
                on,
                _when(item.get("known_at"), cid),
                str(item.get("why") or ""),
                tuple(turns),
                tuple(
                    _expected(e, f"{cid} expect {n}")
                    for n, e in enumerate(item.get("expect", ()), start=1)
                ),
                tuple(
                    _expected(e, f"{cid} maybe {n}")
                    for n, e in enumerate(item.get("maybe", ()), start=1)
                ),
            )
        )
    if not cases:
        raise LabelledError("no cases")
    return tuple(cases)


# --- Scoring ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Made:
    """A proposal dreaming would make, as the scorer reads it."""

    shown: str
    expected: Expected  # what it is, in the set's terms
    unquoted: tuple[str, ...]


def made(findings: Sequence[Finding], known: Known, refs: Refs) -> list[Made]:
    """Every proposal in `findings`, read back from its payload."""
    by_id = {f.id: f for f in known.facts}
    out = []
    for f in findings:
        if f.turn is None:
            continue
        quotes = [f.quote, *(e.quote for e in f.evidence)]
        for p in f.proposals:
            missing = tuple(unquoted(p.kind, p.payload, quotes, today=f.turn.said_on))
            if p.kind == "life_event":
                event = parse_life_event(p.payload)
                what = Expected(p.kind, event=event.kind, on=event.occurs_on)
            elif p.kind == "retract_fact":
                fact = by_id[parse_retract(p.payload)[0]]
                what = Expected(p.kind, refs.entity(fact.entity_id) or "", fact.attribute)
            else:
                write = parse_fact(p.kind, p.payload)
                what = Expected(
                    p.kind,
                    refs.entity(write.entity_id) or "",
                    write.attribute,
                    write.value,
                    write.valid_from,
                )
            out.append(Made(p.shown, what, missing))
    return out


@dataclass(frozen=True)
class CaseResult:
    case: Case
    found: tuple[Expected, ...]
    missed: tuple[Expected, ...]
    wrong: tuple[Made, ...]
    unquoted: tuple[Made, ...]
    outcomes: tuple[tuple[str, str, str], ...] = ()  # each finding: outcome, shown, reason
    model_calls: int = 0
    error: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "expected": len(self.case.expect),
            "found": [e.shown() for e in self.found],
            "missed": [e.shown() for e in self.missed],
            "wrong": [m.shown for m in self.wrong],
            "unquoted": [f"{m.shown}: {'; '.join(m.unquoted)}" for m in self.unquoted],
            "findings": [{"outcome": o, "shown": s, "reason": r} for o, s, r in self.outcomes],
            "model_calls": self.model_calls,
            "error": self.error,
        }


def score_case(case: Case, proposals: Sequence[Made]) -> CaseResult:
    """`case`'s expectations against what dreaming would propose."""
    found = tuple(e for e in case.expect if any(m.expected == e for m in proposals))
    missed = tuple(e for e in case.expect if e not in found)
    wrong = tuple(m for m in proposals if m.expected not in (*case.expect, *case.maybe))
    return CaseResult(case, found, missed, wrong, tuple(m for m in proposals if m.unquoted))


@dataclass(frozen=True)
class LabelledReport:
    mode: str
    at: datetime
    results: tuple[CaseResult, ...]
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)

    @property
    def expected(self) -> int:
        return sum(len(r.case.expect) for r in self.results)

    @property
    def found(self) -> int:
        return sum(len(r.found) for r in self.results)

    @property
    def score(self) -> Decimal:
        return Decimal(self.found) / self.expected if self.expected else Decimal(1)

    @property
    def unquoted(self) -> int:
        return sum(len(r.unquoted) for r in self.results)

    @property
    def wrong(self) -> int:
        return sum(len(r.wrong) for r in self.results)

    @property
    def passed(self) -> bool:
        return (
            self.score >= PASS_FOUND
            and self.unquoted == 0
            and not any(r.error for r in self.results)
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "at": self.at.isoformat(),
            "expected": self.expected,
            "found": self.found,
            "score": f"{self.score:.3f}",
            "wrong": self.wrong,
            "unquoted": self.unquoted,
            "passed": self.passed,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": str(self.cost_usd),
            "results": [r.as_json() for r in self.results],
        }


def render_labelled(report: LabelledReport) -> str:
    lines = [
        f"Dreaming's labelled set ({report.mode}): {report.found} of {report.expected} expected "
        f"proposals found ({report.score:.0%}), {report.wrong} wrong, {report.unquoted} with a "
        f"number not in its quote. {'PASS' if report.passed else 'FAIL'} (needs 90% found, none "
        "unquoted).",
    ]
    for r in report.results:
        head = f"{r.case.id}: {len(r.found)} of {len(r.case.expect)} found"
        if r.wrong:
            head += f", {len(r.wrong)} wrong"
        if r.error:
            head += f" (failed: {r.error})"
        lines.append(head)
        lines += [f"  missed: {e.shown()}" for e in r.missed]
        lines += [f"  wrong: {m.shown}" for m in r.wrong]
        lines += [f"  unquoted: {m.shown}: {'; '.join(m.unquoted)}" for m in r.unquoted]
    if report.input_tokens or report.output_tokens:
        lines.append(
            f"Model: {report.input_tokens} input and {report.output_tokens} output tokens, "
            f"US${report.cost_usd:.4f}."
        )
    return "\n".join(lines)


# --- Running ------------------------------------------------------------------------------------


@dataclass
class _People:
    by_key: dict[str, tuple[uuid.UUID, str]] = field(default_factory=dict)  # mara -> id, Mara
    all: tuple[tuple[str, str], ...] = ()


async def run_labelled(
    engine: AsyncEngine,
    settings: Settings,
    backend: ChatBackend,
    cases: Sequence[Case],
    *,
    household_id: uuid.UUID,
    household_name: str,
    progress: Callable[[CaseResult], None] | None = None,
) -> LabelledReport:
    """Every case in turn, as of its date and as known at its time; nothing is stored but the
    model calls' log (`llm_call`, no session)."""
    started = datetime.now(UTC)
    async with engine.connect() as conn:
        rows = list(
            await conn.execute(
                select(PERSON.c.id, PERSON.c.display_name, PERSON.c.role)
                .where(PERSON.c.household_id == household_id)
                .order_by(PERSON.c.role, PERSON.c.display_name)
            )
        )
    people = _People(
        {r.display_name.lower(): (r.id, r.display_name) for r in rows},
        tuple((r.display_name, r.role) for r in rows),
    )
    manager = ModelManager(settings, backend, DbLlmLog(engine))
    results = []
    for case in cases:
        result = await _one(engine, manager, case, household_id, household_name, people)
        results.append(result)
        if progress is not None:
            progress(result)
    llm = cast_totals(await _totals(engine, started))
    return LabelledReport(settings.model_mode, started, tuple(results), *llm)


async def _one(
    engine: AsyncEngine,
    manager: ModelManager,
    case: Case,
    household_id: uuid.UUID,
    household_name: str,
    people: _People,
) -> CaseResult:
    turns = []
    for t in case.turns:
        person = people.by_key.get(t.speaker.lower())
        if person is None:
            raise LabelledError(f"{case.id}: no one called {t.speaker!r} in the household")
        turns.append(SaidTurn(t.seed, t.message, case.on, person[0], person[1]))
    async with engine.connect() as conn:
        known, events = await household_known(conn, household_id, case.known_at)
    inputs = DreamInputs(
        household_name,
        people.all,
        case.on,
        tuple(known.entities.values()),
        take_snapshot(household_id, known.facts, case.on, case.known_at).facts,
        events,
        said_turns(turns),
    )
    try:
        extraction, findings = await dream_over(
            manager, MemoryStepLog(), session_id=None, inputs=inputs, known=known
        )
    except ModelError as exc:  # a failed case scores 0 and says why; the set goes on
        return CaseResult(case, (), case.expect, (), (), error=safe_error(exc))
    result = score_case(case, made(findings, known, inputs.refs))
    outcomes = tuple((f.outcome, f.shown, f.reason) for f in findings)
    error = None if extraction.claims is not None else "the extraction step handed in nothing"
    return CaseResult(
        case,
        result.found,
        result.missed if error is None else case.expect,
        result.wrong,
        result.unquoted,
        outcomes,
        extraction.model_calls,
        error,
    )


LLM_CALL = cast(Table, LlmCall.__table__)


async def _totals(engine: AsyncEngine, since: datetime) -> Any:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                select(
                    func.coalesce(func.sum(LLM_CALL.c.input_tokens), 0),
                    func.coalesce(func.sum(LLM_CALL.c.output_tokens), 0),
                    func.coalesce(
                        func.sum(LLM_CALL.c.cost_usd).filter(LLM_CALL.c.recorded_replay.is_(False)),
                        0,
                    ),
                ).where(
                    LLM_CALL.c.agent == "dreaming",
                    LLM_CALL.c.session_id.is_(None),
                    LLM_CALL.c.created_at >= since,
                )
            )
        ).one()


def cast_totals(row: Any) -> tuple[int, int, Decimal]:
    return int(row[0]), int(row[1]), Decimal(row[2])
