"""模板解析服务：上传 → 解析 → 存 Template。

存储改造(计划 T3):文件从本地磁盘 uploads/ 改存 minio。
source_path 字段语义从"本地路径"变为"minio object key",
原始文件名通过 ParseJob.source_filename 单独保留(原从路径 basename 提取)。
"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.storage import Storage
from app.models import ParseJob, Template


def create_parse_job(
    db: Session, *, storage: Storage, user_id, filename: str, file_bytes: bytes,
    is_system: bool = False,
) -> ParseJob:
    """上传文件存 minio + 创建 ParseJob。

    is_system=True 时（admin 上传内置模板），run_parse_job 解析后会建出
    Template(is_system=True, status='draft', user_id=user_id)。默认 False（普通用户）。
    """
    object_key = f"templates/{user_id}/{uuid.uuid4()}.docx"
    storage.put(
        "personal", object_key, file_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    job = ParseJob(
        user_id=user_id, source_path=object_key,
        source_filename=filename, status="pending",
        is_system=is_system,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_parse_job(db: Session, *, storage: Storage, job_id: str) -> ParseJob:
    """执行解析任务。

    job_id 接受 str（API/BackgroundTasks 传字符串 id），内部转 UUID 再查。
    sqlite 的 Uuid 类型 bind_processor 不接受裸 str（会调 .hex 报错），
    所以必须先 uuid.UUID(job_id)；PostgreSQL 两种形式都行。
    """
    try:
        pk = uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise NotFoundError("解析任务不存在")
    job = db.get(ParseJob, pk)
    if job is None:
        raise NotFoundError("解析任务不存在")
    if job.status == "completed":
        return job

    job.status = "processing"
    db.commit()

    try:
        from io import BytesIO

        from docx import Document

        from app.parsing.docx_parser import parse_docx

        # 从 minio 取 docx 字节流喂给 python-docx
        doc_bytes = storage.get("personal", job.source_path)
        doc = Document(BytesIO(doc_bytes))
        parsed = parse_docx(doc)

        structure = parsed.structure or [
            {"id": "sec-1", "order": 1, "key": "custom", "title": "正文内容", "level": 1}
        ]

        template = Template(
            user_id=job.user_id,
            name=_derive_template_name(job.source_filename or job.source_path),
            source_filename=job.source_filename,
            structure=structure,
            styles=parsed.styles,
            numbering=parsed.numbering,
            # admin 上传的内置模板：is_system=True + status='draft'（待发布）
            is_system=job.is_system,
            status="draft" if job.is_system else "published",
        )
        db.add(template)
        db.flush()  # 触发 Python 端 default=uuid.uuid4，让 template.id 就位
        job.template_id = template.id
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        return job
    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)[:500]
        db.commit()
        db.refresh(job)
        return job


def run_parse_job_standalone(job_id: str) -> None:
    """供 BackgroundTasks 调用：自开 session 执行解析。

    BackgroundTasks 在响应返回后才执行，此时请求作用域的 session 已关闭，
    因此必须自己开一个独立 session（详见设计 P0 #6）。
    storage 用全局单例 get_storage()(minio client 无 session 状态)。
    """
    from app.core.database import SessionLocal
    from app.core.storage import get_storage

    db = SessionLocal()
    try:
        run_parse_job(db, storage=get_storage(), job_id=job_id)
    finally:
        db.close()


def recover_pending_jobs(stale_minutes: int = 10) -> int:
    """启动恢复扫描：重启后重入队两类孤儿任务。

    1) status="processing" —— 上次崩溃中断（崩溃时正在跑）。
    2) status="pending" 且 created_at 早于 stale_minutes 分钟前 —— 队列卡住。

    run_parse_job 自带幂等：若状态已是 completed 则跳过。
    返回重新入队的任务数。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.core.database import SessionLocal
    from app.core.storage import get_storage
    from app.models import ParseJob

    db = SessionLocal()
    storage = get_storage()
    count = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
        stmt = select(ParseJob).where(
            or_(
                ParseJob.status == "processing",
                (ParseJob.status == "pending") & (ParseJob.created_at < cutoff),
            )
        )
        jobs = list(db.scalars(stmt))
        for j in jobs:
            run_parse_job(db, storage=storage, job_id=str(j.id))
            count += 1
    finally:
        db.close()
    return count


def _derive_template_name(filename: str) -> str:
    """从原始文件名提模板名(去扩展名)。"""
    base = os.path.basename(filename)
    name = os.path.splitext(base)[0]
    return name[:100] if name else "上传的模板"
