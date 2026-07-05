from fastapi import APIRouter

from app.api.routes import agent, files, graph, health, jobs, latex, papers, projects

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(files.router, tags=["files"])
api_router.include_router(papers.router, prefix="/papers", tags=["papers"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(graph.router, prefix="/graph", tags=["graph"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(latex.router, prefix="/latex", tags=["latex"])