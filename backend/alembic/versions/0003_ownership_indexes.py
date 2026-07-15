"""index user-owned project and agent lookups

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15
"""

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX projects_user_idx ON projects (user_id)")
    op.execute("CREATE INDEX agent_sessions_user_idx ON agent_sessions (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS agent_sessions_user_idx")
    op.execute("DROP INDEX IF EXISTS projects_user_idx")
