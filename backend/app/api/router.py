from fastapi import APIRouter, Depends

from app.api.routes import agent, auth, demo, files, graph, health, jobs, latex, papers, projects
from app.auth.dependencies import require_verified_user

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(demo.router, prefix="/demo", tags=["demo"])

authenticated = [Depends(require_verified_user)]
api_router.include_router(
    projects.router, prefix="/projects", tags=["projects"], dependencies=authenticated
)
api_router.include_router(files.router, tags=["files"], dependencies=authenticated)
api_router.include_router(
    papers.router, prefix="/papers", tags=["papers"], dependencies=authenticated
)
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"], dependencies=authenticated)
api_router.include_router(graph.router, prefix="/graph", tags=["graph"], dependencies=authenticated)
api_router.include_router(agent.router, prefix="/agent", tags=["agent"], dependencies=authenticated)
api_router.include_router(latex.router, prefix="/latex", tags=["latex"], dependencies=authenticated)
