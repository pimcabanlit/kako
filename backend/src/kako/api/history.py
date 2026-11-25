"""The timeline and decisions API, for the household's story and the decisions it made.

- `GET /api/v1/timeline`: what happened, newest first (the starting figures, life events with the
  facts they changed, new and replaced facts, corrections, decisions, plans and sessions, each on
  the day it took effect, those after the household's date marked ahead), and each thing the
  household has with each attribute's values over time (window, state, where it came from).
- `GET /api/v1/decisions`: every decision, newest first: the question, the chosen option and every
  option not chosen with its reason, the household's words, who decided, the facts it rests on, and,
  for one still in force, what has moved under it since (to revisit).

Read-only, and only the household's rows (`db.history_read`). Every value is a fact's, written out
by code. Kako has no sign-in yet: the app answers only on loopback (see `api.app`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from kako.api.sessions import _household, _services
from kako.db.history_read import read_decisions, read_timeline

router = APIRouter(prefix="/api/v1", tags=["history"])


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ChangeOut(_Out):
    label: str  # replaced, corrected, the plan's amount, new, ended
    title: str
    before: str | None
    after: str | None
    from_day: str | None


class EventOut(_Out):
    kind: str  # start, life_event, correction, decision, change, plan, session
    on: date
    ahead: bool
    title: str
    detail: str | None
    source: str | None
    changes: list[ChangeOut]
    ref: uuid.UUID | None
    revisit: bool
    by: str | None  # who approved it, or for a decision who decided


class ValueOut(_Out):
    id: uuid.UUID
    value: str
    valid_from: date
    valid_to: date | None
    state: str  # current, coming, past, corrected
    source: str
    shared_on: date | None
    reason: str | None


class AttributeOut(_Out):
    attribute: str
    words: str
    values: list[ValueOut]


class ThingOut(_Out):
    id: uuid.UUID | None
    name: str
    kind: str
    opened_on: date | None
    closed_on: date | None
    attributes: list[AttributeOut]


class TimelineOut(_Out):
    as_of: date
    events: list[EventOut]
    things: list[ThingOut]


class OptionOut(_Out):
    label: str
    chosen: bool
    reason: str | None
    leans: list[str]


class RestsOnOut(_Out):
    title: str
    value: str
    valid_from: date
    moved: bool


class DecisionOut(_Out):
    id: uuid.UUID
    question: str
    chosen: str
    reasoning: str
    quote: str | None
    said_by: str | None
    decided_by: str | None
    decided_at: datetime | None
    session_id: uuid.UUID
    session_title: str
    on: date
    status: str
    valid_to: date | None
    replaced_by: uuid.UUID | None
    outcome: str | None
    plan_id: uuid.UUID | None
    options: list[OptionOut]
    rests_on: list[RestsOnOut]
    revisit: list[ChangeOut]


class DecisionsOut(_Out):
    as_of: date
    decisions: list[DecisionOut]


@router.get("/timeline", response_model=TimelineOut)
async def timeline(request: Request, household_id: uuid.UUID | None = None) -> TimelineOut:
    """The household's story, and each thing's values over time."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        found = await read_timeline(conn, household)
    return TimelineOut.model_validate(found)


@router.get("/decisions", response_model=DecisionsOut)
async def decisions(request: Request, household_id: uuid.UUID | None = None) -> DecisionsOut:
    """Every decision, newest first, with its options and what to revisit."""
    services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        found = await read_decisions(conn, household)
    return DecisionsOut.model_validate(found)
