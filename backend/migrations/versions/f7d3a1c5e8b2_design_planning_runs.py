"""architecture, planning and agent run workflows

Revision ID: f7d3a1c5e8b2
Revises: e4f4f4c2a1b9
Create Date: 2026-09-17 20:30:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "f7d3a1c5e8b2"
down_revision = "e4f4f4c2a1b9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_baseline_id", sa.Uuid(), nullable=True),
        sa.Column("source_baseline_version", sa.Integer(), nullable=True),
        sa.Column("source_baseline_hash", sa.String(length=64), nullable=True),
        sa.Column("source_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("source_artifact_version", sa.Integer(), nullable=True),
        sa.Column("source_artifact_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_baseline_id"], ["requirement_baselines.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_artifacts_organization_id", "artifacts", ["organization_id"])
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])
    op.create_index("ix_artifacts_source_baseline_id", "artifacts", ["source_baseline_id"])
    op.create_index("ix_artifacts_source_artifact_id", "artifacts", ["source_artifact_id"])
    op.create_index(
        "ix_artifacts_project_type_status", "artifacts", ["project_id", "artifact_type", "status"]
    )

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("change_summary", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),
    )
    op.create_index(
        "ix_artifact_versions_organization_id", "artifact_versions", ["organization_id"]
    )
    op.create_index("ix_artifact_versions_artifact_id", "artifact_versions", ["artifact_id"])

    op.create_table(
        "architecture_decision_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("consequences", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "key", name="uq_architecture_decision_key"),
    )
    op.create_index(
        "ix_architecture_decision_records_organization_id",
        "architecture_decision_records",
        ["organization_id"],
    )
    op.create_index(
        "ix_architecture_decision_records_project_id",
        "architecture_decision_records",
        ["project_id"],
    )
    op.create_index(
        "ix_architecture_decision_records_artifact_id",
        "architecture_decision_records",
        ["artifact_id"],
    )

    op.create_table(
        "design_comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("anchor", sa.JSON(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "project_id", "artifact_id"):
        op.create_index(f"ix_design_comments_{column}", "design_comments", [column])

    op.create_table(
        "trace_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_trace_link",
        ),
    )
    op.create_index("ix_trace_links_organization_id", "trace_links", ["organization_id"])
    op.create_index("ix_trace_links_project_id", "trace_links", ["project_id"])
    op.create_index(
        "ix_trace_links_source", "trace_links", ["project_id", "source_type", "source_id"]
    )
    op.create_index(
        "ix_trace_links_target", "trace_links", ["project_id", "target_type", "target_id"]
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("plan_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("current_step", sa.String(length=128), nullable=True),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("writable_paths", sa.JSON(), nullable=False),
        sa.Column("environment", sa.JSON(), nullable=False),
        sa.Column("model_config", sa.JSON(), nullable=False),
        sa.Column("budget", sa.JSON(), nullable=False),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "project_id", "plan_artifact_id"):
        op.create_index(f"ix_agent_runs_{column}", "agent_runs", [column])

    op.create_table(
        "agent_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_run_event_sequence"),
    )
    op.create_index("ix_agent_run_events_organization_id", "agent_run_events", ["organization_id"])
    op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])

    op.create_table(
        "agent_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_checkpoint_sequence"),
    )
    op.create_index(
        "ix_agent_checkpoints_organization_id", "agent_checkpoints", ["organization_id"]
    )
    op.create_index("ix_agent_checkpoints_run_id", "agent_checkpoints", ["run_id"])

    op.create_table(
        "change_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("plan_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("base_commit", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("diff_hash", sa.String(length=64), nullable=True),
        sa.Column("self_review", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "project_id", "run_id", "plan_artifact_id"):
        op.create_index(f"ix_change_sets_{column}", "change_sets", [column])

    op.create_table(
        "change_set_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_set_id", "path", name="uq_change_set_file_path"),
    )
    op.create_index("ix_change_set_files_organization_id", "change_set_files", ["organization_id"])
    op.create_index("ix_change_set_files_change_set_id", "change_set_files", ["change_set_id"])

    op.create_table(
        "verification_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("change_set_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "project_id", "change_set_id"):
        op.create_index(f"ix_verification_runs_{column}", "verification_runs", [column])


def downgrade():
    for index, table in (
        ("ix_verification_runs_change_set_id", "verification_runs"),
        ("ix_verification_runs_project_id", "verification_runs"),
        ("ix_verification_runs_organization_id", "verification_runs"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("verification_runs")
    op.drop_index("ix_change_set_files_change_set_id", table_name="change_set_files")
    op.drop_index("ix_change_set_files_organization_id", table_name="change_set_files")
    op.drop_table("change_set_files")
    for column in ("plan_artifact_id", "run_id", "project_id", "organization_id"):
        op.drop_index(f"ix_change_sets_{column}", table_name="change_sets")
    op.drop_table("change_sets")
    for index, table in (
        ("ix_agent_checkpoints_run_id", "agent_checkpoints"),
        ("ix_agent_checkpoints_organization_id", "agent_checkpoints"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
    op.drop_index("ix_agent_run_events_organization_id", table_name="agent_run_events")
    op.drop_table("agent_run_events")
    for column in ("plan_artifact_id", "project_id", "organization_id"):
        op.drop_index(f"ix_agent_runs_{column}", table_name="agent_runs")
    op.drop_table("agent_runs")
    for index, table in (
        ("ix_trace_links_target", "trace_links"),
        ("ix_trace_links_source", "trace_links"),
        ("ix_trace_links_project_id", "trace_links"),
        ("ix_trace_links_organization_id", "trace_links"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("trace_links")
    for column in ("artifact_id", "project_id", "organization_id"):
        op.drop_index(f"ix_design_comments_{column}", table_name="design_comments")
    op.drop_table("design_comments")
    for column in ("artifact_id", "project_id", "organization_id"):
        op.drop_index(
            f"ix_architecture_decision_records_{column}", table_name="architecture_decision_records"
        )
    op.drop_table("architecture_decision_records")
    op.drop_index("ix_artifact_versions_artifact_id", table_name="artifact_versions")
    op.drop_index("ix_artifact_versions_organization_id", table_name="artifact_versions")
    op.drop_table("artifact_versions")
    for index in (
        "ix_artifacts_project_type_status",
        "ix_artifacts_source_artifact_id",
        "ix_artifacts_source_baseline_id",
        "ix_artifacts_project_id",
        "ix_artifacts_organization_id",
    ):
        op.drop_index(index, table_name="artifacts")
    op.drop_table("artifacts")
