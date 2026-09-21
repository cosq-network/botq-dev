"""requirement analysis and findings

Revision ID: e4f4f4c2a1b9
Revises: dd9a9db68cdb
Create Date: 2026-09-17 19:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "e4f4f4c2a1b9"
down_revision = "dd9a9db68cdb"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirement_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_version_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_version_number", sa.Integer(), nullable=False),
        sa.Column("baseline_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("proposed_work_items", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["baseline_id"], ["requirement_baselines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["baseline_version_id"],
            ["requirement_baseline_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("requirement_analyses", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_requirement_analyses_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_requirement_analyses_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_requirement_analyses_baseline_id"), ["baseline_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_requirement_analyses_baseline_version_id"),
            ["baseline_version_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_requirement_analyses_baseline_version",
            ["baseline_id", "baseline_version_number"],
            unique=False,
        )
        batch_op.create_index(
            "ix_requirement_analyses_org_created", ["organization_id", "created_at"], unique=False
        )

    op.create_table(
        "requirement_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["requirement_analyses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id", "fingerprint", name="uq_requirement_finding_fingerprint"
        ),
    )
    with op.batch_alter_table("requirement_findings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_requirement_findings_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_requirement_findings_project_id"), ["project_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_requirement_findings_analysis_id"), ["analysis_id"], unique=False
        )
        batch_op.create_index(
            "ix_requirement_findings_analysis_status", ["analysis_id", "status"], unique=False
        )

    with op.batch_alter_table("work_items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_analysis_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_work_items_source_analysis_id",
            "requirement_analyses",
            ["source_analysis_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            batch_op.f("ix_work_items_source_analysis_id"), ["source_analysis_id"], unique=False
        )


def downgrade():
    with op.batch_alter_table("work_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_work_items_source_analysis_id"))
        batch_op.drop_constraint("fk_work_items_source_analysis_id", type_="foreignkey")
        batch_op.drop_column("source_analysis_id")

    with op.batch_alter_table("requirement_findings", schema=None) as batch_op:
        batch_op.drop_index("ix_requirement_findings_analysis_status")
        batch_op.drop_index(batch_op.f("ix_requirement_findings_analysis_id"))
        batch_op.drop_index(batch_op.f("ix_requirement_findings_project_id"))
        batch_op.drop_index(batch_op.f("ix_requirement_findings_organization_id"))
    op.drop_table("requirement_findings")

    with op.batch_alter_table("requirement_analyses", schema=None) as batch_op:
        batch_op.drop_index("ix_requirement_analyses_org_created")
        batch_op.drop_index("ix_requirement_analyses_baseline_version")
        batch_op.drop_index(batch_op.f("ix_requirement_analyses_baseline_version_id"))
        batch_op.drop_index(batch_op.f("ix_requirement_analyses_baseline_id"))
        batch_op.drop_index(batch_op.f("ix_requirement_analyses_project_id"))
        batch_op.drop_index(batch_op.f("ix_requirement_analyses_organization_id"))
    op.drop_table("requirement_analyses")
