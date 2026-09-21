"""add durable agent leases and hash-bound verification evidence

Revision ID: c9e2f6a1d4b7
Revises: a2c4e6f8b0d1
Create Date: 2026-09-18 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op


revision = "c9e2f6a1d4b7"
down_revision = "a2c4e6f8b0d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("worker_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_agent_runs_worker_id", ["worker_id"], unique=False)
        batch.create_index("ix_agent_runs_lease_expires_at", ["lease_expires_at"], unique=False)

    with op.batch_alter_table("verification_runs") as batch:
        batch.add_column(sa.Column("change_set_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("waiver_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("waiver_expires_at", sa.DateTime(), nullable=True))

    # Existing verification rows predate hash binding. They are deliberately
    # invalidated rather than silently trusted; operators must re-run them.
    op.execute("UPDATE verification_runs SET change_set_hash = '' WHERE change_set_hash IS NULL")
    with op.batch_alter_table("verification_runs") as batch:
        batch.alter_column("change_set_hash", nullable=False)


def downgrade():
    with op.batch_alter_table("verification_runs") as batch:
        batch.drop_column("waiver_expires_at")
        batch.drop_column("waiver_reason")
        batch.drop_column("change_set_hash")
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_index("ix_agent_runs_lease_expires_at")
        batch.drop_index("ix_agent_runs_worker_id")
        batch.drop_column("attempt_count")
        batch.drop_column("lease_expires_at")
        batch.drop_column("worker_id")
