"""The learned preference's effect: the test set's preference questions answered with and without
what dreaming learned (the grand prize's "agents that learn", measured).

The questions are the ones that expect the preference cited
(`fact:preference.debt_vs_flexibility`). "With" is the specialists' saved run
(`data/test-set/results/specialists.json`), on the demo household after demo mode: dreaming learned
the preference from Sessions 1 to 3, Mara approved it and it was shared in Meko (with Session 1's
decision record). "Without" is the same questions on a household where that never happened
(`kako demo run --without-learning`), recorded once on Foundry (`kako test-set
--without-preference`). Without the preference the check that cites it can't pass, so each side is
also scored leaving that check out: what the answer does, not what it cites.

Saved to `data/test-set/results/preference.json`, which the metrics page reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Final

from kako.evals.questions import Question
from kako.evals.results import (
    TEST_SET_RESULTS,
    ResultsError,
    count_of,
    load_json,
    number_of,
    text_of,
    when_of,
)

PREFERENCE: Final = "fact:preference.debt_vs_flexibility"
CITES_PREFERENCE: Final = f"cites {PREFERENCE}"  # the scorer's name for that check
PREFERENCE_RESULTS: Final = TEST_SET_RESULTS / "preference.json"


def preference_questions(questions: Sequence[Question]) -> tuple[Question, ...]:
    """The questions whose good answer cites the preference."""
    return tuple(q for q in questions if PREFERENCE in q.expect.sources)


def _ratio(passed: int, total: int) -> Decimal:
    return (Decimal(passed) / total if total else Decimal(0)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def side_json(results: Sequence[dict[str, Any]], ids: Sequence[str], where: str) -> dict[str, Any]:
    """One side's scores over `ids`, from the questions' saved results (`Outcome.as_json`): each
    question with and without the check that cites the preference, and the mean of each."""
    by_id = {r.get("id"): r for r in results}
    questions: list[dict[str, Any]] = []
    scores: dict[str, list[Decimal]] = {"score": [], "score_without_citation": []}
    for qid in ids:
        result = by_id.get(qid)
        if result is None:
            raise ResultsError(f"{where} has no result for {qid}")
        checks = result.get("checks")
        if not isinstance(checks, list) or not all(
            isinstance(c, dict)
            and isinstance(c.get("name"), str)
            and isinstance(c.get("passed"), bool)
            for c in checks
        ):
            raise ResultsError(f"{where}: {qid}'s checks aren't as the scorer writes them")
        rest = [c for c in checks if c["name"] != CITES_PREFERENCE]
        cited = next((c["passed"] for c in checks if c["name"] == CITES_PREFERENCE), None)
        score = _ratio(sum(c["passed"] for c in checks), len(checks))
        behaviour = _ratio(sum(c["passed"] for c in rest), len(rest))
        scores["score"].append(score)
        scores["score_without_citation"].append(behaviour)
        questions.append(
            {
                "id": qid,
                "score": str(score),
                "score_without_citation": str(behaviour),
                "cites_preference": cited,
                "checks": [{"name": c["name"], "passed": c["passed"]} for c in checks],
            }
        )

    def mean(key: str) -> str:
        values = scores[key]
        mean = sum(values, Decimal(0)) / len(values) if values else Decimal(0)
        return str(mean.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))

    return {
        "score": mean("score"),
        "score_without_citation": mean("score_without_citation"),
        "questions": questions,
    }


def effect_json(
    with_run: dict[str, Any], without_run: dict[str, Any], ids: Sequence[str]
) -> dict[str, Any]:
    """Both sides over the same questions, each with when and how it ran and what it cost."""

    def side(run: dict[str, Any], where: str) -> dict[str, Any]:
        results = run.get("results")
        if not isinstance(results, list):
            raise ResultsError(f"{where}: results isn't a list of questions")
        chosen = [r for r in results if isinstance(r, dict) and r.get("id") in ids]
        return {
            "run_at": when_of(run, "run_at", where).isoformat(timespec="seconds"),
            "mode": text_of(run, "mode", where),
            "model_calls": sum(count_of(r, "model_calls", where) for r in chosen),
            "cost_usd": str(sum((number_of(r, "cost_usd", where) for r in chosen), Decimal(0))),
            **side_json(results, ids, where),
        }

    return {
        "preference": PREFERENCE,
        "architecture": "specialists",
        "question_ids": list(ids),
        "with": side(with_run, "specialists.json"),
        "without": side(without_run, "the run without the preference"),
    }


@dataclass(frozen=True)
class EffectQuestion:
    id: str
    score_with: Decimal
    score_without: Decimal
    behaviour_with: Decimal  # leaving out the check that cites the preference
    behaviour_without: Decimal
    cited_with: bool | None
    cited_without: bool | None


@dataclass(frozen=True)
class EffectSide:
    run_at: datetime
    mode: str
    model_calls: int
    cost_usd: Decimal
    score: Decimal
    behaviour: Decimal


@dataclass(frozen=True)
class PreferenceEffect:
    preference: str
    with_side: EffectSide
    without_side: EffectSide
    questions: tuple[EffectQuestion, ...]


def _side(raw: Any, where: str) -> tuple[EffectSide, dict[str, dict[str, Any]]]:
    if not isinstance(raw, dict):
        raise ResultsError(f"{where} is missing")
    questions = raw.get("questions")
    if not isinstance(questions, list) or not all(isinstance(q, dict) for q in questions):
        raise ResultsError(f"{where}: questions isn't a list")
    side = EffectSide(
        run_at=when_of(raw, "run_at", where),
        mode=text_of(raw, "mode", where),
        model_calls=count_of(raw, "model_calls", where),
        cost_usd=number_of(raw, "cost_usd", where),
        score=number_of(raw, "score", where),
        behaviour=number_of(raw, "score_without_citation", where),
    )
    return side, {text_of(q, "id", where): q for q in questions}


def _cited(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def read_preference_effect(path: Path = PREFERENCE_RESULTS) -> PreferenceEffect | None:
    """The saved comparison; None when it hasn't been measured yet."""
    raw = load_json(path)
    if raw is None:
        return None
    where = path.name
    with_side, with_qs = _side(raw.get("with"), f"{where} (with)")
    without_side, without_qs = _side(raw.get("without"), f"{where} (without)")
    ids = raw.get("question_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise ResultsError(f"{where}: question_ids isn't a list of ids")
    if set(ids) != set(with_qs) or set(ids) != set(without_qs):
        raise ResultsError(f"{where}: the two sides aren't over the same questions")
    return PreferenceEffect(
        preference=text_of(raw, "preference", where),
        with_side=with_side,
        without_side=without_side,
        questions=tuple(
            EffectQuestion(
                id=qid,
                score_with=number_of(with_qs[qid], "score", where),
                score_without=number_of(without_qs[qid], "score", where),
                behaviour_with=number_of(with_qs[qid], "score_without_citation", where),
                behaviour_without=number_of(without_qs[qid], "score_without_citation", where),
                cited_with=_cited(with_qs[qid].get("cites_preference")),
                cited_without=_cited(without_qs[qid].get("cites_preference")),
            )
            for qid in ids
        ),
    )
