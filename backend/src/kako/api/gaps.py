"""The Context Gaps API: what Kako would like to know, and the answers that fill it.

- `GET /api/v1/gaps` lists the household's gaps (all by default): the search that fell short, its
  band and best score, Meko's reason, the question for the household, the answer's proposal, and
  once replayed, Meko's outcome and the score after.
- `POST /api/v1/gaps/sync` keeps each new weak search in Meko's log as an open gap.
- `POST /api/v1/gaps/{gap_id}/answer` ties a gap to the proposal that answers it: one of the
  household's that writes a fact. Once that proposal is approved and Meko upkeep has written the
  fact's memory, the search is replayed after the approval (`api.proposals`).
- `POST /api/v1/gaps/{gap_id}/dismiss` closes a gap an adult says isn't worth answering.

Self-learning is served by Meko Cloud only: on local Meko, `sync` answers 503 and nothing changes.
Like the approvals API, the routes answer only on loopback and take JSON only.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from kako.api.proposals import _json_only
from kako.api.sessions import Services, _household, _services
from kako.db.meko_log import DbCallLog
from kako.gaps.store import (
    COLLECT_CALLS,
    Gap,
    GapError,
    answer_gap,
    collect_gaps,
    dismiss_gap,
    list_gaps,
)
from kako.health import safe_error
from kako.meko.adapter import SelfLearningUnavailable
from kako.meko.client import MekoError

router = APIRouter(prefix="/api/v1/gaps", tags=["gaps"])


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Household(_In):
    household_id: uuid.UUID | None = None  # unset: the only household


class Answer(_In):
    proposal_id: uuid.UUID
    household_id: uuid.UUID | None = None


class Dismiss(_In):
    person_id: uuid.UUID  # the adult who decides (no sign-in yet)
    household_id: uuid.UUID | None = None


class GapOut(BaseModel):
    id: uuid.UUID
    query: str
    band_before: str
    score_before: Decimal
    reason: str
    question: str | None
    status: str
    proposal_id: uuid.UUID | None
    verify_outcome: str | None
    score_after: Decimal | None


class Synced(BaseModel):
    new: list[uuid.UUID]


def _out(gap: Gap) -> GapOut:
    return GapOut(**gap.__dict__)


@router.get("", response_model=list[GapOut])
async def read_gaps(
    request: Request,
    status: Annotated[
        Literal["open", "asked", "answered", "verified", "dismissed", "all"], Query()
    ] = "all",
    household_id: uuid.UUID | None = None,
) -> list[GapOut]:
    """The household's gaps, the weakest band first, then the lowest score."""
    services: Services = _services(request)
    household, _ = await _household(services.engine, household_id)
    async with services.engine.connect() as conn:
        gaps = await list_gaps(conn, household, status=None if status == "all" else status)
    return [_out(g) for g in gaps]


@router.post("/sync", response_model=Synced)
async def sync_gaps(body: Household, request: Request) -> Synced:
    """Keep each new weak search in Meko's search log (low or mid band) as an open gap."""
    _json_only(request)
    services: Services = _services(request)
    household, _ = await _household(services.engine, body.household_id)
    try:
        async with services.open_meko(DbCallLog(services.engine), COLLECT_CALLS) as meko:
            if meko is None:
                raise HTTPException(
                    503, "Meko is off here (KAKO_MEKO_OFF): its search log can't be read"
                )
            made = await collect_gaps(services.engine, meko, household)
    except SelfLearningUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except GapError as exc:
        raise HTTPException(409, str(exc)) from None
    except MekoError as exc:
        raise HTTPException(502, f"Meko: {safe_error(exc)}") from None
    return Synced(new=made)


@router.post("/{gap_id}/answer", response_model=GapOut)
async def answer(gap_id: uuid.UUID, body: Answer, request: Request) -> GapOut:
    """Tie the gap to the proposal that answers it (one of the household's that writes a fact)."""
    _json_only(request)
    services: Services = _services(request)
    household, _ = await _household(services.engine, body.household_id)
    try:
        async with services.engine.begin() as conn:
            gap = await answer_gap(conn, household, gap_id, body.proposal_id)
    except GapError as exc:
        raise HTTPException(404 if "no such" in str(exc) else 409, str(exc)) from None
    return _out(gap)


@router.post("/{gap_id}/dismiss", response_model=GapOut)
async def dismiss(gap_id: uuid.UUID, body: Dismiss, request: Request) -> GapOut:
    """Close a gap an adult of the household says isn't worth answering."""
    _json_only(request)
    services: Services = _services(request)
    household, _ = await _household(services.engine, body.household_id)
    try:
        async with services.engine.begin() as conn:
            gap = await dismiss_gap(conn, household, gap_id, body.person_id)
    except GapError as exc:
        status = 404 if "no such" in str(exc) else 403 if "adult" in str(exc) else 409
        raise HTTPException(status, str(exc)) from None
    return _out(gap)
