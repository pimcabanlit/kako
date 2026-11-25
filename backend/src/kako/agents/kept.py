"""A session's turns as Kako kept them, for the agents of a later turn: the types only.

Read from Postgres (`session_turn` as the household saw each turn, `turn_context` for what the
orchestrator noted about it) by `agents.brief_store`, and written into prompts by
`agents.conversation` (the conversation, compacted by code) and `agents.brief` (the session state
and the recaps of earlier sessions). Every text here is people's or a model's words: whoever writes
one into a prompt wraps it as data.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Final

# The agent test set asks each question in a session of its own with this title prefix
# (`evals.questions`). A question is asked on its own: its brief has no earlier sessions, and no
# other session's brief recaps it.
TEST_SET_TITLE: Final = "Agent test set"


@dataclass(frozen=True)
class KeptOption:
    """An option as the household was shown it."""

    label: str
    summary: str
    what_if: str
    allocations: tuple[str, ...]  # each move as a spec: "debt:credit-card said:10000"
    recommended: bool = False


@dataclass(frozen=True)
class KeptChange:
    """A change the turn filed for a person's yes."""

    proposal_id: uuid.UUID | None
    kind: str
    shown: str  # in plain words, as the household was shown it


@dataclass(frozen=True)
class KeptTurn:
    """One kept turn of a session, numbered from 1 within it."""

    number: int
    seed: str
    said_by: str | None  # who wrote the message, by display name
    message: str  # the household's words
    reply: str  # Kako's reply, as shown
    options: tuple[KeptOption, ...] = ()
    changes: tuple[KeptChange, ...] = ()
    replan: bool = False  # code also showed what changed and why
    topic: str | None = None  # what the orchestrator said the conversation was about, then
    asks: str | None = None  # the question the reply asked the household, if any


@dataclass(frozen=True)
class PastSession:
    """An earlier session of the household, for its recap: its turns and what it decided."""

    ref: str  # S1 is the newest
    title: str
    on: date  # the household's date for it
    turns: tuple[KeptTurn, ...]
    decisions: tuple[str, ...] = ()  # each as "question: chose label"
    ended: bool = False
