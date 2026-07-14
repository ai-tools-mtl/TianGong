"""归档编排服务。"""

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project
from app.rag.archiver import archive_project


def archive(db: Session, *, user_id, project_id: str) -> dict:
    """归档项目到知识库。"""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    chunk_count = archive_project(db, project=project, user_id=user_id)
    return {"project_id": str(project.id), "chunks": chunk_count, "status": "archived"}
