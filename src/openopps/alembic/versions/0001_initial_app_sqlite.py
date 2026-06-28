"""Create initial durable app SQLite schema.

Revision ID: 0001_initial_app_sqlite
Revises:
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial_app_sqlite"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("version", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_sources_provider_id", "sources", ["provider_id"])
    op.create_index("ix_sources_synced_at", "sources", ["synced_at"])

    op.create_table(
        "boards",
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
        sa.PrimaryKeyConstraint("key"),
        sa.UniqueConstraint("source_key", "remote_id", name="uq_board_source_remote"),
    )
    op.create_index("ix_boards_domain", "boards", ["domain"])
    op.create_index("ix_boards_key", "boards", ["key"])
    op.create_index("ix_boards_name", "boards", ["name"])
    op.create_index("ix_boards_remote_id", "boards", ["remote_id"])
    op.create_index("ix_boards_remote_slug", "boards", ["remote_slug"])
    op.create_index("ix_boards_source_key", "boards", ["source_key"])
    op.create_index("ix_boards_synced_at", "boards", ["synced_at"])

    op.create_table(
        "board_providers",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_key", "board_key", "provider_id", name="uq_board_provider"
        ),
    )
    op.create_index("ix_board_providers_board_key", "board_providers", ["board_key"])
    op.create_index(
        "ix_board_providers_detected_at", "board_providers", ["detected_at"]
    )
    op.create_index("ix_board_providers_host", "board_providers", ["host"])
    op.create_index(
        "ix_board_providers_provider_id", "board_providers", ["provider_id"]
    )
    op.create_index("ix_board_providers_site", "board_providers", ["site"])
    op.create_index("ix_board_providers_source_key", "board_providers", ["source_key"])
    op.create_index(
        "ix_board_providers_support_level", "board_providers", ["support_level"]
    )
    op.create_index("ix_board_providers_tenant", "board_providers", ["tenant"])
    op.create_index("ix_board_providers_token", "board_providers", ["token"])

    op.create_table(
        "jobs",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "board_key", "provider_id", "remote_id", name="uq_job_remote"
        ),
    )
    op.create_index("ix_jobs_board_key", "jobs", ["board_key"])
    op.create_index("ix_jobs_closed_at", "jobs", ["closed_at"])
    op.create_index("ix_jobs_current_content_hash", "jobs", ["current_content_hash"])
    op.create_index("ix_jobs_current_payload_hash", "jobs", ["current_payload_hash"])
    op.create_index("ix_jobs_current_version_id", "jobs", ["current_version_id"])
    op.create_index("ix_jobs_first_seen_at", "jobs", ["first_seen_at"])
    op.create_index("ix_jobs_last_seen_at", "jobs", ["last_seen_at"])
    op.create_index("ix_jobs_provider_id", "jobs", ["provider_id"])
    op.create_index("ix_jobs_remote_id", "jobs", ["remote_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_synced_at", "jobs", ["synced_at"])

    op.create_table(
        "job_versions",
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "content_hash", name="uq_job_version_content"),
        sa.UniqueConstraint("job_id", "version", name="uq_job_version_number"),
    )
    op.create_index("ix_job_versions_company", "job_versions", ["company"])
    op.create_index("ix_job_versions_content_hash", "job_versions", ["content_hash"])
    op.create_index("ix_job_versions_created_at", "job_versions", ["created_at"])
    op.create_index("ix_job_versions_department", "job_versions", ["department"])
    op.create_index(
        "ix_job_versions_employment_type", "job_versions", ["employment_type"]
    )
    op.create_index("ix_job_versions_first_seen_at", "job_versions", ["first_seen_at"])
    op.create_index("ix_job_versions_job_id", "job_versions", ["job_id"])
    op.create_index("ix_job_versions_last_seen_at", "job_versions", ["last_seen_at"])
    op.create_index("ix_job_versions_payload_hash", "job_versions", ["payload_hash"])
    op.create_index("ix_job_versions_posted_at", "job_versions", ["posted_at"])
    op.create_index("ix_job_versions_remote", "job_versions", ["remote"])
    op.create_index(
        "ix_job_versions_salary_currency", "job_versions", ["salary_currency"]
    )
    op.create_index("ix_job_versions_team", "job_versions", ["team"])
    op.create_index("ix_job_versions_title", "job_versions", ["title"])
    op.create_index("ix_job_versions_updated_at", "job_versions", ["updated_at"])
    op.create_index("ix_job_versions_version", "job_versions", ["version"])
    op.create_index(
        "ix_job_versions_workplace_type", "job_versions", ["workplace_type"]
    )

    op.create_table(
        "job_version_locations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_version_id", "ordinal", "label", name="uq_job_version_location"
        ),
    )
    op.create_index(
        "ix_job_version_locations_job_version_id",
        "job_version_locations",
        ["job_version_id"],
    )
    op.create_index(
        "ix_job_version_locations_label", "job_version_locations", ["label"]
    )
    op.create_index(
        "ix_job_version_locations_ordinal", "job_version_locations", ["ordinal"]
    )

    op.create_table(
        "job_version_skills",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("level", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_version_skills_job_version_id", "job_version_skills", ["job_version_id"]
    )
    op.create_index("ix_job_version_skills_level", "job_version_skills", ["level"])
    op.create_index("ix_job_version_skills_name", "job_version_skills", ["name"])
    op.create_index("ix_job_version_skills_ordinal", "job_version_skills", ["ordinal"])

    op.create_table(
        "job_version_skill_keywords",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("skill_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("keyword", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id", "ordinal", "keyword", name="uq_job_skill_keyword"
        ),
    )
    op.create_index(
        "ix_job_version_skill_keywords_keyword",
        "job_version_skill_keywords",
        ["keyword"],
    )
    op.create_index(
        "ix_job_version_skill_keywords_ordinal",
        "job_version_skill_keywords",
        ["ordinal"],
    )
    op.create_index(
        "ix_job_version_skill_keywords_skill_id",
        "job_version_skill_keywords",
        ["skill_id"],
    )

    op.create_table(
        "job_version_bullets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_version_id", "kind", "ordinal", "text", name="uq_job_version_bullet"
        ),
    )
    op.create_index(
        "ix_job_version_bullets_job_version_id",
        "job_version_bullets",
        ["job_version_id"],
    )
    op.create_index("ix_job_version_bullets_kind", "job_version_bullets", ["kind"])
    op.create_index(
        "ix_job_version_bullets_ordinal", "job_version_bullets", ["ordinal"]
    )

    op.create_table(
        "job_payload_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("payload_kind", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "payload_kind", "payload_hash", name="uq_job_payload_snapshot"
        ),
    )
    op.create_index(
        "ix_job_payload_snapshots_job_id", "job_payload_snapshots", ["job_id"]
    )
    op.create_index(
        "ix_job_payload_snapshots_observed_at", "job_payload_snapshots", ["observed_at"]
    )
    op.create_index(
        "ix_job_payload_snapshots_payload_hash",
        "job_payload_snapshots",
        ["payload_hash"],
    )
    op.create_index(
        "ix_job_payload_snapshots_payload_kind",
        "job_payload_snapshots",
        ["payload_kind"],
    )

    op.create_table(
        "job_sync_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("board_key", sa.String(), nullable=False),
        sa.Column("provider_id", sa.String(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), nullable=False),
        sa.Column("changed_count", sa.Integer(), nullable=False),
        sa.Column("reopened_count", sa.Integer(), nullable=False),
        sa.Column("closed_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_sync_runs_board_key", "job_sync_runs", ["board_key"])
    op.create_index("ix_job_sync_runs_provider_id", "job_sync_runs", ["provider_id"])
    op.create_index("ix_job_sync_runs_success", "job_sync_runs", ["success"])
    op.create_index("ix_job_sync_runs_synced_at", "job_sync_runs", ["synced_at"])

    op.create_table(
        "job_sync_observations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("sync_run_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), nullable=False),
        sa.Column("job_version_id", sa.String(), nullable=True),
        sa.Column("observation_kind", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("payload_hash", sa.String(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_sync_observations_content_hash",
        "job_sync_observations",
        ["content_hash"],
    )
    op.create_index(
        "ix_job_sync_observations_job_id", "job_sync_observations", ["job_id"]
    )
    op.create_index(
        "ix_job_sync_observations_job_version_id",
        "job_sync_observations",
        ["job_version_id"],
    )
    op.create_index(
        "ix_job_sync_observations_observation_kind",
        "job_sync_observations",
        ["observation_kind"],
    )
    op.create_index(
        "ix_job_sync_observations_observed_at", "job_sync_observations", ["observed_at"]
    )
    op.create_index(
        "ix_job_sync_observations_payload_hash",
        "job_sync_observations",
        ["payload_hash"],
    )
    op.create_index(
        "ix_job_sync_observations_sync_run_id", "job_sync_observations", ["sync_run_id"]
    )


def downgrade() -> None:
    op.drop_table("job_sync_observations")
    op.drop_table("job_sync_runs")
    op.drop_table("job_payload_snapshots")
    op.drop_table("job_version_bullets")
    op.drop_table("job_version_skill_keywords")
    op.drop_table("job_version_skills")
    op.drop_table("job_version_locations")
    op.drop_table("job_versions")
    op.drop_table("jobs")
    op.drop_table("board_providers")
    op.drop_table("boards")
    op.drop_table("sources")
