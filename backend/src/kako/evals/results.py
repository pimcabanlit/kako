"""The saved results the metrics page reads: the agent test set's runs, dreaming's labelled set and
the preference's effect, each written by its command with `--save`.

A missing file is "not measured yet" (None); a file that isn't as its command writes it raises
`ResultsError`, so the page says it can't be read rather than showing a wrong figure.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

DATA: Final = Path(__file__).resolve().parents[4] / "data"
TEST_SET_RESULTS: Final = DATA / "test-set" / "results"
DREAMING_RESULTS: Final = DATA / "dreaming" / "results.json"


class ResultsError(Exception):
    """A saved results file is not as its command writes it."""


@dataclass(frozen=True)
class TestSetRun:
    """One saved run of the agent test set (`kako test-set --save`)."""

    __test__ = False  # not a pytest test class

    architecture: str
    mode: str  # live, record or replay
    run_at: datetime
    deployments: dict[str, str]
    questions: int
    answered: int
    score: Decimal  # the mean of the questions' scores, 0 to 1
    checks_passed: int
    checks_total: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal  # as recorded: a replay keeps its recording's cost
    meko_calls: int
    scores: dict[str, Decimal]  # each question's score, by id


@dataclass(frozen=True)
class DreamingRun:
    """Dreaming's labelled set, saved (`kako dream eval --save`)."""

    mode: str
    at: datetime
    expected: int
    found: int
    score: Decimal  # found of expected, 0 to 1
    wrong: int
    unquoted: int
    passed: bool
    cost_usd: Decimal


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResultsError(f"{path.name} can't be read: {exc}") from None
    if not isinstance(raw, dict):
        raise ResultsError(f"{path.name} isn't a JSON object")
    return raw


def count_of(raw: dict[str, Any], key: str, where: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ResultsError(f"{where}: {key} isn't a count")
    return value


def number_of(raw: dict[str, Any], key: str, where: str) -> Decimal:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ResultsError(f"{where}: {key} isn't a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ResultsError(f"{where}: {key} isn't a number") from None
    if not number.is_finite() or number < 0:
        raise ResultsError(f"{where}: {key} isn't a number")
    return number


def text_of(raw: dict[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ResultsError(f"{where}: {key} is missing")
    return value


def when_of(raw: dict[str, Any], key: str, where: str) -> datetime:
    try:
        when = datetime.fromisoformat(text_of(raw, key, where))
    except ValueError:
        raise ResultsError(f"{where}: {key} isn't a date and time") from None
    if when.tzinfo is None:
        raise ResultsError(f"{where}: {key} has no time zone")
    return when


def test_set_run(raw: dict[str, Any], where: str) -> TestSetRun:
    """A test-set report as `Report.as_json` writes it."""
    deployments = raw.get("deployments")
    if not isinstance(deployments, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in deployments.items()
    ):
        raise ResultsError(f"{where}: deployments isn't a list of names")
    results = raw.get("results")
    if not isinstance(results, list) or not all(isinstance(r, dict) for r in results):
        raise ResultsError(f"{where}: results isn't a list of questions")
    score = number_of(raw, "score", where)
    if score > 1:
        raise ResultsError(f"{where}: score is over 1")
    return TestSetRun(
        architecture=text_of(raw, "architecture", where),
        mode=text_of(raw, "mode", where),
        run_at=when_of(raw, "run_at", where),
        deployments=dict(deployments),
        questions=count_of(raw, "questions", where),
        answered=count_of(raw, "answered", where),
        score=score,
        checks_passed=count_of(raw, "checks_passed", where),
        checks_total=count_of(raw, "checks_total", where),
        model_calls=count_of(raw, "model_calls", where),
        input_tokens=count_of(raw, "input_tokens", where),
        output_tokens=count_of(raw, "output_tokens", where),
        cost_usd=number_of(raw, "cost_usd", where),
        meko_calls=count_of(raw, "meko_calls", where),
        scores={text_of(r, "id", where): number_of(r, "score", where) for r in results},
    )


def read_test_set_run(architecture: str, directory: Path = TEST_SET_RESULTS) -> TestSetRun | None:
    """The saved run for `specialists` or `single`; None when there is none yet."""
    path = directory / f"{architecture}.json"
    raw = load_json(path)
    if raw is None:
        return None
    run = test_set_run(raw, path.name)
    if run.architecture != architecture:
        raise ResultsError(f"{path.name} holds a run of {run.architecture}")
    return run


def read_dreaming_run(path: Path = DREAMING_RESULTS) -> DreamingRun | None:
    """Dreaming's saved labelled-set report; None when there is none yet."""
    raw = load_json(path)
    if raw is None:
        return None
    where = path.name
    passed = raw.get("passed")
    if not isinstance(passed, bool):
        raise ResultsError(f"{where}: passed isn't true or false")
    score = number_of(raw, "score", where)
    if score > 1:
        raise ResultsError(f"{where}: score is over 1")
    return DreamingRun(
        mode=text_of(raw, "mode", where),
        at=when_of(raw, "at", where),
        expected=count_of(raw, "expected", where),
        found=count_of(raw, "found", where),
        score=score,
        wrong=count_of(raw, "wrong", where),
        unquoted=count_of(raw, "unquoted", where),
        passed=passed,
        cost_usd=number_of(raw, "cost_usd", where),
    )
