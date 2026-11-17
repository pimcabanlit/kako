"""Dreaming layer: one run per session, and the proposals waiting for a person."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import enum_check, fk, uuid_pk


class DreamRun(Base):
    __tablename__ = "dream_run"
    __table_args__ = (enum_check("dream_run", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = fk("session.id", unique=True)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )


class Proposal(Base):
    __tablename__ = "proposal"
    __table_args__ = (
        enum_check("proposal", "kind"),
        enum_check("proposal", "status"),
        CheckConstraint(
            "(status = 'pending' AND decided_at IS NULL AND decided_by_person_id IS NULL) OR "
            "(status = 'approved' AND decided_at IS NOT NULL "
            "AND decided_by_person_id IS NOT NULL) OR "
            "(status IN ('rejected', 'expired') AND decided_at IS NOT NULL)",
            name="decided",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    dream_run_id: Mapped[uuid.UUID | None] = fk("dream_run.id", nullable=True)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    decided_by_person_id: Mapped[uuid.UUID | None] = fk("person.id", nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProposalEvidence(Base):
    __tablename__ = "proposal_evidence"
    __table_args__ = (enum_check("proposal_evidence", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    proposal_id: Mapped[uuid.UUID] = fk("proposal.id")
    kind: Mapped[str] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(Text)
    person_id: Mapped[uuid.UUID | None] = fk("person.id", nullable=True)
    quote: Mapped[str] = mapped_column(Text)
