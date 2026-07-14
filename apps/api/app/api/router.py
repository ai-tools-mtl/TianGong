from fastapi import APIRouter

from app.api import ai, auth, export, health, projects, sections, templates, versions

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(templates.router)
api_router.include_router(sections.router)
api_router.include_router(ai.router)
api_router.include_router(versions.router)
api_router.include_router(export.router)
api_router.include_router(health.router)
