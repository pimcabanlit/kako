"""A session's turns as the household saw them: `session_turn`.

The session screen reopens a past session like a chat app: each turn's message, who wrote it, and
the answer exactly as shown (the session API's turn: the reply and texts as number-checked, the
options, the changes waiting for a yes, a replan's parts, the plan's ids and the cost). Meko keeps
the same turn in its conversation, but a session run with Meko off has none, and reading it back
would spend Meko calls on every page view. A turn is written once, after it is kept; a failed turn
leaves no row.

The way back is `alembic downgrade 0006`, which drops the table. The screen then shows no past
turns; everything else a turn stored (the plan, its sources, the agent steps, the checks) stays.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_turn",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("meko_turn_seed", sa.Text(), nullable=False),
        sa.Column("said_by", sa.Uuid(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("shown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["said_by"], ["person.id"], name=op.f("fk_session_turn_said_by_person")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_session_turn_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_turn")),
        sa.UniqueConstraint(
            "session_id",
            "meko_turn_seed",
            name=op.f("uq_session_turn_session_id_meko_turn_seed"),
        ),
    )


def downgrade() -> None:
    op.drop_table("session_turn")
