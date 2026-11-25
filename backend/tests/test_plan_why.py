"""The plan screen's words (`planning/why.py`): formulas, names, the number check's matches, and
what changed, on the worked example."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from kako.engine import compute
from kako.engine.diff import Diff, diff
from kako.facts.snapshot import take_snapshot
from kako.planning.why import (
    FORMULAS,
    Refs,
    fact_title,
    figure_title,
    matched_words,
    what_changed,
)
from tests.support.data_model import DATA_MODEL
from tests.support.facts import HOUSEHOLD, at
from tests.support.villanueva import DEC_1, SEP_15, Villanueva, build

ENGINE = Path(__file__).resolve().parents[1] / "src" / "kako" / "engine"


def test_every_formula_has_words_and_is_in_the_data_model() -> None:
    documented = set(re.findall(r"^\| `(F-[A-Z]+-\d+)` \|", DATA_MODEL.read_text(), re.M))
    used = {
        found
        for path in ENGINE.glob("*.py")
        for found in re.findall(r'"(F-[A-Z]+-\d+)"', path.read_text())
    }
    assert used, "the engine names its formulas"
    assert set(FORMULAS) == documented - {"F-DIFF-1"}  # the diff is not a figure's formula
    assert used <= set(FORMULAS)
    for formula, words in FORMULAS.items():
        assert words.endswith("."), formula
        assert not re.search(r"\d", words.replace("13th", "")), f"{formula} has a number in it"


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def test_names_read_as_the_household_would(house: Villanueva) -> None:
    card = next(e for e in house.entities if e.name == "Credit card")
    assert figure_title("debt.payoff_months", card) == (
        "Months until the debt is paid off (Credit card)"
    )
    assert figure_title("cashflow.monthly_surplus", None) == (
        "What is left a month after spending and minimum payments"
    )
    salary = next(
        f for f in house.facts
        if f.entity_id == house.ids["mara_salary"] and f.attribute == "income.monthly_net"
    )  # fmt: skip
    entity = next(e for e in house.entities if e.id == salary.entity_id)
    assert fact_title(salary, entity) == "Mara's salary (take-home pay a month)"


def test_the_number_checks_matches_in_words(house: Villanueva) -> None:
    refs = Refs({"debt:credit-card": next(e for e in house.entities if e.name == "Credit card")})
    assert matched_words("figure:cashflow.monthly_surplus", refs) == (
        "What is left a month after spending and minimum payments"
    )
    assert matched_words("figure:debt.payoff_months@debt:credit-card", refs) == (
        "Months until the debt is paid off (Credit card)"
    )
    assert matched_words("figure:savings1-W2:debt.payoff_months@debt:credit-card", refs) == (
        "Months until the debt is paid off (Credit card), in the option's what-if"
    )
    assert matched_words("fact:debt:credit-card/debt.balance", refs) == "Credit card (balance)"
    assert matched_words("fact:household.emergency_months_target", refs) == (
        "The household's emergency fund target, in months of essential spending"
    )
    assert matched_words("allocation:debt1-W1:debt:credit-card", refs) == (
        "The option's amount a month for Credit card"
    )
    assert matched_words("said", refs) == "The household's own words"
    assert matched_words("date:today", refs) == "The household's date"
    assert matched_words(None, refs) is None  # nothing matched: the check flagged it


@pytest.fixture(scope="module")
def v2_to_v3(house: Villanueva) -> Diff:
    """Plan v2 (Sep 15, as Kako knew it then) against plan v3 (Dec 1): the worked example."""
    v2 = compute(
        take_snapshot(HOUSEHOLD, house.facts, SEP_15, at("2026-09-15", 18)), house.entities
    )
    v3 = compute(take_snapshot(HOUSEHOLD, house.facts, DEC_1, at("2026-12-01", 18)), house.entities)
    return diff(v2, v3, house.facts, {uuid.uuid4(): []})


def test_what_changed_leads_with_the_headline_figures(v2_to_v3: Diff, house: Villanueva) -> None:
    changes = what_changed(v2_to_v3, house.entities)
    first = changes.figures[0]
    assert (first.title, first.headline) == ("Take-home pay a month, all incomes", True)
    assert first.before == "₱100,000.00"
    assert first.after == "₱116,000.00"
    headline = [f.headline for f in changes.figures]
    assert headline == sorted(headline, reverse=True)  # the headline figures first, then the rest
    assert all(f.before != f.after for f in changes.figures)  # only figures that moved

    salary = next(f for f in changes.facts if f.title == "Mara's salary (take-home pay a month)")
    assert (salary.label, salary.before, salary.after, salary.from_day) == (
        "replaced",
        "₱52,000.00",
        "₱68,000.00",
        "Dec 1, 2026",
    )
    assert any(f.label == "the plan's amount" for f in changes.facts)  # September's allocations
