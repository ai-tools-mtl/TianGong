from fastapi import APIRouter

from app.api import (
    admin, ai, attachments, auth, export, health, knowledge, projects, review, sections, settings, share, tags, templates, versions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(tags.router)
api_router.include_router(templates.router)
api_router.include_router(sections.router)
api_router.include_router(attachments.router)
api_router.include_router(ai.router)
api_router.include_router(versions.router)
api_router.include_router(export.router)
api_router.include_router(knowledge.router)
api_router.include_router(review.router)
api_router.include_router(share.router)
api_router.include_router(admin.router)
# /settings/* 用户 BYOK 域（从原 admin.py 剥离，refactor/admin-api-split）
api_router.include_router(settings.router)
api_router.include_router(health.router)
