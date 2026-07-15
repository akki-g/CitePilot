# project creation bootstraps main.tex and references.bib at v1

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_owned_project, require_verified_user
from app.db.models import Paper, Project, ProjectFile, ProjectPaper, User
from app.deps import get_db

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
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

@router.get("")
async def list_projects(
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> list[dict]:
    projects = (
        await session.execute(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(Project.created_at.desc())
        )
    ).scalars().all()

    return [
        {
            "id": str(p.id),
            "name": p.name,
            # fix: description was missing from the list response the frontend renders
            "description": p.description,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]

# fix: was a plain @router.post("") — creation should return 201, not 200
@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> dict:
    project = Project(user_id=user.id, name=body.name, description=body.description)
    session.add(project)
    await session.flush()
    session.add_all(
        [
            ProjectFile(project_id=project.id, path="main.tex", content=DEFAULT_MAIN_TEX, version=1),
            # fix: was `project_if=id` — typo'd kwarg plus the `id` builtin; TypeError on every project create
            ProjectFile(project_id=project.id, path="references.bib", content="", version=1),
        ]
    )

    await session.commit()
    return {"id": str(project.id), "name":project.name, "description": project.description}

@router.get("/{project_id}/papers")
async def list_project_papers(
    project_id: UUID,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_user),
) -> list[dict]:
    await get_owned_project(session, user, project_id)
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
