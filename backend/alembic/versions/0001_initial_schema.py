"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
from alembic import op

# fix: migration file was missing — created verbatim from guide 01 (the migration IS the schema spec)
# Alembic revision identifiers. `down_revision = None` means this is the first migration.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Each string is one SQL statement. asyncpg/Alembic is happiest when statements are executed separately.
TABLES = [
    """
    CREATE TABLE users (
      id UUID PRIMARY KEY,
      email TEXT UNIQUE,
      display_name TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE projects (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL REFERENCES users(id),
      name TEXT NOT NULL,
      description TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE project_files (
      id UUID PRIMARY KEY,
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      path TEXT NOT NULL,
      content TEXT NOT NULL,
      version INT NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(project_id, path)
    )
    """,
    """
    CREATE TABLE file_versions (
      id UUID PRIMARY KEY,
      file_id UUID NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
      version INT NOT NULL,
      content TEXT NOT NULL,
      created_by TEXT NOT NULL DEFAULT 'user',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(file_id, version)
    )
    """,
    """
    CREATE TABLE papers (
      id UUID PRIMARY KEY,
      openalex_id TEXT UNIQUE,
      semantic_scholar_id TEXT UNIQUE,
      doi TEXT UNIQUE,
      title TEXT,
      abstract TEXT,
      publication_year INT,
      publication_date DATE,
      venue_name TEXT,
      source_name TEXT,
      cited_by_count INT DEFAULT 0,
      url TEXT,
      pdf_url TEXT,
      is_stub BOOLEAN NOT NULL DEFAULT false,
      metadata JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE authors (
      id UUID PRIMARY KEY,
      openalex_id TEXT UNIQUE,
      semantic_scholar_id TEXT UNIQUE,
      name TEXT NOT NULL,
      metadata JSONB NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE paper_authors (
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      author_id UUID NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
      author_order INT,
      PRIMARY KEY (paper_id, author_id)
    )
    """,
    """
    CREATE TABLE citations (
      citing_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      cited_paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      source TEXT NOT NULL DEFAULT 'openalex',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (citing_paper_id, cited_paper_id)
    )
    """,
    """
    CREATE TABLE concepts (
      id UUID PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      type TEXT NOT NULL DEFAULT 'concept',
      metadata JSONB NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE paper_concepts (
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      concept_id UUID NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
      score FLOAT,
      source TEXT NOT NULL DEFAULT 'openalex',
      PRIMARY KEY (paper_id, concept_id)
    )
    """,
    """
    CREATE TABLE paper_chunks (
      id UUID PRIMARY KEY,
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      chunk_index INT NOT NULL,
      section TEXT,
      text TEXT NOT NULL,
      token_count INT,
      embedding vector(1536),
      metadata JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      UNIQUE(paper_id, chunk_index)
    )
    """,
    """
    CREATE TABLE project_papers (
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
      bibtex_key TEXT NOT NULL,
      added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, paper_id),
      UNIQUE(project_id, bibtex_key)
    )
    """,
    """
    CREATE TABLE agent_sessions (
      id UUID PRIMARY KEY,
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      user_id UUID NOT NULL REFERENCES users(id),
      title TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE agent_messages (
      id UUID PRIMARY KEY,
      session_id UUID NOT NULL REFERENCES agent_sessions(id) ON DELETE CASCADE,
      role TEXT NOT NULL,
      content TEXT NOT NULL,
      metadata JSONB NOT NULL DEFAULT '{}',
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE tool_calls (
      id UUID PRIMARY KEY,
      session_id UUID REFERENCES agent_sessions(id) ON DELETE CASCADE,
      tool_name TEXT NOT NULL,
      arguments JSONB NOT NULL DEFAULT '{}',
      result JSONB,
      status TEXT NOT NULL DEFAULT 'pending',
      error TEXT,
      started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      completed_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE jobs (
      id UUID PRIMARY KEY,
      job_type TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'queued',
      queue_job_id TEXT,
      input JSONB NOT NULL DEFAULT '{}',
      result JSONB,
      error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE latex_compilations (
      id UUID PRIMARY KEY,
      project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      status TEXT NOT NULL DEFAULT 'queued',
      main_file_path TEXT NOT NULL DEFAULT 'main.tex',
      pdf_path TEXT,
      logs TEXT,
      error TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      completed_at TIMESTAMPTZ
    )
    """,
]

# Indexes live outside CREATE TABLE because they optimize query access patterns.
INDEXES = [
    "CREATE INDEX citations_cited_idx ON citations (cited_paper_id)",
    "CREATE INDEX agent_messages_session_idx ON agent_messages (session_id, created_at)",
    """
    CREATE INDEX paper_chunks_embedding_hnsw_idx
    ON paper_chunks USING hnsw (embedding vector_cosine_ops)
    """,
]

# Drop order is reverse dependency order: children first, parents last.
TABLE_NAMES = [
    "latex_compilations", "jobs", "tool_calls", "agent_messages", "agent_sessions",
    "project_papers", "paper_chunks", "paper_concepts", "concepts", "citations",
    "paper_authors", "authors", "papers", "file_versions", "project_files",
    "projects", "users",
]


def upgrade() -> None:
    # pgvector extension must exist before creating `embedding vector(1536)`.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # Create all tables in parent-before-child order.
    for statement in TABLES:
        op.execute(statement)
    # Create indexes after tables exist.
    for statement in INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Drop tables in dependency-safe order. CASCADE cleans up constraints/indexes.
    for table in TABLE_NAMES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
