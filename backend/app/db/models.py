import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector

# sql alchemy column/index/constraint building blocks used by the ORM classes 
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)

# postgres SQL specific UUID and JSONB column types
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# collects tables metadata so Alembic can see all ORM tables
class Base(DeclarativeBase):
    """Declarative base imported by Alembic env.py"""

# avoids repeating uuid primary key column def on every table
def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

# postgres sets time not python
def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

# minimal owner identity for the MVP local auth
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str | None] = mapped_column(Text, unique=True)
    display_name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()


class OAuthIdentity(Base):
    """An external identity linked to one CitePilot account."""

    __tablename__ = "oauth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject"),
        Index("oauth_identities_user_idx", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class UserSession(Base):
    """Server-side login session; the browser only receives the opaque token."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("user_sessions_user_idx", "user_id"),
        Index("user_sessions_expiry_idx", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()


class AccountToken(Base):
    """Single-use, expiring account action token (currently email verification)."""

    __tablename__ = "account_tokens"
    __table_args__ = (Index("account_tokens_user_purpose_idx", "user_id", "purpose"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_col()


# a research writing workspace owned by one user
class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("projects_user_idx", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    files: Mapped[list["ProjectFile"]] = relationship(back_populates="project")

# the current content for each file path in a project
class ProjectFile(Base):
    __tablename__ = "project_files"
    __table_args__ = (UniqueConstraint("project_id", "path"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    project: Mapped[Project] = relationship(back_populates="files")


# snapshots only explicity saves and agent patches; autosaves update current content without bloating history
class FileVersion(Base):
    __tablename__ = "file_versions"
    __table_args__ = (UniqueConstraint("file_id", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(Text, nullable=False, default="user")  # 'user' | 'agent'
    created_at: Mapped[datetime] = created_at_col()


# canonical paper metadata
# is_stub=True means the paper exists mainly to support citation edges
class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(Text, unique=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(Text, unique=True)
    doi: Mapped[str | None] = mapped_column(Text, unique=True)  # ALWAYS normalized before write
    title: Mapped[str | None] = mapped_column(Text)  # nullable: stubs have no title yet
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[date | None] = mapped_column(Date)
    venue_name: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    cited_by_count: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    is_stub: Mapped[bool] = mapped_column(nullable=False, default=False)
    paper_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


# normalized authors plus many-to-many authorship/owner
class Author(Base):
    __tablename__ = "authors"

    id: Mapped[uuid.UUID] = uuid_pk()
    openalex_id: Mapped[str | None] = mapped_column(Text, unique=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    author_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class PaperAuthor(Base):
    __tablename__ = "paper_authors"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("authors.id", ondelete="CASCADE"), primary_key=True
    )
    author_order: Mapped[int | None] = mapped_column(Integer)


# directed paper-to-paper edge in postgres; Neo4j mirrors this for traversal
class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (Index("citations_cited_idx", "cited_paper_id"),)  # reverse lookups

    citing_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    cited_paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, default="openalex")
    created_at: Mapped[datetime] = created_at_col()

# structured topics/methods/datasets later used by graph retrieval
class Concept(Base):
    __tablename__ = "concepts"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="concept")
    concept_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)


class PaperConcept(Base):
    __tablename__ = "paper_concepts"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="openalex")


# text plus pg vestor embedding, for mvp its one title_abstract chunck per paper
class PaperChunk(Base):
    __tablename__ = "paper_chunks"
    __table_args__ = (UniqueConstraint("paper_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str | None] = mapped_column(Text)  # 'title_abstract' for MVP
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))  # dim frozen by migration
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()


# papers the use has added to a project with the stable BibTeX key
class ProjectPaper(Base):
    __tablename__ = "project_papers"
    __table_args__ = (UniqueConstraint("project_id", "bibtex_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    bibtex_key: Mapped[str] = mapped_column(Text, nullable=False)
    added_at: Mapped[datetime] = created_at_col()

# conversational state for the in app agent 
class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (Index("agent_sessions_user_idx", "user_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AgentMessage(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (Index("agent_messages_session_idx", "session_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'assistant' | 'tool'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()


# audit log for every tool call invocation and result/error
class ToolCallRecord(Base):
    __tablename__ = "tool_calls"

    id: Mapped[uuid.UUID] = uuid_pk()
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE")
    )
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)  # truncated to <= 4 KB before storage
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

# durable UI-visible status for arq background work
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    queue_job_id: Mapped[str | None] = mapped_column(Text)  # arq job id linkage
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


# tracks each compliation attempt, logs, error, and pdf artifact path
class LatexCompilation(Base):
    __tablename__ = "latex_compilations"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    main_file_path: Mapped[str] = mapped_column(Text, nullable=False, default="main.tex")
    pdf_path: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
