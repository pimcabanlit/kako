"""Memories Meko extracted from a session on its own: candidates, never knowledge (pure).

Meko keeps a memory for what the household says, worded its own way, and lists it among its
Learnings (memories waiting to be kept or promoted) until someone keeps it (docs/meko-setup.md,
spike 4). Kako treats each one as a **candidate**: dreaming shows it to the extraction step as a
noted memory (`m1`), and a claim may name the noted memories it says the same as. Then each one
settles to exactly one fate (V-14: every one ends linked to an approved fact or deleted):

- **waiting** on the proposals its claim made now, which show its words to the household: linked to
  what they write once a person approves every one of them, deleted once any is turned down.
- **delete**: anything else. No claim names it; its claim was refused, a conflict or deferred; it
  holds a number its claim's quote doesn't (Meko's words never add a number to the household's);
  or its claim made nothing new to approve (the same as Kako holds, or proposed by the session
  already), so no person would see its words. A memory is marked approved in a brief only once a
  person has approved every proposal that showed it.

A memory Kako wrote itself carries `kako_` metadata and is never a candidate.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final, Literal

from kako.facts.evidence import text_unquoted

MAX_NOTED: Final = 20  # candidates read from one session
MAX_TEXT: Final = 600
Fate = Literal["waiting", "delete"]


@dataclass(frozen=True)
class Noted:
    """One memory Meko extracted from the session, as dreaming reads it."""

    ref: str  # m1, m2: how the brief and the claims name it
    memory_id: str
    text: str
    agent_id: str | None  # who wrote it: only that agent can delete it


@dataclass(frozen=True)
class Settled:
    """What one claim came to, as the candidates it names need it."""

    quote: str
    said_on: date
    proposal_ids: tuple[uuid.UUID, ...]  # made now, each showing the memory's words


@dataclass(frozen=True)
class Candidate:
    """A noted memory's fate."""

    noted: Noted
    fate: Fate
    reason: str
    proposal_ids: tuple[uuid.UUID, ...] = ()


def _kako_written(metadata: Mapping[str, Any]) -> bool:
    return any(str(key).startswith("kako_") for key in metadata)


def noted_memories(memories: Sequence[Any], conversation_id: str) -> tuple[Noted, ...]:
    """The candidates among a conversation's memories: saved in it, not written by Kako, at most
    MAX_NOTED, in the order of their words (so the brief doesn't depend on Meko's ids)."""
    found: dict[str, Noted] = {}
    for m in memories:
        saved_in = m.conversation_id or m.metadata.get("meko_conversation_id")
        if saved_in != conversation_id or _kako_written(m.metadata) or not m.text.strip():
            continue
        found.setdefault(m.id, Noted("", m.id, m.text.strip()[:MAX_TEXT], m.agent_id))
    ordered = sorted(found.values(), key=lambda n: (n.text, n.memory_id))[:MAX_NOTED]
    return tuple(
        Noted(f"m{n}", c.memory_id, c.text, c.agent_id) for n, c in enumerate(ordered, start=1)
    )


def settle(noted: Sequence[Noted], named: Mapping[str, Sequence[Settled]]) -> list[Candidate]:
    """Each noted memory's fate, from the claims that name it (`named`, by ref)."""
    fates = []
    for n in noted:
        claims = list(named.get(n.ref, ()))
        if not claims:
            fates.append(Candidate(n, "delete", "no claim says the same as it"))
            continue
        extra = sorted(
            {x for c in claims for x in text_unquoted(n.text, [c.quote], today=c.said_on)}
        )
        if extra:
            fates.append(
                Candidate(
                    n, "delete", "it holds a number the household didn't say: " + ", ".join(extra)
                )
            )
            continue
        waiting = tuple(dict.fromkeys(i for c in claims for i in c.proposal_ids))
        if waiting:
            fates.append(Candidate(n, "waiting", "waits for the household's yes", waiting))
        else:
            fates.append(
                Candidate(n, "delete", "its claim made nothing new for a person to approve")
            )
    return fates
