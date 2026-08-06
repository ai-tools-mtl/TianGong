from fastapi import APIRouter

from app.api import (
    admin, ai, assistant, attachments, auth, export, figures, health, knowledge, memories, projects, review, sections, settings, share, skills, tags, templates, versions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
# /assistant/* ChatGPT 式初始化助手顶层会话（对话式新建）
api_router.include_router(assistant.router)
api_router.include_router(tags.router)
api_router.include_router(templates.router)
api_router.include_router(sections.router)
api_router.include_router(attachments.router)
# /sections/{id}/figures/* /figures/* AI 生成的专利附图（drawio 渲染）
api_router.include_router(figures.router)
api_router.include_router(ai.router)
api_router.include_router(versions.router)
api_router.include_router(export.router)
api_router.include_router(knowledge.router)
# /memories/* 用户长期记忆 CRUD（Task 13-14）
api_router.include_router(memories.router)
api_router.include_router(review.router)
api_router.include_router(share.router)
api_router.include_router(admin.router)
# /skills/* 用户个人技能域（Task 18：/skills/mine CRUD + /skills/visible）
api_router.include_router(skills.router)
# /settings/* 用户自定义配置域（从原 admin.py 剥离，refactor/admin-api-split）
api_router.include_router(settings.router)
api_router.include_router(health.router)
