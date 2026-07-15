"""add production authentication tables and user fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-15
"""

from alembic import op


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    op.execute("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
    op.execute("ALTER TABLE users ADD COLUMN last_login_at TIMESTAMPTZ")
    op.execute("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true")

    op.execute(
        """
        CREATE TABLE oauth_identities (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          provider TEXT NOT NULL,
          subject TEXT NOT NULL,
          email TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE(provider, subject)
        )
        """
    )
    op.execute("CREATE INDEX oauth_identities_user_idx ON oauth_identities (user_id)")

    op.execute(
        """
        CREATE TABLE user_sessions (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash TEXT NOT NULL UNIQUE,
          csrf_token_hash TEXT NOT NULL,
          expires_at TIMESTAMPTZ NOT NULL,
          last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          user_agent TEXT,
          ip_address TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX user_sessions_user_idx ON user_sessions (user_id)")
    op.execute("CREATE INDEX user_sessions_expiry_idx ON user_sessions (expires_at)")

    op.execute(
        """
        CREATE TABLE account_tokens (
          id UUID PRIMARY KEY,
          user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          purpose TEXT NOT NULL,
          token_hash TEXT NOT NULL UNIQUE,
          expires_at TIMESTAMPTZ NOT NULL,
          used_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX account_tokens_user_purpose_idx ON account_tokens (user_id, purpose)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS account_tokens")
    op.execute("DROP TABLE IF EXISTS user_sessions")
    op.execute("DROP TABLE IF EXISTS oauth_identities")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_hash")
