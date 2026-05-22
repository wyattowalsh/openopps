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
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_sources_enabled", "sources", ["enabled"])
    op.create_index("ix_sources_provider_id", "sources", ["provider_id"])
    op.create_index("ix_sources_synced_at", "sources", ["synced_at"])

    op.create_table(
        "boards",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
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
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("raw_listing", sa.JSON(), nullable=True),
        sa.Column("raw_detail", sa.JSON(), nullable=True),
        sa.Column("extra_payload", sa.JSON(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "board_key", "provider_id", "remote_id", name="uq_job_remote"
        ),
    )
    op.create_index("ix_jobs_board_key", "jobs", ["board_key"])
    op.create_index("ix_jobs_company", "jobs", ["company"])
    op.create_index("ix_jobs_department", "jobs", ["department"])
    op.create_index("ix_jobs_employment_type", "jobs", ["employment_type"])
    op.create_index("ix_jobs_posted_at", "jobs", ["posted_at"])
    op.create_index("ix_jobs_provider_id", "jobs", ["provider_id"])
    op.create_index("ix_jobs_remote", "jobs", ["remote"])
    op.create_index("ix_jobs_remote_id", "jobs", ["remote_id"])
    op.create_index("ix_jobs_salary_currency", "jobs", ["salary_currency"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_synced_at", "jobs", ["synced_at"])
    op.create_index("ix_jobs_team", "jobs", ["team"])
    op.create_index("ix_jobs_title", "jobs", ["title"])
    op.create_index("ix_jobs_updated_at", "jobs", ["updated_at"])
    op.create_index("ix_jobs_workplace_type", "jobs", ["workplace_type"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("board_providers")
    op.drop_table("boards")
    op.drop_table("sources")
