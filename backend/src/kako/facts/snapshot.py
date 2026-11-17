"""The snapshot: the household as it stood on one date, as Kako knew it at one time.

docs/data-model.md, "Reading facts: the snapshot":

- `on=d`: every fact that is not retracted whose validity window contains d.
- `on=d, known_at=t`: the same, as Kako believed it at t. Only facts recorded at or before t and
  not retracted at or before t count, and each window is the one it had at t. A replacement
  recorded after t hadn't closed the old fact yet, so at t the old fact was still open. The window
  at t is worked out from the replacement chain (`replaces`, `recorded_at`, `retracted_at`), so no
  extra history columns are needed.

Pure: the store loads the household's facts with one query and hands them here.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from kako.facts.model import FactRow


@dataclass(frozen=True)
class Snapshot:
    household_id: uuid.UUID
    on: date
    known_at: datetime | None
    facts: tuple[FactRow, ...]  # sorted by id
    hash: str

    def get(self, entity_id: uuid.UUID | None, attribute: str) -> FactRow | None:
        """The one fact for an entity (None: the household) and attribute, if any."""
        matches = [f for f in self.facts if f.entity_id == entity_id and f.attribute == attribute]
        if len(matches) > 1:
            raise ValueError(f"two facts for {attribute} on {self.on}: the windows overlap (V-02)")
        return matches[0] if matches else None


def snapshot_hash(fact_ids: Iterable[uuid.UUID]) -> str:
    """A stable hash of the facts in a snapshot: SHA-256 of the sorted ids."""
    joined = "\n".join(sorted(str(fact_id) for fact_id in fact_ids))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()


def known(fact: FactRow, known_at: datetime | None) -> bool:
    """Whether Kako held `fact` as true (not retracted) at `known_at` (None: now)."""
    if known_at is None:
        return fact.status != "retracted"
    if fact.recorded_at > known_at:
        return False
    return fact.retracted_at is None or fact.retracted_at > known_at


def window_end(fact: FactRow, successors: list[FactRow], known_at: datetime | None) -> date | None:
    """Where `fact`'s window ended, as known at `known_at`.

    A fact can only be replaced while its window is open, so a fact that has ever had a
    successor ended exactly where its live successor starts, or is open. A fact that never had one
    keeps the end it was recorded with.
    """
    if not successors:
        return fact.valid_to
    live = [s for s in successors if known(s, known_at)]
    if len(live) > 1:
        raise ValueError(f"fact {fact.id} has two live replacements (V-04)")
    return live[0].valid_from if live else None


def take_snapshot(
    household_id: uuid.UUID,
    facts: Iterable[FactRow],
    on: date,
    known_at: datetime | None = None,
) -> Snapshot:
    """The facts of one household true on `on`, as known at `known_at` (None: now)."""
    rows = [f for f in facts if f.household_id == household_id]
    successors: dict[uuid.UUID, list[FactRow]] = defaultdict(list)
    for row in rows:
        if row.replaces is not None:
            successors[row.replaces].append(row)
    chosen = []
    for row in rows:
        if not known(row, known_at) or row.valid_from > on:
            continue
        end = window_end(row, successors.get(row.id, []), known_at)
        if end is None or on < end:
            chosen.append(row)
    chosen.sort(key=lambda f: f.id)
    return Snapshot(
        household_id=household_id,
        on=on,
        known_at=known_at,
        facts=tuple(chosen),
        hash=snapshot_hash(f.id for f in chosen),
    )
