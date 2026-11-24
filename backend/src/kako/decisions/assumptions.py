"""The facts a decision rests on (`decision_assumption`).

A decision is made on what the household's life looked like then: what comes in (take-home pay,
13th-month pay), what goes out (expenses, minimum payments), what debts cost (their rates), and
what the household wants (its preferences, constraints and targets). When one of those is later
replaced or retracted, the replan lists the decision **to revisit** (F-DIFF-1).

Balances and amounts saved are left out on purpose: they move with every statement, which is the
plan working, not the ground under it changing. So is `plan.allocation`, which is the decision
itself. Only facts true on the decision's date and known when it was made count, and a goal's or
debt's own details (a target date, a minimum payment) are kept, since a plan rests on them.
"""

from __future__ import annotations

import uuid
from typing import Final

from kako.facts.snapshot import Snapshot

# What changes as the plan works, so a decision doesn't rest on it.
PROGRESS: Final = frozenset(
    {"debt.balance", "account.balance", "goal.saved_amount", "plan.allocation"}
)


def assumptions(snapshot: Snapshot) -> tuple[uuid.UUID, ...]:
    """The facts of `snapshot` (the household on the decision's date, as known when it was made)
    that a decision made then rests on, in a stable order."""
    return tuple(
        sorted(
            (f.id for f in snapshot.facts if f.attribute not in PROGRESS),
            key=str,
        )
    )
