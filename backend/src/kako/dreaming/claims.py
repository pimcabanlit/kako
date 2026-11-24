"""What dreaming reads and what its model step hands back (pure).

A **turn** is what one person of the household said in a session: its seed, their words, the
household's date and who said it. A **claim** is one thing the extraction step says the household
stated in a turn: the quote it rests on, a life event if any, and the facts it states, each value
copied as said. A claim may be a **correction**: the household says a value Kako holds was wrong
(with the right value, or none when it shouldn't be there at all).

`parse_claims` reads the model's `submit_claims` arguments and refuses a wrong shape (`ClaimError`,
sent back to the model once). Whether a claim holds up (its quote, its numbers, its entity and
attribute, against what Kako holds) is decided in `classify.py`, never here.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

MAX_CLAIMS: Final = 12  # claims a session
MAX_FACTS: Final = 4  # facts in one claim
MAX_QUOTE: Final = 600
MAX_DESCRIPTION: Final = 300
MAX_VALUE: Final = 200


class ClaimError(ValueError):
    """The extraction step's answer has the wrong shape; the message goes back to the model."""


@dataclass(frozen=True)
class SaidTurn:
    """One turn of the household's, as dreaming reads it."""

    seed: str  # the turn's seed (`s4:t1`): the proposal's source and its evidence ref
    text: str  # the household's words
    said_on: date  # the household's date when it was said
    person_id: uuid.UUID | None = None  # who said it, when known
    speaker: str | None = None  # their name, as the model reads it


@dataclass(frozen=True)
class ClaimedEvent:
    kind: str
    description: str
    occurs_on: str  # as the model wrote it: "2026-12-01"


@dataclass(frozen=True)
class ClaimedFact:
    entity: str  # an entity ref, or "" for a household-wide fact
    attribute: str
    value: str  # as said: "68000", "3.5%", "2026-12-01", "yes"; "" only to retract
    valid_from: str  # "2026-12-01", or "" for the day it was said


@dataclass(frozen=True)
class Claim:
    turn: str  # the seed of the turn it was said in
    quote: str  # the household's exact words
    correction: bool  # the household says a value Kako holds was wrong
    life_event: ClaimedEvent | None
    facts: tuple[ClaimedFact, ...]


def _str(raw: dict[str, Any], name: str, limit: int, where: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str):
        raise ClaimError(f"{where}.{name} must be a string")
    if len(value) > limit:
        raise ClaimError(f"{where}.{name} must be at most {limit} characters")
    return value.strip()


def _event(raw: Any, where: str) -> ClaimedEvent | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ClaimError(f"{where}.life_event is an object or null")
    return ClaimedEvent(
        _str(raw, "kind", 40, f"{where}.life_event"),
        _str(raw, "description", MAX_DESCRIPTION, f"{where}.life_event"),
        _str(raw, "occurs_on", 40, f"{where}.life_event"),
    )


def _fact(raw: Any, where: str) -> ClaimedFact:
    if not isinstance(raw, dict):
        raise ClaimError(f"{where} is an object")
    return ClaimedFact(
        _str(raw, "entity", 80, where),
        _str(raw, "attribute", 60, where),
        _str(raw, "value", MAX_VALUE, where),
        _str(raw, "valid_from", 40, where),
    )


def parse_claims(arguments: dict[str, Any]) -> tuple[Claim, ...]:
    """The claims in `submit_claims`' arguments, or ClaimError for a wrong shape."""
    raw = arguments.get("claims")
    if not isinstance(raw, list):
        raise ClaimError("claims is a list (empty when the household stated nothing new)")
    if len(raw) > MAX_CLAIMS:
        raise ClaimError(f"at most {MAX_CLAIMS} claims")
    claims = []
    for n, item in enumerate(raw, start=1):
        where = f"claims[{n}]"
        if not isinstance(item, dict):
            raise ClaimError(f"{where} is an object")
        correction = item.get("correction")
        if not isinstance(correction, bool):
            raise ClaimError(f"{where}.correction is true or false")
        facts = item.get("facts")
        if not isinstance(facts, list) or len(facts) > MAX_FACTS:
            raise ClaimError(f"{where}.facts is a list of at most {MAX_FACTS}")
        claim = Claim(
            _str(item, "turn", 80, where),
            _str(item, "quote", MAX_QUOTE, where),
            correction,
            _event(item.get("life_event"), where),
            tuple(_fact(f, f"{where}.facts[{i}]") for i, f in enumerate(facts, start=1)),
        )
        if not claim.quote:
            raise ClaimError(f"{where}.quote is the household's exact words")
        if claim.life_event is None and not claim.facts:
            raise ClaimError(f"{where} names a life event, facts, or both")
        claims.append(claim)
    return tuple(claims)
