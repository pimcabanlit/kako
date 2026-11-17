"""Sessions layer: a planning session is one Meko conversation."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Text, Uuid
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
