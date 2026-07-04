# project creation bootstraps main.tex and references.bib at v1

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Paper, Project, ProjectFile, ProjectPaper, User
from app.deps import get_app_settings, get_db

router = APIRouter()

DEFAULT_MAIN_TEX = r"""\documentclass{article}
\usepackage{hyperref}
\usepackage{cite}

\title{Untitled Research Draft}
\author{}
\date{\today}

\begin{document}
\maketitle

\section{Introduction}
Start writing here.

\bibliographystyle{plain}
\bibliography{references}

\end{document}
"""

class ProjectCreate(BaseModel):
    name: str
    description: str | None = None

async def ensure_dev_user(session: AsyncSession, settings: Settings) -> User:
    user = await session.get(User, UUID(settings.DEV_USER_ID))  
    if user is None:
        user = User(
            id=UUID(settings.DEV_USER_ID), email="dev@citepilot.local", display_name="Dev User"
        )
        session.add(user)
        await session.flush()

    return user


@router.get("")
async def list_projects(session: AsyncSession = Depends(get_db)) -> list[dict]:
    projects = (
        await session.execute(select(Project).order_by(Project.created_at.desc()))
    ).scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]

@router.post("")
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings)
) -> dict:
    user = await ensure_dev_user(session, settings)
    project = Project(user_id=user.id, name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    session.add_all(
        [
            ProjectFile(project_id=project.id, path="main.tex", content=DEFAULT_MAIN_TEX, version=1),
            ProjectFile(project_if=id, path="references.bib", content="", version=1),
        ]
    )

    await session.commit()
    return {"id": str(project.id), "name":project.name, "description": project.description}

@router.get("/{project_id}/papers")
async def list_project_papers(
    project_id: UUID, session: AsyncSession = Depends(get_db)
) -> list[dict]:
    rows = (
        await session.execute(
            select(Paper, ProjectPaper.bibtex_key)
            .join(ProjectPaper, ProjectPaper.paper_id == Paper.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(ProjectPaper.added_at.desc())
        )
    ).all()
    return [
        {
            "paper_id": str(paper.id),
            "bibtex_key": bibtex_key,
            "title": paper.title,
            "year": paper.publication_year,
            "cited_by_count": paper.cited_by_count,
            "is_stub": paper.is_stub,
        }
        for paper, bibtex_key in rows
    ]