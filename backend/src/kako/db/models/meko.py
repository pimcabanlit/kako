"""Self-learning and Meko links: weak searches, and what Meko holds about each Kako row."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import enum_check, fk, uuid_pk


class ContextGap(Base):
    __tablename__ = "context_gap"
    __table_args__ = (
        enum_check("context_gap", "band_before"),
        enum_check("context_gap", "verify_outcome"),
        enum_check("context_gap", "status"),
        CheckConstraint(
            "score_before BETWEEN 0 AND 1 AND (score_after IS NULL OR score_after BETWEEN 0 AND 1)",
            name="scores",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    meko_log_id: Mapped[str] = mapped_column(Text, unique=True)
    query: Mapped[str] = mapped_column(Text)
    band_before: Mapped[str] = mapped_column(Text)
    score_before: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    reason: Mapped[str] = mapped_column(Text)
    question: Mapped[str | None] = mapped_column(Text)
    asked_in_session_id: Mapped[uuid.UUID | None] = fk("session.id", nullable=True)
    proposal_id: Mapped[uuid.UUID | None] = fk("proposal.id", nullable=True)
    verify_outcome: Mapped[str | None] = mapped_column(Text)
    score_after: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(Text)


class MekoLink(Base):
    __tablename__ = "meko_link"
    __table_args__ = (enum_check("meko_link", "kako_table"), enum_check("meko_link", "meko_kind"))

    kako_table: Mapped[str] = mapped_column(Text, primary_key=True)
    kako_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    meko_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    meko_id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
