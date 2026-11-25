"""Sessions layer: a planning session is one Meko conversation, and its turns as shown."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, Uuid
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


class TurnContext(Base):
    """What the agents of one turn were given, and what the orchestrator noted for the next turn.

    Written once with the turn's `session_turn` row: the brief as sent, the conversation's window
    (which earlier turns went word for word, as one line, or were left out), the brief's Meko
    search, and the orchestrator's `topic` and `asks`, which the next turn's session state reads.
    """

    __tablename__ = "turn_context"
    __table_args__ = (UniqueConstraint("session_id", "meko_turn_seed"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = fk("session.id")
    meko_turn_seed: Mapped[str] = mapped_column(Text)
    brief: Mapped[str] = mapped_column(Text)
    brief_tokens: Mapped[int] = mapped_column(Integer)
    history: Mapped[dict[str, Any]] = mapped_column(JSONB)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    asks: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
