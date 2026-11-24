"""A proposal's payload is the write it approves (V-08; REVIEW.md rule 4), written one way."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from kako.facts.attributes import attribute
from kako.facts.proposals import (
    PayloadError,
    check_payload,
    decode_value,
    encode_value,
    fact_payload,
    retract_payload,
)
from kako.facts.values import FactValueError

CARD = uuid.UUID("00000000-0000-4000-8000-000000000002")
OLD = uuid.UUID("00000000-0000-4000-8000-000000000003")


@pytest.mark.parametrize(
    ("key", "value", "written"),
    [
        ("debt.balance", 7_688_000, 7_688_000),
        ("debt.monthly_rate", Decimal("0.035"), "0.035000"),
        ("goal.target_date", date(2027, 6, 1), "2027-06-01"),
        ("preference.debt_strategy", "avalanche", "avalanche"),
        ("household.emergency_months_target", 5, 5),
    ],
)
def test_values_round_trip(key: str, value: Any, written: Any) -> None:
    attr = attribute(key)
    assert encode_value(attr, value) == written
    assert decode_value(attr, written) == value


@pytest.mark.parametrize(
    ("key", "raw"),
    [
        ("debt.monthly_rate", 0.035),  # a float is never a rate
        ("debt.monthly_rate", "three percent"),
        ("debt.balance", "7688000"),
        ("debt.balance", True),
        ("debt.balance", 76_880.5),
        ("goal.target_date", 20270601),
        ("goal.target_date", "June 2027"),
        ("preference.debt_strategy", "fastest"),
    ],
)
def test_values_that_dont_decode(key: str, raw: Any) -> None:
    with pytest.raises(FactValueError):
        decode_value(attribute(key), raw)


def _card_balance(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "entity_id": CARD,
        "attribute_key": "debt.balance",
        "value": 7_688_000,
        "valid_from": date(2026, 12, 1),
        "replaces": OLD,
    }
    fields.update(changes)
    return fact_payload(**fields)


def test_the_same_write_passes_however_the_rate_is_written() -> None:
    check_payload(_card_balance(), _card_balance())
    rate = {"attribute_key": "debt.monthly_rate", "value": Decimal("0.035")}
    approved = {**_card_balance(**rate), "value": "0.0350"}
    check_payload(approved, _card_balance(**rate))


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_card_balance(value=1), "different value"),
        (_card_balance(valid_from=date(2026, 11, 1)), "different valid_from"),
        (_card_balance(replaces=uuid.uuid4()), "different replaces"),
        (_card_balance(replaces=None), "missing replaces"),
        ({**_card_balance(), "note": "x"}, "unexpected note"),
        (retract_payload(OLD, "typo"), "different kind of write"),
        ([], "no write"),
        (None, "no write"),
        ({**_card_balance(), "value": "7688000"}, "doesn't fit"),
    ],
)
def test_a_different_write_is_refused(payload: Any, message: str) -> None:
    with pytest.raises(PayloadError, match=message):
        check_payload(payload, _card_balance())


def test_a_retraction_names_its_fact_and_reason() -> None:
    check_payload(retract_payload(OLD, "typo"), retract_payload(OLD, "typo"))
    with pytest.raises(PayloadError, match="different fact_id"):
        check_payload(retract_payload(CARD, "typo"), retract_payload(OLD, "typo"))


# --- Kinds, keys, and the payloads that write their own tables ----------------------------------


def test_the_kinds_are_the_databases() -> None:
    from kako.db.enums import ENUMS
    from kako.facts.proposals import KINDS, LIFE_EVENT_KINDS

    assert ENUMS[("proposal", "kind")] == KINDS
    assert ENUMS[("life_event", "kind")] == LIFE_EVENT_KINDS


def test_idempotency_keys() -> None:
    from kako.facts.proposals import fact_target, idempotency_key

    target = fact_target(CARD, "debt.balance", date(2026, 11, 15))
    key = idempotency_key("s:abc:s4:t1", "replace_fact", target)
    assert key == f"s:abc:s4:t1|fact|{CARD}/debt.balance/2026-11-15"
    # The kinds that write a fact share a family: one value can't be proposed twice as two kinds.
    assert idempotency_key("s:abc:s4:t1", "new_fact", target) == key
    assert idempotency_key("s:abc:s4:t1", "preference_pattern", target) == key
    assert idempotency_key("s:abc:s4:t1", "life_event", "new_job/2026-12-01") != key
    assert fact_target(None, "preference.note", date(2026, 1, 1)).startswith("household/")
    with pytest.raises(PayloadError, match="kind of proposal"):
        idempotency_key("s", "edit_fact", target)
    with pytest.raises(PayloadError, match="source and its target"):
        idempotency_key(" ", "new_fact", target)
    with pytest.raises(PayloadError, match="at most"):
        idempotency_key("s" * 400, "new_fact", target)


def test_a_life_event_payload() -> None:
    from kako.facts.proposals import life_event_payload, parse_life_event

    event_id = uuid.uuid4()
    payload = life_event_payload(
        event_id=event_id,
        kind="new_job",
        description="Mara starts a new job",
        occurs_on=date(2026, 12, 1),
        source_ref="conv:s4:t1",
    )
    parsed = parse_life_event(payload)
    assert (parsed.id, parsed.kind, parsed.occurs_on) == (event_id, "new_job", date(2026, 12, 1))
    with pytest.raises(PayloadError, match="kind of life event"):
        parse_life_event({**payload, "kind": "lottery"})
    with pytest.raises(PayloadError, match="unexpected value"):
        parse_life_event({**payload, "value": 1})
    with pytest.raises(PayloadError, match="isn't a date"):
        parse_life_event({**payload, "occurs_on": "Dec 1"})


def _decision(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "question": "How hard should we pay down the credit card?",
        "reasoning": "Lia starts school and we want cash on hand.",
        "valid_from": "2026-09-15",
        "chosen": "B: split",
        "options": [
            {
                "id": str(uuid.uuid4()),
                "label": "A: all extra on the card",
                "calc_run_id": None,
                "rejected_reason": "We want cash on hand",
                "tags": ["favours_speed"],
            },
            {
                "id": str(uuid.uuid4()),
                "label": "B: split",
                "calc_run_id": None,
                "rejected_reason": None,
                "tags": ["favours_flexibility"],
            },
        ],
        "assumptions": [str(OLD)],
        "plan_id": None,
        "revises": None,
    }
    payload.update(changes)
    return payload


def test_a_decision_payload_round_trips() -> None:
    from kako.decisions.tags import DECISION_TAGS
    from kako.facts.proposals import decision_payload, parse_decision

    payload = _decision()
    write = parse_decision(payload, DECISION_TAGS)
    assert write.chosen_option.label == "B: split"
    assert write.chosen_option.tags == ("favours_flexibility",)
    assert write.assumptions == (OLD,)
    assert decision_payload(write) == payload


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"chosen": "C: something else"}, "isn't one of the options"),
        ({"options": []}, "1 to 6 options"),
        ({"assumptions": "all"}, "a list of at most"),
        ({"plan_id": "plan v2"}, "isn't an id"),
        ({"question": ""}, "non-empty"),
    ],
)
def test_a_decision_payload_is_refused(changes: dict[str, Any], error: str) -> None:
    from kako.decisions.tags import DECISION_TAGS
    from kako.facts.proposals import parse_decision

    with pytest.raises(PayloadError, match=error):
        parse_decision(_decision(**changes), DECISION_TAGS)


def test_a_decision_needs_reasons_and_known_tags() -> None:
    from kako.decisions.tags import DECISION_TAGS
    from kako.facts.proposals import parse_decision

    payload = _decision()
    payload["options"][0]["rejected_reason"] = None
    with pytest.raises(PayloadError, match="every other option has one"):
        parse_decision(payload, DECISION_TAGS)
    payload = _decision()
    payload["options"][1]["tags"] = ["favours_luck"]
    with pytest.raises(PayloadError, match="isn't on the list"):
        parse_decision(payload, DECISION_TAGS)
    payload = _decision()
    payload["options"][1]["label"] = payload["options"][0]["label"]
    with pytest.raises(PayloadError, match="share a label"):
        parse_decision(payload, DECISION_TAGS)


def test_a_fact_payload_reads_back() -> None:
    from kako.facts.proposals import parse_fact, parse_retract

    new = fact_payload(
        entity_id=CARD, attribute_key="debt.balance", value=7_688_000, valid_from=date(2026, 11, 15)
    )
    assert parse_fact("new_fact", new).value == 7_688_000
    with pytest.raises(PayloadError, match="missing replaces"):
        parse_fact("replace_fact", new)
    replacing = {**new, "replaces": str(OLD)}
    assert parse_fact("replace_fact", replacing).replaces == OLD
    with pytest.raises(PayloadError, match="unexpected replaces"):
        parse_fact("new_fact", replacing)
    with pytest.raises(PayloadError, match="records a preference"):
        parse_fact("preference_pattern", new)
    with pytest.raises(PayloadError, match="catalog"):
        parse_fact("new_fact", {**new, "attribute": "debt.mood"})
    assert parse_retract(retract_payload(OLD, "typo")) == (OLD, "typo")
