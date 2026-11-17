"""Decisions layer: decisions with their options (chosen and rejected) and assumptions."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.enums import DECISION_TAGS
from kako.db.models._columns import enum_check, fk, uuid_pk

# Constants from code, never input (see enum_check).
_TAG_LIST = ", ".join(f"'{tag}'" for tag in DECISION_TAGS)


class Decision(Base):
    __tablename__ = "decision"
    __table_args__ = (
        enum_check("decision", "status"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="window"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    session_id: Mapped[uuid.UUID] = fk("session.id")
    question: Mapped[str] = mapped_column(Text)
    # Decision and option point at each other: this key is checked at commit (written together).
    chosen_option_id: Mapped[uuid.UUID] = fk("decision_option.id", deferred=True)
    reasoning: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text)
    replaced_by: Mapped[uuid.UUID | None] = fk("decision.id", nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text)
    proposal_id: Mapped[uuid.UUID] = fk("proposal.id")


class DecisionOption(Base):
    __tablename__ = "decision_option"
    __table_args__ = (
        # V-15: every tag is on the fixed list.
        CheckConstraint(f"tags <@ ARRAY[{_TAG_LIST}]::text[]", name="tags"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    decision_id: Mapped[uuid.UUID] = fk("decision.id")
    label: Mapped[str] = mapped_column(Text)
    calc_run_id: Mapped[uuid.UUID | None] = fk("calc_run.id", nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), default=list
    )


class DecisionAssumption(Base):
    __tablename__ = "decision_assumption"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("decision.id"), primary_key=True
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("fact.id"), primary_key=True)
