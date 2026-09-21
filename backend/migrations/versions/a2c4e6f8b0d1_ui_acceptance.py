"""phase 4 design, preview and acceptance control plane

Revision ID: a2c4e6f8b0d1
Revises: f7d3a1c5e8b2
Create Date: 2026-09-17 23:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a2c4e6f8b0d1"
down_revision = "f7d3a1c5e8b2"
branch_labels = None
depends_on = None


def _indexes(table, columns):
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade():
    op.create_table(
        "design_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("file_id", sa.String(length=255), nullable=False),
        sa.Column("file_url", sa.String(length=2048), nullable=True),
        sa.Column("preview_url", sa.String(length=2048), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("handoff", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id"),
    )
    _indexes("design_references", ["organization_id", "project_id"])
    op.create_index(
        "ix_design_references_project_provider", "design_references", ["project_id", "provider"]
    )

    op.create_table(
        "design_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("design_reference_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.String(length=255), nullable=True),
        sa.Column("node_id", sa.String(length=255), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["design_reference_id"], ["design_references.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "design_reference_id",
            "work_item_id",
            "page_id",
            "node_id",
            name="uq_design_link_anchor",
        ),
    )
    _indexes(
        "design_links", ["organization_id", "project_id", "design_reference_id", "work_item_id"]
    )

    op.create_table(
        "preview_deployments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("mockup_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("mockup_version", sa.Integer(), nullable=False),
        sa.Column("mockup_hash", sa.String(length=64), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=True),
        sa.Column("commit_sha", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("access_policy", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mockup_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "preview_deployments",
        ["organization_id", "project_id", "mockup_artifact_id", "change_set_id"],
    )
    op.create_index(
        "ix_preview_deployments_project_status", "preview_deployments", ["project_id", "status"]
    )

    op.create_table(
        "acceptance_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("preview_id", sa.Uuid(), nullable=False),
        sa.Column("work_item_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scenario_guidance", sa.JSON(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("completed_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preview_id"], ["preview_deployments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("acceptance_sessions", ["organization_id", "project_id", "preview_id", "work_item_id"])

    op.create_table(
        "defects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("work_item_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reproduction_steps", sa.JSON(), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("actual", sa.Text(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("regression_test_required", sa.Boolean(), nullable=False),
        sa.Column("regression_evidence", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["acceptance_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes("defects", ["organization_id", "project_id", "session_id", "work_item_id"])
    op.create_index(
        "ix_defects_project_status_severity", "defects", ["project_id", "status", "severity"]
    )

    op.create_table(
        "acceptance_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_key", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("defect_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["acceptance_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["defect_id"], ["defects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "criterion_key", name="uq_acceptance_result_criterion"),
    )
    _indexes("acceptance_results", ["organization_id", "project_id", "session_id", "defect_id"])


def downgrade():
    for index, table in (
        ("ix_acceptance_results_defect_id", "acceptance_results"),
        ("ix_acceptance_results_session_id", "acceptance_results"),
        ("ix_acceptance_results_project_id", "acceptance_results"),
        ("ix_acceptance_results_organization_id", "acceptance_results"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("acceptance_results")
    op.drop_index("ix_defects_project_status_severity", table_name="defects")
    for column in ("work_item_id", "session_id", "project_id", "organization_id"):
        op.drop_index(f"ix_defects_{column}", table_name="defects")
    op.drop_table("defects")
    for column in ("work_item_id", "preview_id", "project_id", "organization_id"):
        op.drop_index(f"ix_acceptance_sessions_{column}", table_name="acceptance_sessions")
    op.drop_table("acceptance_sessions")
    op.drop_index("ix_preview_deployments_project_status", table_name="preview_deployments")
    for column in ("change_set_id", "mockup_artifact_id", "project_id", "organization_id"):
        op.drop_index(f"ix_preview_deployments_{column}", table_name="preview_deployments")
    op.drop_table("preview_deployments")
    for column in ("work_item_id", "design_reference_id", "project_id", "organization_id"):
        op.drop_index(f"ix_design_links_{column}", table_name="design_links")
    op.drop_table("design_links")
    op.drop_index("ix_design_references_project_provider", table_name="design_references")
    op.drop_index("ix_design_references_project_id", table_name="design_references")
    op.drop_index("ix_design_references_organization_id", table_name="design_references")
    op.drop_table("design_references")
