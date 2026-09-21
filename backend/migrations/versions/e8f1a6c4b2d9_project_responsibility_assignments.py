"""add project responsibility assignments

Revision ID: e8f1a6c4b2d9
Revises: d4e7f9a2b6c1
Create Date: 2026-09-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "e8f1a6c4b2d9"
down_revision = "d4e7f9a2b6c1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "project_responsibility_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("responsibility_type", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("segregation_group", sa.String(length=64), nullable=True),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_until", sa.DateTime(), nullable=True),
        sa.Column("assigned_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_responsibility_assignments_organization_id",
        "project_responsibility_assignments",
        ["organization_id"],
    )
    op.create_index(
        "ix_project_responsibility_assignments_project_id",
        "project_responsibility_assignments",
        ["project_id"],
    )
    op.create_index(
        "ix_project_responsibility_assignments_user_id",
        "project_responsibility_assignments",
        ["user_id"],
    )
    op.create_index(
        "ix_project_responsibility_active",
        "project_responsibility_assignments",
        ["project_id", "responsibility_type", "is_primary", "effective_from"],
    )


def downgrade():
    op.drop_index("ix_project_responsibility_active", table_name="project_responsibility_assignments")
    op.drop_index(
        "ix_project_responsibility_assignments_user_id",
        table_name="project_responsibility_assignments",
    )
    op.drop_index(
        "ix_project_responsibility_assignments_project_id",
        table_name="project_responsibility_assignments",
    )
    op.drop_index(
        "ix_project_responsibility_assignments_organization_id",
        table_name="project_responsibility_assignments",
    )
    op.drop_table("project_responsibility_assignments")
