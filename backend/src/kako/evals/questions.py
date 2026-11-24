"""The agent test set's questions (`data/test-set/questions.toml`), read and checked.

Pure: no database, Meko or clock. Each question names when it is asked (`on`, and `known_at` with
its time zone), the household's message, and what a good answer must hold (`Expect`). An error names
the question and the field, so a typo in the set fails before any model is called.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal

from kako.agents.numbers import scan

TEST_SET: Final = Path(__file__).resolve().parents[4] / "data" / "test-set" / "questions.toml"
ID: Final = re.compile(r"^q\d{2}$")
ENTITY_REF: Final = re.compile(r"^(income|expense|debt|account|goal):[a-z0-9-]+$")
SOURCE: Final = re.compile(r"^(said|memory|doc|(fact|decision):\S+)$")
EXPECT_KEYS: Final = frozenset(
    {
        "states",
        "words",
        "options",
        "allocations",
        "not_recommended",
        "recommended",
        "cites",
        "sources",
    }
)


class TestSetError(Exception):
    """The test set file is not as the scorer needs it."""

    __test__ = False  # not a pytest test class


Move = dict[str, str]  # entity ref -> a monthly amount as written: "₱4,000.00"


@dataclass(frozen=True)
class Expect:
    states: tuple[str, ...] = ()  # each a figure, or options for one: "15 months | Feb 16, 2028"
    words: tuple[str, ...] = ()
    options: tuple[int, int] | None = None  # (min, max)
    allocations: tuple[Move, ...] = ()
    not_recommended: Move | None = None
    recommended: Literal["none"] | None = None
    cites: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Question:
    id: str
    on: date
    known_at: datetime
    message: str
    why: str
    expect: Expect = field(default_factory=Expect)

    @property
    def seed(self) -> str:
        """The turn's seed: it keys the recorded responses, so it never changes for a question."""
        return f"ts:{self.id}"


def read_test_set(path: Path = TEST_SET) -> tuple[Question, ...]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise TestSetError(f"{path}: {exc}") from None
    if raw.get("version") != 1:
        raise TestSetError(f"{path}: version must be 1")
    items = raw.get("question")
    if not isinstance(items, list) or not items:
        raise TestSetError(f"{path}: no [[question]] entries")
    questions = tuple(_question(item) for item in items)
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise TestSetError(f"{path}: two questions share an id")
    return questions


def _question(item: Any) -> Question:
    if not isinstance(item, dict):
        raise TestSetError("each [[question]] is a table")
    qid = item.get("id")
    if not isinstance(qid, str) or not ID.match(qid):
        raise TestSetError(f"question id {qid!r} must look like q01")

    def fail(what: str) -> TestSetError:
        return TestSetError(f"{qid}: {what}")

    on, known_at = item.get("on"), item.get("known_at")
    if not isinstance(on, date) or isinstance(on, datetime):
        raise fail("on must be a date, such as 2026-09-15")
    if not isinstance(known_at, datetime) or known_at.tzinfo is None:
        raise fail("known_at must be a time with its zone, such as 2026-09-15T09:00:00+08:00")
    message, why = item.get("message"), item.get("why")
    if not isinstance(message, str) or not message.strip():
        raise fail("message must be a non-empty string")
    if not isinstance(why, str) or not why.strip():
        raise fail("why must say what a good answer does")
    unknown = set(item) - {"id", "on", "known_at", "message", "why", "expect"}
    if unknown:
        raise fail(f"unknown fields {sorted(unknown)}")
    return Question(
        qid, on, known_at, message.strip(), why.strip(), _expect(item.get("expect"), fail)
    )


def _expect(raw: Any, fail: Any) -> Expect:
    if raw is None:
        return Expect()
    if not isinstance(raw, dict):
        raise fail("expect must be a table")
    unknown = set(raw) - EXPECT_KEYS
    if unknown:
        raise fail(f"unknown expectations {sorted(unknown)}")

    def strings(name: str, pattern: re.Pattern[str] | None = None) -> tuple[str, ...]:
        value = raw.get(name, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
            raise fail(f"expect.{name} must be a list of strings")
        for v in value:
            if pattern is not None and not pattern.match(v):
                raise fail(f"expect.{name}: {v!r} isn't one")
        return tuple(value)

    options = raw.get("options")
    bounds: tuple[int, int] | None = None
    if options is not None:
        low, high = (
            (options.get("min"), options.get("max")) if isinstance(options, dict) else (None, None)
        )
        if not (isinstance(low, int) and isinstance(high, int) and 0 <= low <= high <= 4):
            raise fail("expect.options must be { min, max } within 0 to 4")
        bounds = (low, high)
    allocations = raw.get("allocations", [])
    if not isinstance(allocations, list):
        raise fail("expect.allocations must be a list of moves")
    recommended = raw.get("recommended")
    if recommended not in (None, "none"):
        raise fail('expect.recommended can only be "none"')
    not_recommended = raw.get("not_recommended")
    states = strings("states")
    for wanted in states:
        for one in wanted.split("|"):
            if len(scan(one.strip())) != 1:
                raise fail(
                    f"expect.states: {one.strip()!r} must be one figure ('|' between options)"
                )
    return Expect(
        states=states,
        words=strings("words"),
        options=bounds,
        allocations=tuple(_move(m, fail) for m in allocations),
        not_recommended=None if not_recommended is None else _move(not_recommended, fail),
        recommended=recommended,
        cites=strings("cites", re.compile(r"^[a-z_]+\.[a-z_]+(@\S+)?$")),
        sources=strings("sources", SOURCE),
    )


def _move(raw: Any, fail: Any) -> Move:
    if not isinstance(raw, dict) or not raw:
        raise fail("a move is a table of entity = amount")
    for ref, amount in raw.items():
        if not ENTITY_REF.match(ref):
            raise fail(f"{ref!r} isn't an entity ref, such as debt:credit-card")
        if not isinstance(amount, str) or not re.fullmatch(r"₱\d{1,3}(,\d{3})*\.\d{2}", amount):
            raise fail(f"{ref}: {amount!r} must be written as ₱4,000.00")
    return dict(raw)


def centavos(amount: str) -> int:
    """₱4,000.00 as centavos."""
    whole, _, cents = amount.removeprefix("₱").replace(",", "").partition(".")
    return int(whole) * 100 + int(cents)
