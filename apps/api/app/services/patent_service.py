"""专利检索服务：调 client → 写 Project.prior_art_refs → 返回结果。

Project.prior_art_refs 是 JSONB 字段（MVP 设计 §3.2 预留），存检索结果快照。
本服务提供 search（调 client + 持久化）和 get（读已存）两个操作。
"""

import uuid as uuid_mod

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Project
from app.services.patent_client import search_patents


def search_prior_art(
    db: Session, *, user_id, project_id: str, query: str
) -> dict:
    """检索现有技术专利并持久化到 project.prior_art_refs。

    返回 {query, results, source, saved_to: project_id}；source 为
    "live"/"mock"（检索源降级标记，前端据此提示示例数据）。
    """
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    if not query.strip():
        raise ValidationError("检索关键词不能为空")

    results, source = search_patents(query)

    # 持久化检索结果快照到 prior_art_refs（source 供前端展示降级提示）
    project.prior_art_refs = {
        "query": query,
        "results": results,
        "source": source,
    }
    db.commit()

    return {"query": query, "results": results, "source": source, "saved_to": str(pid)}


def get_prior_art(db: Session, *, user_id, project_id: str) -> dict | None:
    """读取已存的检索结果。无检索记录返回 None。"""
    try:
        pid = uuid_mod.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")

    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    return project.prior_art_refs
