"""The worked example's household (docs/data-model.md, "Worked example: a new job") as fact rows in
memory, built from the demo files (`data/demo-household/`) the way the loader writes them: the seed,
then every change through `through`, each a replacement or a new fact. So the engine tests and the
demo data can't drift apart.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from kako.demo.files import DemoHousehold, read_demo
from kako.demo.load import seed_time
from kako.facts.model import EntityRow, FactRow
from tests.support.facts import HOUSEHOLD, fact

SEP_15 = date(2026, 9, 15)  # plan v2
DEC_1 = date(2026, 12, 1)  # plan v3


@dataclass
class Villanueva:
    demo: DemoHousehold
    entities: list[EntityRow] = field(default_factory=list)
    facts: list[FactRow] = field(default_factory=list)
    ids: dict[str, uuid.UUID] = field(default_factory=dict)


def build(through: datetime | None = datetime(2027, 1, 1, tzinfo=UTC)) -> Villanueva:
    demo = read_demo()
    h = Villanueva(demo)
    for e in demo.entities:
        h.ids[e.key] = uuid.uuid4()
        h.entities.append(
            EntityRow(h.ids[e.key], HOUSEHOLD, e.kind, e.name, e.opened_on, e.closed_on)
        )
    for seed in demo.facts:
        entity_id = h.ids[seed.entity] if seed.entity else None
        h.facts.append(
            fact(
                entity_id,
                seed.attribute,
                seed.value,
                seed.valid_from.isoformat(),
                recorded_at=seed_time(demo),
                source_ref=seed.source_ref,
            )
        )
    events: dict[str, uuid.UUID] = {}
    for change in demo.changes:
        if through is None or change.recorded_at > through:
            break
        if change.kind == "life_event":
            events[change.life_event or ""] = uuid.uuid4()
            continue
        entity_id = h.ids[change.entity] if change.entity else None
        current = [
            (i, f) for i, f in enumerate(h.facts)
            if (f.entity_id, f.attribute) == (entity_id, change.attribute)
            and f.status == "active" and f.valid_to is None
        ]  # fmt: skip
        new = fact(
            entity_id,
            change.attribute,
            change.value,
            change.valid_from.isoformat(),
            recorded_at=change.recorded_at.astimezone(UTC),
            source_kind=change.source_kind,
            source_ref=change.source_ref,
            proposal_id=uuid.uuid4(),
            life_event_id=events[change.life_event] if change.life_event else None,
        )
        if current and change.kind != "new_fact":
            index, old = current[0]
            new = replace(new, replaces=old.id)
            h.facts[index] = replace(
                old, valid_to=new.valid_from, replaced_by=new.id, status="replaced"
            )
        h.facts.append(new)
    return h
