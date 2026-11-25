"""System layer: every model call, every Meko call, every number check."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Numeric, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from kako.db.base import Base
from kako.db.models._columns import enum_check, fk, uuid_pk


class LlmCall(Base):
    __tablename__ = "llm_call"
    __table_args__ = (
        enum_check("llm_call", "agent"),
        enum_check("llm_call", "outcome"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cached_tokens >= 0 "
            "AND latency_ms >= 0 AND cost_usd >= 0",
            name="not_negative",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = fk("session.id", nullable=True)
    meko_turn_seed: Mapped[str | None] = mapped_column(Text)
    agent: Mapped[str] = mapped_column(Text)
    deployment: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cached_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    outcome: Mapped[str] = mapped_column(Text)
    recorded_replay: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prompts: Mapped[dict[str, Any]] = mapped_column(  # last: added by migration 0008
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )


class MekoCall(Base):
    __tablename__ = "meko_call"
    __table_args__ = (
        enum_check("meko_call", "target"),
        enum_check("meko_call", "outcome"),
        CheckConstraint(
            "(latency_ms IS NULL OR latency_ms >= 0) AND "
            "(result_count IS NULL OR result_count >= 0)",
            name="not_negative",
        ),
        Index("ix_meko_call_counter", "target", "tool"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = fk("session.id", nullable=True)
    target: Mapped[str] = mapped_column(Text)
    tool: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    result_count: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NumberCheck(Base):
    __tablename__ = "number_check"
    __table_args__ = (enum_check("number_check", "subject"), enum_check("number_check", "result"))

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = fk("session.id", nullable=True)
    calc_run_id: Mapped[uuid.UUID] = fk("calc_run.id")
    subject: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    checked_text: Mapped[str] = mapped_column(Text)
    numbers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
