"""The prompts each model call ran with: `llm_call.prompts`.

Every agent's system message is built from prompts kept in the repo (`kako/agents/prompts/`). Each
call now logs which versions it used, by prompt name: `{"common": {"source": "repo", "sha256":
...}, "debt": {...}}`, so a recommendation can be traced to the exact prompt texts behind it (the
same versions are named in the turn's Meko trace as `kako_prompts`). Rows from before this
migration, and calls with no agent prompt (`check-models`), have `{}`.

The way back is `alembic downgrade 0007`, which drops the column. Calls lose the versions they ran
with; Meko's traces still name them.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_call",
        sa.Column(
            "prompts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_call", "prompts")
