"""What each turn's agents were given: `turn_context`; and a session's recap in Meko.

A turn's agents read the session as a conversation (docs/architecture.md, "The conversation"): the
brief, the session's earlier turns (word for word, as one line each once the session is long, or
left out), and one Meko search on what the conversation is about. `turn_context` keeps, once per
turn, the brief exactly as sent, which earlier turns went where, the search, and the
orchestrator's two notes for the next turn (`topic`, what the conversation is about; `asks`, the
question its reply asked), so the next turn's session state can read them and any answer can be
explained later from what the model saw.

`meko_link.kako_table` gains `session`: Meko upkeep keeps a recap of each ended session as one of
Kako's own memories, written by code from its turns, and links it to the session.

The way back is `alembic downgrade 0008`, which drops the table and the `session` links (Meko
keeps the recap memories; `kako meko check` then reports them as unlinked). Turns answered before
this migration have no `turn_context` row: their session state has no topic and no question.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BEFORE = "('fact', 'decision', 'plan', 'life_event', 'proposal', 'context_gap')"
AFTER = "('fact', 'decision', 'plan', 'life_event', 'proposal', 'context_gap', 'session')"


def upgrade() -> None:
    op.create_table(
        "turn_context",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("meko_turn_seed", sa.Text(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("brief_tokens", sa.Integer(), nullable=False),
        sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("asks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_turn_context_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_turn_context")),
        sa.UniqueConstraint(
            "session_id",
            "meko_turn_seed",
            name=op.f("uq_turn_context_session_id_meko_turn_seed"),
        ),
    )
    op.drop_constraint(op.f("ck_meko_link_kako_table"), "meko_link", type_="check")
    op.create_check_constraint(
        op.f("ck_meko_link_kako_table"), "meko_link", f"kako_table IN {AFTER}"
    )


def downgrade() -> None:
    op.execute("DELETE FROM meko_link WHERE kako_table = 'session'")
    op.drop_constraint(op.f("ck_meko_link_kako_table"), "meko_link", type_="check")
    op.create_check_constraint(
        op.f("ck_meko_link_kako_table"), "meko_link", f"kako_table IN {BEFORE}"
    )
    op.drop_table("turn_context")
