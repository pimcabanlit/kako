"""Meko upkeep's sentences and plan (Phase 4, task 5), pure: what Kako keeps in Meko for each fact,
and the steps that bring Meko in line when a fact is added, replaced, retracted or restored."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

from kako.facts.attributes import CATALOG
from kako.upkeep.plan import Link, plan_upkeep
from kako.upkeep.sentences import PHRASES, fact_sentence
from tests.support.facts import at, entity, fact

HOUSEHOLD = "Villanueva household"
MARA = entity("income", "Mara's salary")
OLD = fact(MARA.id, "income.monthly_net", 5_200_000, "2026-03-01")
NEW = fact(MARA.id, "income.monthly_net", 6_800_000, "2026-12-01", recorded_at=at("2026-11-20"))
REPLACED = replace(OLD, status="replaced", valid_to=date(2026, 12, 1), replaced_by=NEW.id)
ENTITIES = {MARA.id: MARA}

NOW = (
    "In the Villanueva household, from Mar 1, 2026, Mara's salary (take-home pay a month) "
    "is ₱52,000.00."
)
PAST = (
    "In the Villanueva household, from Mar 1, 2026 until Nov 30, 2026, Mara's salary "
    "(take-home pay a month) was ₱52,000.00."
)


def test_every_attribute_has_its_words() -> None:
    assert set(PHRASES) == set(CATALOG)


def test_a_fact_in_force_reads_in_the_present_tense() -> None:
    assert fact_sentence(OLD, HOUSEHOLD, MARA) == NOW


def test_a_replaced_fact_reads_in_the_past_tense_to_the_day_before_its_replacement() -> None:
    assert fact_sentence(REPLACED, HOUSEHOLD, MARA) == PAST


def test_a_retracted_fact_has_no_sentence() -> None:
    assert fact_sentence(replace(OLD, status="retracted"), HOUSEHOLD, MARA) is None


def test_household_wide_facts_rates_and_dates() -> None:
    pref = fact(None, "preference.debt_vs_flexibility", "flexibility", "2026-10-20")
    assert fact_sentence(pref, HOUSEHOLD, None) == (
        "In the Villanueva household, from Oct 20, 2026, the household's preference between "
        "paying debt off faster (speed) and keeping cash on hand (flexibility) is flexibility."
    )
    card = entity("debt", "Credit card")
    rate = fact(card.id, "debt.monthly_rate", Decimal("0.03"), "2026-03-01")
    assert fact_sentence(rate, HOUSEHOLD, card) == (
        "In the Villanueva household, from Mar 1, 2026, Credit card (interest rate) is 3% a month."
    )
    house = entity("goal", "House fund")
    when = fact(house.id, "goal.target_date", date(2031, 12, 1), "2026-12-01")
    assert fact_sentence(when, HOUSEHOLD, house) == (
        "In the Villanueva household, from Dec 1, 2026, House fund (target date) is Dec 1, 2031."
    )


def _own(f_id: uuid.UUID, text: str, memory: str = "m-own") -> Link:
    return Link(f_id, memory, "kako:upkeep", text)


def test_a_fact_without_a_memory_gets_one_and_then_nothing_is_owed() -> None:
    (step,) = plan_upkeep([OLD], [], HOUSEHOLD, ENTITIES)
    assert (step.kind, step.fact, step.text) == ("add", OLD, NOW)
    assert plan_upkeep([OLD], [_own(OLD.id, NOW)], HOUSEHOLD, ENTITIES) == []


def test_a_replaced_fact_is_rewritten_in_the_past_tense_and_its_replacement_added() -> None:
    new_sentence = fact_sentence(NEW, HOUSEHOLD, MARA)
    steps = plan_upkeep([REPLACED, NEW], [_own(OLD.id, NOW)], HOUSEHOLD, ENTITIES)
    assert [(s.kind, s.fact.id, s.text) for s in steps] == [
        ("rewrite", OLD.id, PAST),
        ("add", NEW.id, new_sentence),
    ]
    assert steps[0].link == _own(OLD.id, NOW)


def test_a_replaced_fact_with_no_memory_yet_is_added_in_the_past_tense() -> None:
    (step,) = plan_upkeep([REPLACED], [], HOUSEHOLD, ENTITIES)
    assert (step.kind, step.text) == ("add", PAST)


def test_meko_words_about_a_replaced_fact_are_deleted_but_kept_while_it_holds() -> None:
    extracted = Link(OLD.id, "m-meko", "kako:orchestrator", None)
    assert plan_upkeep([OLD], [_own(OLD.id, NOW), extracted], HOUSEHOLD, ENTITIES) == []
    steps = plan_upkeep([REPLACED], [_own(OLD.id, NOW), extracted], HOUSEHOLD, ENTITIES)
    assert [(s.kind, s.link) for s in steps] == [
        ("delete", extracted),
        ("rewrite", _own(OLD.id, NOW)),
    ]


def test_every_memory_of_a_retracted_fact_is_deleted_and_none_added() -> None:
    retracted = replace(OLD, status="retracted")
    extracted = Link(OLD.id, "m-meko", "kako:orchestrator", None)
    steps = plan_upkeep([retracted], [_own(OLD.id, NOW, "m-z"), extracted], HOUSEHOLD, ENTITIES)
    assert [(s.kind, s.link.memory_id if s.link else None) for s in steps] == [
        ("delete", "m-meko"),
        ("delete", "m-z"),
    ]
    assert plan_upkeep([retracted], [], HOUSEHOLD, ENTITIES) == []


def test_a_fact_back_in_force_comes_back_to_the_present_tense() -> None:
    """Its replacement was retracted: the old value was true all along."""
    (step,) = plan_upkeep([OLD], [_own(OLD.id, PAST)], HOUSEHOLD, ENTITIES)
    assert (step.kind, step.text) == ("rewrite", NOW)


def test_steps_follow_the_order_the_facts_were_recorded() -> None:
    steps = plan_upkeep([NEW, OLD], [], HOUSEHOLD, ENTITIES)
    assert [s.fact.id for s in steps] == [OLD.id, NEW.id]
