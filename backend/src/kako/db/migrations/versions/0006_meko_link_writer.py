"""What Kako wrote to Meko for a link: the memory's writer, and the text Kako last gave it.

Meko lets only the agent that wrote a memory rewrite or delete it, and keeps no record Kako can
compare cheaply, so a link keeps both: `agent_id` (who wrote it: `kako:upkeep` for Kako's own
memory of a fact, the turn's agent for one Meko extracted) and `text` (the sentence Kako last
wrote, null for a memory in Meko's own words). Meko upkeep (`kako/upkeep/`) compares a fact's
sentence with `text` to know when to rewrite its memory in the past tense.

The way back is `alembic downgrade 0005`, which drops the two columns. Links lose who wrote them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("meko_link", sa.Column("agent_id", sa.Text(), nullable=True))
    op.add_column("meko_link", sa.Column("text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("meko_link", "text")
    op.drop_column("meko_link", "agent_id")
