"""Add url_pull_runs, membership scope, and the matching snapshot copy.

Revision ID: 0006_url_pull_runs
Revises: 0005_update_snapshot_ledger
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_url_pull_runs"
down_revision: str | None = "0005_update_snapshot_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEMBERSHIP_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("jobs", "membership", "ix_jobs_membership"),
    ("update_snapshot_jobs", "membership", "ix_update_snapshot_jobs_membership"),
    (
        "job_sync_runs",
        "membership_scope",
        "ix_job_sync_runs_membership_scope",
    ),
    (
        "update_snapshot_job_sync_runs",
        "membership_scope",
        "ix_update_snapshot_job_sync_runs_membership_scope",
    ),
)

_URL_PULL_RUN_INDEXES: tuple[str, ...] = (
    "started_at",
    "finished_at",
    "status",
    "error_kind",
    "requested_operation",
    "resolved_operation",
    "provider_id",
    "native_board_identity",
    "posting_identity",
    "board_key",
    "job_sync_run_id",
    "job_id",
    "job_version_id",
    "membership_scope",
    "discovery_method",
)


def upgrade() -> None:
    for table_name, column_name, index_name in _MEMBERSHIP_COLUMNS:
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(
                sa.Column(
                    column_name,
                    sa.String(),
                    nullable=False,
                    server_default="listed",
                )
            )
            batch.create_index(index_name, [column_name])

    op.create_table(
        "url_pull_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_kind", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("requested_operation", sa.String(), nullable=False),
        sa.Column("resolved_operation", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("native_board_identity", sa.String(), nullable=False),
        sa.Column("posting_identity", sa.String(), nullable=True),
        sa.Column("board_key", sa.String(), nullable=True),
        sa.Column("job_sync_run_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("job_version_id", sa.String(), nullable=True),
        sa.Column("membership_scope", sa.String(), nullable=True),
        sa.Column("membership_authoritative", sa.Boolean(), nullable=True),
        sa.Column("membership_complete", sa.Boolean(), nullable=True),
        sa.Column("membership_observed_count", sa.Integer(), nullable=True),
        sa.Column("detail_status", sa.String(), nullable=True),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("discovery_method", sa.String(), nullable=True),
        sa.Column("requested_url", sa.String(), nullable=True),
        sa.Column("resolved_url", sa.String(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["board_key"], ["boards.key"]),
        sa.ForeignKeyConstraint(["job_sync_run_id"], ["job_sync_runs.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["job_version_id"], ["job_versions.id"]),
    )
    for column_name in _URL_PULL_RUN_INDEXES:
        op.create_index(f"ix_url_pull_runs_{column_name}", "url_pull_runs", [column_name])

    op.create_table(
        "update_snapshot_url_pull_runs",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_kind", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("requested_operation", sa.String(), nullable=False),
        sa.Column("resolved_operation", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("native_board_identity", sa.String(), nullable=False),
        sa.Column("posting_identity", sa.String(), nullable=True),
        sa.Column("board_key", sa.String(), nullable=True),
        sa.Column("job_sync_run_id", sa.String(), nullable=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("job_version_id", sa.String(), nullable=True),
        sa.Column("membership_scope", sa.String(), nullable=True),
        sa.Column("membership_authoritative", sa.Boolean(), nullable=True),
        sa.Column("membership_complete", sa.Boolean(), nullable=True),
        sa.Column("membership_observed_count", sa.Integer(), nullable=True),
        sa.Column("detail_status", sa.String(), nullable=True),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("discovery_method", sa.String(), nullable=True),
        sa.Column("requested_url", sa.String(), nullable=True),
        sa.Column("resolved_url", sa.String(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
    )
    for column_name in _URL_PULL_RUN_INDEXES:
        op.create_index(
            f"ix_update_snapshot_url_pull_runs_{column_name}",
            "update_snapshot_url_pull_runs",
            [column_name],
        )


def downgrade() -> None:
    for column_name in reversed(_URL_PULL_RUN_INDEXES):
        op.drop_index(
            f"ix_update_snapshot_url_pull_runs_{column_name}",
            table_name="update_snapshot_url_pull_runs",
        )
    op.drop_table("update_snapshot_url_pull_runs")
    for column_name in reversed(_URL_PULL_RUN_INDEXES):
        op.drop_index(f"ix_url_pull_runs_{column_name}", table_name="url_pull_runs")
    op.drop_table("url_pull_runs")
    for table_name, column_name, index_name in reversed(_MEMBERSHIP_COLUMNS):
        with op.batch_alter_table(table_name) as batch:
            batch.drop_index(index_name)
            batch.drop_column(column_name)
