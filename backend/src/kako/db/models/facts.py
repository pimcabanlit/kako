"""Facts layer: one row per value per period, and the life events that cause changes."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import (
    RATE,
    enum_check,
    fk,
    one_value_check,
    uuid_pk,
    value_range_check,
)


class Fact(Base):
    """A value with its validity window and replacement chain. Never updated except in the
    status transitions in docs/data-model.md, never deleted."""

    __tablename__ = "fact"
    __table_args__ = (
        enum_check("fact", "status"),
        enum_check("fact", "source_kind"),
        one_value_check(),
        value_range_check(),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="window"),
        CheckConstraint("replaces IS NULL OR replaces <> id", name="not_self"),
        CheckConstraint(
            "status <> 'replaced' OR (valid_to IS NOT NULL AND replaced_by IS NOT NULL)",
            name="replaced_closed",
        ),
        CheckConstraint(
            "(status = 'retracted') = (retracted_at IS NOT NULL) AND "
            "(retracted_at IS NULL) = (retraction_reason IS NULL)",
            name="retracted_reason",
        ),
        # Migration 0003. Only a seed fact has no proposal, and a seed fact replaces nothing.
        CheckConstraint(
            "(source_kind = 'seed') = (proposal_id IS NULL) "
            "AND (source_kind <> 'seed' OR replaces IS NULL)",
            name="seed",
        ),
        Index("ix_fact_snapshot", "household_id", "entity_id", "attribute", "valid_from"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    entity_id: Mapped[uuid.UUID | None] = fk("entity.id", nullable=True)
    attribute: Mapped[str] = mapped_column(Text)
    value_money: Mapped[int | None] = mapped_column(BigInteger)
    value_rate: Mapped[Decimal | None] = mapped_column(RATE)
    value_int: Mapped[int | None] = mapped_column(Integer)
    value_date: Mapped[date | None] = mapped_column(Date)
    value_text: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    replaces: Mapped[uuid.UUID | None] = fk("fact.id", nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = fk("fact.id", nullable=True, unique=True)
    status: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_reason: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    # Unique (migration 0003): a proposal writes one fact at most.
    proposal_id: Mapped[uuid.UUID | None] = fk("proposal.id", nullable=True, unique=True)
    life_event_id: Mapped[uuid.UUID | None] = fk("life_event.id", nullable=True)


class LifeEvent(Base):
    __tablename__ = "life_event"
    __table_args__ = (enum_check("life_event", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    kind: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    occurs_on: Mapped[date] = mapped_column(Date)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_ref: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[uuid.UUID] = fk("proposal.id")
