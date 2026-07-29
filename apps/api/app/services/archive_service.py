"""归档编排服务。"""

import uuid

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Project
from app.rag.archiver import archive_project, run_archive_embed_standalone


def archive(db: Session, *, user_id, project_id: str, background_tasks: BackgroundTasks = None) -> dict:
    """归档项目到知识库。

    异步化：archive_project 请求内落库（status=archiving）+ 返回；
    若传入 background_tasks，则后台 spawn run_archive_embed_standalone 做向量化。
    """
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    chunk_count = archive_project(db, project=project, user_id=user_id)
    # 后台向量化（status: archiving → archived）
    if background_tasks is not None:
        background_tasks.add_task(run_archive_embed_standalone, str(project.id))
    return {"project_id": str(project.id), "chunks": chunk_count, "status": project.status}
