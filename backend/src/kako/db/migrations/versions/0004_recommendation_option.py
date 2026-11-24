"""A plan's options: each recommendation names the option it belongs to, and a plan names the
option the orchestrator recommends, if any.

A turn's answer offers up to 4 options, each one what-if with its allocations. Each allocation is
one `recommendation` row (the entity and its monthly amount), so an option is the recommendations
that share its label: accepting the plan with an option writes that option's allocations as
`plan.allocation` facts. Unique on (`plan_id`, `option`, `entity_id`).

The way back is `alembic downgrade 0003`, which drops the two columns and the unique key. Plans
stored since lose which option each recommendation belonged to.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNIQUE = "uq_recommendation_plan_id_option_entity_id"


def upgrade() -> None:
    # Rows stored before options existed (none in the demo) become the option "A".
    op.add_column(
        "recommendation", sa.Column("option", sa.Text(), nullable=False, server_default="A")
    )
    op.alter_column("recommendation", "option", server_default=None)
    op.create_unique_constraint(
        "uq_recommendation_plan_id_option_entity_id",
        "recommendation",
        ["plan_id", "option", "entity_id"],
    )
    op.add_column("plan", sa.Column("recommended_option", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("plan", "recommended_option")
    op.drop_constraint(
        "uq_recommendation_plan_id_option_entity_id", "recommendation", type_="unique"
    )
    op.drop_column("recommendation", "option")
