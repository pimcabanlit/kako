"""Patterns in the household's decisions (docs/architecture.md, "How dreaming works", step 4).

Pure: no database, Meko or clock. Each decision's chosen option carries tags from the fixed list
(`kako/decisions/tags.py`, V-15); the two sides of one preference are a pair of tags. Three choices
the same way, across at least two sessions, with none the other way, make a pattern: the preference
it shows, citing each decision. A pattern the household already holds as its preference proposes
nothing. Code counts; no model is asked.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

MIN_CHOICES: Final = 3
MIN_SESSIONS: Final = 2
# Each tag, the preference it shows and the value it shows, and the tag on the other side.
SIDES: Final[dict[str, tuple[str, str, str]]] = {
    "favours_flexibility": ("preference.debt_vs_flexibility", "flexibility", "favours_speed"),
    "favours_speed": ("preference.debt_vs_flexibility", "speed", "favours_flexibility"),
}
# How a pattern reads in plain words, by the value it shows.
MEANING: Final[dict[str, str]] = {
    "flexibility": "kept cash on hand rather than paying debt off faster",
    "speed": "paid debt off faster rather than keeping cash on hand",
}


@dataclass(frozen=True)
class Choice:
    """One decision the household made, as a pattern reads it."""

    decision_id: uuid.UUID
    session_id: uuid.UUID
    session_title: str
    session_on: date
    decided_by: uuid.UUID | None
    reasoning: str  # the household's own words
    tags: frozenset[str]  # the chosen option's


@dataclass(frozen=True)
class Pattern:
    attribute: str
    value: str
    choices: tuple[Choice, ...]  # oldest first

    @property
    def explanation(self) -> str:
        """Why, in plain words, naming each session (no number is worked out)."""
        sessions = list(dict.fromkeys(c.session_title for c in self.choices))
        named = sessions[0]
        if len(sessions) > 1:
            named = ", ".join(sessions[:-1]) + f" and {sessions[-1]}"
        return (
            f"In its decisions in {named}, the household {MEANING[self.value]}, and it "
            "never chose the other way."
        )


def find_patterns(choices: Sequence[Choice], held: Mapping[str, str]) -> list[Pattern]:
    """The patterns in these choices that the household doesn't already hold (`held`: each
    preference attribute's value now)."""
    found: list[Pattern] = []
    ordered = sorted(choices, key=lambda c: (c.session_on, c.session_title, str(c.decision_id)))
    for tag, (attribute, value, other) in SIDES.items():
        this_way = [c for c in ordered if tag in c.tags]
        other_way = [c for c in ordered if other in c.tags]
        if (
            len(this_way) >= MIN_CHOICES
            and len({c.session_id for c in this_way}) >= MIN_SESSIONS
            and not other_way
            and held.get(attribute) != value
        ):
            found.append(Pattern(attribute, value, tuple(this_way)))
    return found
