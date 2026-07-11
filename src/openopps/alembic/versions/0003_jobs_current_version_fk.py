"""Add jobs.current_version_id foreign key with ON DELETE SET NULL.

Revision ID: 0003_jobs_current_version_fk
Revises: 0002_data_model_integrity
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_jobs_current_version_fk"
down_revision: str | None = "0002_data_model_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE jobs
            SET current_version_id = NULL
            WHERE current_version_id IS NOT NULL
              AND current_version_id NOT IN (SELECT id FROM job_versions)
            """
        )
    )

    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_jobs_current_version_id_job_versions",
            "job_versions",
            ["current_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.drop_constraint(
            "fk_jobs_current_version_id_job_versions", type_="foreignkey"
        )