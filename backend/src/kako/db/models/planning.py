"""Planning layer: plans, recommendations and their sources, conflicts, what-ifs, agent steps."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import ARRAY
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


class Plan(Base):
    __tablename__ = "plan"
    __table_args__ = (
        enum_check("plan", "status"),
        UniqueConstraint("household_id", "version"),
        CheckConstraint("version >= 1", name="version"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    version: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[uuid.UUID] = fk("session.id")
    calc_run_id: Mapped[uuid.UUID] = fk("calc_run.id")
    status: Mapped[str] = mapped_column(Text)
    replaces: Mapped[uuid.UUID | None] = fk("plan.id", nullable=True)
    replaced_by: Mapped[uuid.UUID | None] = fk("plan.id", nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    meko_artifact_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recommended_option: Mapped[str | None] = mapped_column(Text)


class Recommendation(Base):
    __tablename__ = "recommendation"
    __table_args__ = (
        enum_check("recommendation", "area"),
        enum_check("recommendation", "specialist"),
        CheckConstraint("allocation IS NULL OR allocation >= 0", name="allocation"),
        UniqueConstraint("plan_id", "option", "entity_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = fk("plan.id")
    area: Mapped[str] = mapped_column(Text)
    specialist: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = fk("entity.id", nullable=True)
    allocation: Mapped[int | None] = mapped_column(BigInteger)
    meko_turn_seed: Mapped[str] = mapped_column(Text)
    option: Mapped[str] = mapped_column(Text)


class RecommendationSource(Base):
    __tablename__ = "recommendation_source"
    __table_args__ = (enum_check("recommendation_source", "source_kind"),)

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recommendation.id"), primary_key=True
    )
    source_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    quote: Mapped[str | None] = mapped_column(Text)


class Reconciliation(Base):
    __tablename__ = "reconciliation"
    __table_args__ = (
        enum_check("reconciliation", "kind"),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    plan_id: Mapped[uuid.UUID] = fk("plan.id")
    kind: Mapped[str] = mapped_column(Text)
    specialists: Mapped[list[str]] = mapped_column(ARRAY(Text))
    figure_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    resolution: Mapped[str] = mapped_column(Text)
    rejected: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    name: Mapped[str] = mapped_column(Text)
    base_as_of: Mapped[date] = mapped_column(Date)
    amp_branch_id: Mapped[str | None] = mapped_column(Text)


class ScenarioOverride(Base):
    __tablename__ = "scenario_override"
    __table_args__ = (one_value_check(), value_range_check())

    id: Mapped[uuid.UUID] = uuid_pk()
    scenario_id: Mapped[uuid.UUID] = fk("scenario.id")
    entity_id: Mapped[uuid.UUID | None] = fk("entity.id", nullable=True)
    attribute: Mapped[str] = mapped_column(Text)
    value_money: Mapped[int | None] = mapped_column(BigInteger)
    value_rate: Mapped[Decimal | None] = mapped_column(RATE)
    value_int: Mapped[int | None] = mapped_column(Integer)
    value_date: Mapped[date | None] = mapped_column(Date)
    value_text: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)


class AgentStep(Base):
    __tablename__ = "agent_step"
    __table_args__ = (
        enum_check("agent_step", "agent"),
        enum_check("agent_step", "outcome"),
        UniqueConstraint("session_id", "meko_turn_seed", "seq"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = fk("session.id")
    meko_turn_seed: Mapped[str] = mapped_column(Text)
    agent: Mapped[str] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(Text)
    input_summary: Mapped[str] = mapped_column(Text)
    result_summary: Mapped[str] = mapped_column(Text)
    calc_run_id: Mapped[uuid.UUID | None] = fk("calc_run.id", nullable=True)
    outcome: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
