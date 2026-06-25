"""Enforce operational data model integrity.

Revision ID: 0002_data_model_integrity
Revises: 0001_initial_app_sqlite
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_data_model_integrity"
down_revision: str | None = "0001_initial_app_sqlite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _cleanup_orphans()

    with op.batch_alter_table("boards", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_boards_source_key_sources",
            "sources",
            ["source_key"],
            ["key"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("board_providers", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_board_providers_source_key_sources",
            "sources",
            ["source_key"],
            ["key"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_board_providers_board_key_boards",
            "boards",
            ["board_key"],
            ["key"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_jobs_board_key_boards",
            "boards",
            ["board_key"],
            ["key"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_versions", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_versions_job_id_jobs",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_version_locations", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_version_locations_version",
            "job_versions",
            ["job_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_version_skills", recreate="always") as batch:
        batch.create_unique_constraint(
            "uq_job_version_skill", ["job_version_id", "ordinal"]
        )
        batch.create_foreign_key(
            "fk_job_version_skills_version",
            "job_versions",
            ["job_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_version_skill_keywords", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_version_skill_keywords_skill",
            "job_version_skills",
            ["skill_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_version_bullets", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_version_bullets_version",
            "job_versions",
            ["job_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_payload_snapshots", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_payload_snapshots_job",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_sync_runs", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_sync_runs_board",
            "boards",
            ["board_key"],
            ["key"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("job_sync_observations", recreate="always") as batch:
        batch.create_foreign_key(
            "fk_job_sync_observations_run",
            "job_sync_runs",
            ["sync_run_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_job_sync_observations_job",
            "jobs",
            ["job_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_foreign_key(
            "fk_job_sync_observations_version",
            "job_versions",
            ["job_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("job_sync_observations", recreate="always") as batch:
        batch.drop_constraint("fk_job_sync_observations_version", type_="foreignkey")
        batch.drop_constraint("fk_job_sync_observations_job", type_="foreignkey")
        batch.drop_constraint("fk_job_sync_observations_run", type_="foreignkey")

    with op.batch_alter_table("job_sync_runs", recreate="always") as batch:
        batch.drop_constraint("fk_job_sync_runs_board", type_="foreignkey")

    with op.batch_alter_table("job_payload_snapshots", recreate="always") as batch:
        batch.drop_constraint("fk_job_payload_snapshots_job", type_="foreignkey")

    with op.batch_alter_table("job_version_bullets", recreate="always") as batch:
        batch.drop_constraint("fk_job_version_bullets_version", type_="foreignkey")

    with op.batch_alter_table("job_version_skill_keywords", recreate="always") as batch:
        batch.drop_constraint("fk_job_version_skill_keywords_skill", type_="foreignkey")

    with op.batch_alter_table("job_version_skills", recreate="always") as batch:
        batch.drop_constraint("fk_job_version_skills_version", type_="foreignkey")
        batch.drop_constraint("uq_job_version_skill", type_="unique")

    with op.batch_alter_table("job_version_locations", recreate="always") as batch:
        batch.drop_constraint("fk_job_version_locations_version", type_="foreignkey")

    with op.batch_alter_table("job_versions", recreate="always") as batch:
        batch.drop_constraint("fk_job_versions_job_id_jobs", type_="foreignkey")

    with op.batch_alter_table("jobs", recreate="always") as batch:
        batch.drop_constraint("fk_jobs_board_key_boards", type_="foreignkey")

    with op.batch_alter_table("board_providers", recreate="always") as batch:
        batch.drop_constraint("fk_board_providers_board_key_boards", type_="foreignkey")
        batch.drop_constraint(
            "fk_board_providers_source_key_sources", type_="foreignkey"
        )

    with op.batch_alter_table("boards", recreate="always") as batch:
        batch.drop_constraint("fk_boards_source_key_sources", type_="foreignkey")


def _cleanup_orphans() -> None:
    conn = op.get_bind()
    statements = [
        """
        DELETE FROM job_sync_observations
        WHERE sync_run_id NOT IN (SELECT id FROM job_sync_runs)
           OR job_id NOT IN (SELECT id FROM jobs)
        """,
        """
        UPDATE job_sync_observations
        SET job_version_id = NULL
        WHERE job_version_id IS NOT NULL
          AND job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_skill_keywords
        WHERE skill_id NOT IN (SELECT id FROM job_version_skills)
        """,
        """
        DELETE FROM job_version_skills
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_skills
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM job_version_skills
            GROUP BY job_version_id, ordinal
        )
        """,
        """
        DELETE FROM job_version_locations
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_bullets
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_payload_snapshots
        WHERE job_id NOT IN (SELECT id FROM jobs)
        """,
        """
        DELETE FROM job_versions
        WHERE job_id NOT IN (SELECT id FROM jobs)
        """,
        """
        UPDATE jobs
        SET current_version_id = NULL
        WHERE current_version_id IS NOT NULL
          AND current_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_sync_runs
        WHERE board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM job_sync_observations
        WHERE sync_run_id NOT IN (SELECT id FROM job_sync_runs)
        """,
        """
        DELETE FROM jobs
        WHERE board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM board_providers
        WHERE source_key NOT IN (SELECT key FROM sources)
           OR board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM boards
        WHERE source_key NOT IN (SELECT key FROM sources)
        """,
        """
        DELETE FROM board_providers
        WHERE source_key NOT IN (SELECT key FROM sources)
           OR board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM jobs
        WHERE board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM job_versions
        WHERE job_id NOT IN (SELECT id FROM jobs)
        """,
        """
        UPDATE job_sync_observations
        SET job_version_id = NULL
        WHERE job_version_id IS NOT NULL
          AND job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        UPDATE jobs
        SET current_version_id = NULL
        WHERE current_version_id IS NOT NULL
          AND current_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_payload_snapshots
        WHERE job_id NOT IN (SELECT id FROM jobs)
        """,
        """
        DELETE FROM job_version_locations
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_bullets
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_skills
        WHERE job_version_id NOT IN (SELECT id FROM job_versions)
        """,
        """
        DELETE FROM job_version_skills
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM job_version_skills
            GROUP BY job_version_id, ordinal
        )
        """,
        """
        DELETE FROM job_version_skill_keywords
        WHERE skill_id NOT IN (SELECT id FROM job_version_skills)
        """,
        """
        DELETE FROM job_sync_runs
        WHERE board_key NOT IN (SELECT key FROM boards)
        """,
        """
        DELETE FROM job_sync_observations
        WHERE sync_run_id NOT IN (SELECT id FROM job_sync_runs)
           OR job_id NOT IN (SELECT id FROM jobs)
        """,
    ]
    for statement in statements:
        conn.execute(sa.text(statement))
