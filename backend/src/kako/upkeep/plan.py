"""What upkeep owes Meko for a household's facts (docs/data-model.md, "What Kako keeps in Meko").

Pure: the facts, the entities and the links in, the steps out, in the order the facts were recorded.
For each fact:

- **in force or replaced:** Kako's own memory says the fact's sentence now (`sentences.py`): added
  when there is none, rewritten when the sentence changed (a replaced fact goes into the past tense;
  a fact back in force after its replacement was retracted comes back to the present);
- **replaced:** a memory Meko extracted in its own words, linked to the fact once a person approved
  it (`dreaming/memories.py`), is deleted: it tells of the old value as current, and Kako's own
  memory keeps it in the past tense;
- **retracted:** every memory linked to it is deleted, so a wrong value can't be found again.

A link whose `text` is null is a memory in Meko's words; one with text is Kako's own.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from kako.facts.model import EntityRow, FactRow
from kako.upkeep.sentences import fact_sentence


@dataclass(frozen=True)
class Link:
    """A `meko_link` from a fact to a memory."""

    fact_id: uuid.UUID
    memory_id: str
    agent_id: str | None
    text: str | None  # None: Meko's own words

    @property
    def own(self) -> bool:
        return self.text is not None


@dataclass(frozen=True)
class Step:
    kind: Literal["add", "rewrite", "delete"]
    fact: FactRow
    text: str | None = None  # add and rewrite: the sentence to write
    link: Link | None = None  # rewrite and delete: the memory


def plan_upkeep(
    facts: Iterable[FactRow],
    links: Sequence[Link],
    household: str,
    entities: Mapping[uuid.UUID, EntityRow],
) -> list[Step]:
    """Every step that brings Meko in line with the facts, oldest fact first."""
    by_fact: dict[uuid.UUID, list[Link]] = {}
    for link in links:
        by_fact.setdefault(link.fact_id, []).append(link)
    steps: list[Step] = []
    for fact in sorted(facts, key=lambda f: (f.recorded_at, str(f.id))):
        mine = sorted(by_fact.get(fact.id, ()), key=lambda link: link.memory_id)
        entity = entities.get(fact.entity_id) if fact.entity_id is not None else None
        sentence = fact_sentence(fact, household, entity)
        if sentence is None:
            steps += [Step("delete", fact, link=link) for link in mine]
            continue
        if fact.status == "replaced":
            steps += [Step("delete", fact, link=link) for link in mine if not link.own]
        own = [link for link in mine if link.own]
        if not own:
            steps.append(Step("add", fact, text=sentence))
        steps += [Step("rewrite", fact, sentence, link) for link in own if link.text != sentence]
    return steps
