"""What the number check (V-10) finds and logs: plain values, shared by the tools, the answers
and the `number_check` log. The check itself is `agents.numbers`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

Subject = Literal["reply", "recommendation", "summary", "reconciliation"]
Result = Literal["pass", "fail", "regenerated"]
Kind = Literal["money", "months", "percent", "date", "month", "number", "code"]


@dataclass(frozen=True)
class Number:
    text: str  # as written
    kind: Kind
    match: str | None  # what it matched: a figure, fact, allocation or "said"; None: unmatched

    def as_json(self) -> dict[str, Any]:
        return {"text": self.text, "kind": self.kind, "match": self.match}


@dataclass(frozen=True)
class TextCheck:
    """One text checked: what it is, the text, and each number in it."""

    subject: Subject
    label: str  # for the model and the screen: "the reply", "option 'B: split'"
    text: str
    numbers: tuple[Number, ...]

    @property
    def unmatched(self) -> tuple[Number, ...]:
        return tuple(n for n in self.numbers if n.match is None)

    @property
    def ok(self) -> bool:
        return not self.unmatched

    @property
    def result(self) -> Result:
        """The result once the text is final: it passed, or it is shown with numbers flagged."""
        return "pass" if self.ok else "fail"


@dataclass(frozen=True)
class CheckRecord:
    """One row of `number_check`."""

    subject: Subject
    subject_id: uuid.UUID | None
    checked_text: str
    numbers: tuple[Number, ...]
    result: Result
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def record(check: TextCheck, result: Result, subject_id: uuid.UUID | None = None) -> CheckRecord:
    return CheckRecord(check.subject, subject_id, check.text, check.numbers, result)


class CheckLog(Protocol):
    async def write(self, record: CheckRecord) -> None: ...


class MemoryCheckLog:
    def __init__(self) -> None:
        self.records: list[CheckRecord] = []

    async def write(self, record: CheckRecord) -> None:
        self.records.append(record)
