"""Add durable lifecycle and batch progress to job sync runs.

Revision ID: 0004_job_sync_run_lifecycle
Revises: 0003_jobs_current_version_fk
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_job_sync_run_lifecycle"
down_revision: str | None = "0003_jobs_current_version_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_sync_runs") as batch:
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("finished_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(), nullable=True))
        batch.add_column(sa.Column("error_kind", sa.String(), nullable=True))
        batch.add_column(
            sa.Column(
                "authoritative",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "committed_batch_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE job_sync_runs
            SET started_at = synced_at,
                finished_at = synced_at,
                status = CASE WHEN success THEN 'succeeded' ELSE 'failed' END,
                error_kind = CASE
                    WHEN success THEN NULL
                    WHEN error IS NOT NULL THEN 'legacy_failure'
                    ELSE 'unknown'
                END,
                authoritative = success
            """
        )
    )

    with op.batch_alter_table("job_sync_runs") as batch:
        batch.alter_column("started_at", nullable=False)
        batch.alter_column("status", nullable=False)
        batch.create_index("ix_job_sync_runs_started_at", ["started_at"])
        batch.create_index("ix_job_sync_runs_finished_at", ["finished_at"])
        batch.create_index("ix_job_sync_runs_status", ["status"])
        batch.create_index("ix_job_sync_runs_error_kind", ["error_kind"])
        batch.create_index("ix_job_sync_runs_authoritative", ["authoritative"])


def downgrade() -> None:
    with op.batch_alter_table("job_sync_runs") as batch:
        batch.drop_index("ix_job_sync_runs_authoritative")
        batch.drop_index("ix_job_sync_runs_error_kind")
        batch.drop_index("ix_job_sync_runs_status")
        batch.drop_index("ix_job_sync_runs_finished_at")
        batch.drop_index("ix_job_sync_runs_started_at")
        batch.drop_column("committed_batch_count")
        batch.drop_column("authoritative")
        batch.drop_column("error_kind")
        batch.drop_column("status")
        batch.drop_column("finished_at")
        batch.drop_column("started_at")
