"""Household layer: the household, its people and its entities (identity only, no values)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import enum_check, fk, uuid_pk


class Household(Base):
    __tablename__ = "household"
    __table_args__ = (CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[date] = mapped_column(Date)
    meko_datapack_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Person(Base):
    __tablename__ = "person"
    __table_args__ = (enum_check("person", "role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    birth_year: Mapped[int | None] = mapped_column(Integer)


class Entity(Base):
    __tablename__ = "entity"
    __table_args__ = (
        enum_check("entity", "kind"),
        UniqueConstraint("household_id", "kind", "name"),
        CheckConstraint(
            "closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on", name="dates"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    owner_person_id: Mapped[uuid.UUID | None] = fk("person.id", nullable=True)
    opened_on: Mapped[date | None] = mapped_column(Date)
    closed_on: Mapped[date | None] = mapped_column(Date)
