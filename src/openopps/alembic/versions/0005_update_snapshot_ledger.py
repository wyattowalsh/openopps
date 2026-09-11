"""Create the naïve update-snapshot ledger (header + twelve copies).

Revision ID: 0005_update_snapshot_ledger
Revises: 0004_job_sync_run_lifecycle
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_update_snapshot_ledger"
down_revision: str | None = "0004_job_sync_run_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPY_TABLES: tuple[str, ...] = (
    "update_snapshot_sources",
    "update_snapshot_boards",
    "update_snapshot_board_providers",
    "update_snapshot_jobs",
    "update_snapshot_job_versions",
    "update_snapshot_job_version_locations",
    "update_snapshot_job_version_skills",
    "update_snapshot_job_version_skill_keywords",
    "update_snapshot_job_version_bullets",
    "update_snapshot_job_payload_snapshots",
    "update_snapshot_job_sync_runs",
    "update_snapshot_job_sync_observations",
)


def upgrade() -> None:
    op.create_table(
        "update_snapshots",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("appended_at", sa.DateTime(), nullable=False),
        sa.Column("collection_status", sa.String(), nullable=False),
        sa.Column("validation_ok", sa.Boolean(), nullable=False),
        sa.Column("attestation", sa.String(), nullable=False),
        sa.Column("run_digest", sa.String(), nullable=False),
        sa.Column("schema_revision", sa.String(), nullable=False),
        sa.Column("row_counts", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index(
        "ix_update_snapshots_appended_at", "update_snapshots", ["appended_at"]
    )
    op.create_index(
        "ix_update_snapshots_attestation", "update_snapshots", ["attestation"]
    )
    op.create_index(
        "ix_update_snapshots_captured_at", "update_snapshots", ["captured_at"]
    )
    op.create_index(
        "ix_update_snapshots_collection_status",
        "update_snapshots",
        ["collection_status"],
    )
    op.create_index(
        "ix_update_snapshots_run_digest", "update_snapshots", ["run_digest"]
    )
    op.create_index(
        "ix_update_snapshots_schema_revision", "update_snapshots", ["schema_revision"]
    )
    op.create_index(
        "ix_update_snapshots_validation_ok", "update_snapshots", ["validation_ok"]
    )

    op.create_table(
        "update_snapshot_sources",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("version", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "key"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
    )
    op.create_index(
        "ix_update_snapshot_sources_provider_id",
        "update_snapshot_sources",
        ["provider_id"],
    )
    op.create_index(
        "ix_update_snapshot_sources_synced_at", "update_snapshot_sources", ["synced_at"]
    )

    op.create_table(
        "update_snapshot_boards",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("source_keys", sa.JSON(), nullable=True),
        sa.Column("source_board_keys", sa.JSON(), nullable=True),
        sa.Column("remote_id", sa.String(), nullable=False),
        sa.Column("remote_slug", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("website_url", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("markets", sa.JSON(), nullable=True),
        sa.Column("locations", sa.JSON(), nullable=True),
        sa.Column("staff_count", sa.Integer(), nullable=True),
        sa.Column("num_jobs_hint", sa.Integer(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "key"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_key",
            "remote_id",
            name="uq_update_snapshot_board_source_remote",
        ),
    )
    op.create_index(
        "ix_update_snapshot_boards_domain", "update_snapshot_boards", ["domain"]
    )
    op.create_index("ix_update_snapshot_boards_key", "update_snapshot_boards", ["key"])
    op.create_index(
        "ix_update_snapshot_boards_name", "update_snapshot_boards", ["name"]
    )
    op.create_index(
        "ix_update_snapshot_boards_remote_id", "update_snapshot_boards", ["remote_id"]
    )
    op.create_index(
        "ix_update_snapshot_boards_remote_slug",
        "update_snapshot_boards",
        ["remote_slug"],
    )
    op.create_index(
        "ix_update_snapshot_boards_source_key", "update_snapshot_boards", ["source_key"]
    )
    op.create_index(
        "ix_update_snapshot_boards_synced_at", "update_snapshot_boards", ["synced_at"]
    )

    op.create_table(
        "update_snapshot_board_providers",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("board_key", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("support_level", sa.String(), nullable=False),
        sa.Column("count_hint", sa.Integer(), nullable=True),
        sa.Column("board_url", sa.String(), nullable=True),
        sa.Column("token", sa.String(), nullable=True),
        sa.Column("host", sa.String(), nullable=True),
        sa.Column("tenant", sa.String(), nullable=True),
        sa.Column("site", sa.String(), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_key",
            "board_key",
            "provider_id",
            name="uq_update_snapshot_board_provider",
        ),
    )
    op.create_index(
        "ix_update_snapshot_board_providers_board_key",
        "update_snapshot_board_providers",
        ["board_key"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_detected_at",
        "update_snapshot_board_providers",
        ["detected_at"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_host",
        "update_snapshot_board_providers",
        ["host"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_provider_id",
        "update_snapshot_board_providers",
        ["provider_id"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_site",
        "update_snapshot_board_providers",
        ["site"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_source_key",
        "update_snapshot_board_providers",
        ["source_key"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_support_level",
        "update_snapshot_board_providers",
        ["support_level"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_tenant",
        "update_snapshot_board_providers",
        ["tenant"],
    )
    op.create_index(
        "ix_update_snapshot_board_providers_token",
        "update_snapshot_board_providers",
        ["token"],
    )

    op.create_table(
        "update_snapshot_jobs",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("board_key", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("remote_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("current_content_hash", sa.String(), nullable=True),
        sa.Column("current_payload_hash", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "board_key",
            "provider_id",
            "remote_id",
            name="uq_update_snapshot_job_remote",
        ),
    )
    op.create_index(
        "ix_update_snapshot_jobs_board_key", "update_snapshot_jobs", ["board_key"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_closed_at", "update_snapshot_jobs", ["closed_at"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_current_content_hash",
        "update_snapshot_jobs",
        ["current_content_hash"],
    )
    op.create_index(
        "ix_update_snapshot_jobs_current_payload_hash",
        "update_snapshot_jobs",
        ["current_payload_hash"],
    )
    op.create_index(
        "ix_update_snapshot_jobs_current_version_id",
        "update_snapshot_jobs",
        ["current_version_id"],
    )
    op.create_index(
        "ix_update_snapshot_jobs_first_seen_at",
        "update_snapshot_jobs",
        ["first_seen_at"],
    )
    op.create_index(
        "ix_update_snapshot_jobs_last_seen_at", "update_snapshot_jobs", ["last_seen_at"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_provider_id", "update_snapshot_jobs", ["provider_id"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_remote_id", "update_snapshot_jobs", ["remote_id"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_status", "update_snapshot_jobs", ["status"]
    )
    op.create_index(
        "ix_update_snapshot_jobs_synced_at", "update_snapshot_jobs", ["synced_at"]
    )

    op.create_table(
        "update_snapshot_job_versions",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("locations", sa.JSON(), nullable=True),
        sa.Column("department", sa.String(), nullable=True),
        sa.Column("team", sa.String(), nullable=True),
        sa.Column("workplace_type", sa.String(), nullable=True),
        sa.Column("company", sa.String(), nullable=True),
        sa.Column("employment_type", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("description_html", sa.String(), nullable=True),
        sa.Column("remote", sa.String(), nullable=True),
        sa.Column("compensation", sa.JSON(), nullable=True),
        sa.Column("salary", sa.String(), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(), nullable=True),
        sa.Column("experience", sa.String(), nullable=True),
        sa.Column("responsibilities", sa.JSON(), nullable=True),
        sa.Column("qualifications", sa.JSON(), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=True),
        sa.Column("job_description", sa.JSON(), nullable=True),
        sa.Column("posting_url", sa.String(), nullable=True),
        sa.Column("apply_url", sa.String(), nullable=True),
        sa.Column("posted_at", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_id",
            "content_hash",
            name="uq_update_snapshot_job_version_content",
        ),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_id",
            "version",
            name="uq_update_snapshot_job_version_number",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_versions_company",
        "update_snapshot_job_versions",
        ["company"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_content_hash",
        "update_snapshot_job_versions",
        ["content_hash"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_created_at",
        "update_snapshot_job_versions",
        ["created_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_department",
        "update_snapshot_job_versions",
        ["department"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_employment_type",
        "update_snapshot_job_versions",
        ["employment_type"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_first_seen_at",
        "update_snapshot_job_versions",
        ["first_seen_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_job_id",
        "update_snapshot_job_versions",
        ["job_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_last_seen_at",
        "update_snapshot_job_versions",
        ["last_seen_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_payload_hash",
        "update_snapshot_job_versions",
        ["payload_hash"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_posted_at",
        "update_snapshot_job_versions",
        ["posted_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_remote",
        "update_snapshot_job_versions",
        ["remote"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_salary_currency",
        "update_snapshot_job_versions",
        ["salary_currency"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_team", "update_snapshot_job_versions", ["team"]
    )
    op.create_index(
        "ix_update_snapshot_job_versions_title",
        "update_snapshot_job_versions",
        ["title"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_updated_at",
        "update_snapshot_job_versions",
        ["updated_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_version",
        "update_snapshot_job_versions",
        ["version"],
    )
    op.create_index(
        "ix_update_snapshot_job_versions_workplace_type",
        "update_snapshot_job_versions",
        ["workplace_type"],
    )

    op.create_table(
        "update_snapshot_job_version_locations",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_version_id",
            "ordinal",
            "label",
            name="uq_update_snapshot_job_version_location",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_version_locations_job_version_id",
        "update_snapshot_job_version_locations",
        ["job_version_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_locations_label",
        "update_snapshot_job_version_locations",
        ["label"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_locations_ordinal",
        "update_snapshot_job_version_locations",
        ["ordinal"],
    )

    op.create_table(
        "update_snapshot_job_version_skills",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_version_id",
            "ordinal",
            name="uq_update_snapshot_job_version_skill",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_version_skills_job_version_id",
        "update_snapshot_job_version_skills",
        ["job_version_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_skills_level",
        "update_snapshot_job_version_skills",
        ["level"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_skills_name",
        "update_snapshot_job_version_skills",
        ["name"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_skills_ordinal",
        "update_snapshot_job_version_skills",
        ["ordinal"],
    )

    op.create_table(
        "update_snapshot_job_version_skill_keywords",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("skill_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "skill_id",
            "ordinal",
            "keyword",
            name="uq_update_snapshot_job_skill_keyword",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_version_skill_keywords_keyword",
        "update_snapshot_job_version_skill_keywords",
        ["keyword"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_skill_keywords_ordinal",
        "update_snapshot_job_version_skill_keywords",
        ["ordinal"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_skill_keywords_skill_id",
        "update_snapshot_job_version_skill_keywords",
        ["skill_id"],
    )

    op.create_table(
        "update_snapshot_job_version_bullets",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_version_id",
            "kind",
            "ordinal",
            "text",
            name="uq_update_snapshot_job_version_bullet",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_version_bullets_job_version_id",
        "update_snapshot_job_version_bullets",
        ["job_version_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_bullets_kind",
        "update_snapshot_job_version_bullets",
        ["kind"],
    )
    op.create_index(
        "ix_update_snapshot_job_version_bullets_ordinal",
        "update_snapshot_job_version_bullets",
        ["ordinal"],
    )

    op.create_table(
        "update_snapshot_job_payload_snapshots",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("payload_kind", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "job_id",
            "payload_kind",
            "payload_hash",
            name="uq_update_snapshot_job_payload_snapshot",
        ),
    )
    op.create_index(
        "ix_update_snapshot_job_payload_snapshots_job_id",
        "update_snapshot_job_payload_snapshots",
        ["job_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_payload_snapshots_observed_at",
        "update_snapshot_job_payload_snapshots",
        ["observed_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_payload_snapshots_payload_hash",
        "update_snapshot_job_payload_snapshots",
        ["payload_hash"],
    )
    op.create_index(
        "ix_update_snapshot_job_payload_snapshots_payload_kind",
        "update_snapshot_job_payload_snapshots",
        ["payload_kind"],
    )

    op.create_table(
        "update_snapshot_job_sync_runs",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("board_key", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("error_kind", sa.String(), nullable=True),
        sa.Column("authoritative", sa.Boolean(), nullable=False),
        sa.Column("committed_batch_count", sa.Integer(), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("reopened_count", sa.Integer(), nullable=False),
        sa.Column("closed_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_authoritative",
        "update_snapshot_job_sync_runs",
        ["authoritative"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_board_key",
        "update_snapshot_job_sync_runs",
        ["board_key"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_error_kind",
        "update_snapshot_job_sync_runs",
        ["error_kind"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_finished_at",
        "update_snapshot_job_sync_runs",
        ["finished_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_provider_id",
        "update_snapshot_job_sync_runs",
        ["provider_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_started_at",
        "update_snapshot_job_sync_runs",
        ["started_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_status",
        "update_snapshot_job_sync_runs",
        ["status"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_success",
        "update_snapshot_job_sync_runs",
        ["success"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_runs_synced_at",
        "update_snapshot_job_sync_runs",
        ["synced_at"],
    )

    op.create_table(
        "update_snapshot_job_sync_observations",
        sa.Column("snapshot_id", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("sync_run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=True),
        sa.Column("observation_kind", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("payload_hash", sa.String(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("snapshot_id", "id"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["update_snapshots.snapshot_id"]),
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_content_hash",
        "update_snapshot_job_sync_observations",
        ["content_hash"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_job_id",
        "update_snapshot_job_sync_observations",
        ["job_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_job_version_id",
        "update_snapshot_job_sync_observations",
        ["job_version_id"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_observation_kind",
        "update_snapshot_job_sync_observations",
        ["observation_kind"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_observed_at",
        "update_snapshot_job_sync_observations",
        ["observed_at"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_payload_hash",
        "update_snapshot_job_sync_observations",
        ["payload_hash"],
    )
    op.create_index(
        "ix_update_snapshot_job_sync_observations_sync_run_id",
        "update_snapshot_job_sync_observations",
        ["sync_run_id"],
    )


def downgrade() -> None:
    for name in reversed(_COPY_TABLES):
        op.drop_table(name)
    op.drop_table("update_snapshots")
