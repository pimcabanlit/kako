"""Sessions layer: a planning session is one Meko conversation, and its turns as shown."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import fk, uuid_pk


class Session(Base):
    __tablename__ = "session"

    id: Mapped[uuid.UUID] = uuid_pk()
    household_id: Mapped[uuid.UUID] = fk("household.id")
    meko_conversation_id: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    household_date: Mapped[date] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionParticipant(Base):
    __tablename__ = "session_participant"

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("session.id"), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.id"), primary_key=True)


class SessionTurn(Base):
    __tablename__ = "session_turn"
    __table_args__ = (UniqueConstraint("session_id", "meko_turn_seed"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = fk("session.id")
    meko_turn_seed: Mapped[str] = mapped_column(Text)
    said_by: Mapped[uuid.UUID | None] = fk("person.id", nullable=True)
    message: Mapped[str] = mapped_column(Text)
    shown: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
