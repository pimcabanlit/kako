"""Engine layer: calculation runs, the facts each read, and every figure produced."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, Text, UniqueConstraint
from sqlalchemy import Uuid as UuidType
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import enum_check, fk, uuid_pk


class CalcRun(Base):
    __tablename__ = "calc_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    as_of_date: Mapped[date] = mapped_column(Date)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot_hash: Mapped[str] = mapped_column(Text)
    scenario_id: Mapped[uuid.UUID | None] = fk("scenario.id", nullable=True)
    engine_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CalcInput(Base):
    __tablename__ = "calc_input"

    calc_run_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("calc_run.id"), primary_key=True
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(UuidType, ForeignKey("fact.id"), primary_key=True)


class Figure(Base):
    __tablename__ = "figure"
    __table_args__ = (
        enum_check("figure", "unit"),
        enum_check("figure", "flag"),
        UniqueConstraint("calc_run_id", "key", "entity_id", postgresql_nulls_not_distinct=True),
        CheckConstraint(
            "num_nonnulls(value_numeric, value_date) <= 1 AND "
            "(num_nonnulls(value_numeric, value_date) = 1 OR flag IS NOT NULL)",
            name="value_or_flag",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    calc_run_id: Mapped[uuid.UUID] = fk("calc_run.id")
    key: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = fk("entity.id", nullable=True)
    unit: Mapped[str] = mapped_column(Text)
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    value_date: Mapped[date | None] = mapped_column(Date)
    flag: Mapped[str | None] = mapped_column(Text)
    formula: Mapped[str] = mapped_column(Text)
    input_fact_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UuidType))
    input_figure_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UuidType))
