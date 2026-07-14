"""模板解析服务：上传 → 解析 → 存 Template。"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import ParseJob, Template


def create_parse_job(
    db: Session, *, user_id, filename: str, file_bytes: bytes, upload_dir: str
) -> ParseJob:
    """保存上传文件，创建 ParseJob。"""
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4()}.docx"
    file_path = os.path.join(upload_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(file_bytes)

    job = ParseJob(user_id=user_id, source_path=file_path, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def run_parse_job(db: Session, job_id: str, upload_dir: str) -> ParseJob:
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
        from docx import Document

        from app.parsing.docx_parser import parse_docx

        doc = Document(job.source_path)
        parsed = parse_docx(doc)

        structure = parsed.structure or [
            {"id": "sec-1", "order": 1, "key": "custom", "title": "正文内容", "level": 1}
        ]

        template = Template(
            user_id=job.user_id,
            name=_derive_template_name(job.source_path),
            source_filename=os.path.basename(job.source_path),
            structure=structure,
            styles=parsed.styles,
            numbering=parsed.numbering,
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


def run_parse_job_standalone(job_id: str, upload_dir: str) -> None:
    """供 BackgroundTasks 调用：自开 session 执行解析。

    BackgroundTasks 在响应返回后才执行，此时请求作用域的 session 已关闭，
    因此必须自己开一个独立 session（详见设计 P0 #6）。
    """
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        run_parse_job(db, job_id=job_id, upload_dir=upload_dir)
    finally:
        db.close()


def recover_pending_jobs(upload_dir: str, stale_minutes: int = 10) -> int:
    """启动恢复扫描：重启后重入队两类孤儿任务。

    1) status="processing" —— 上次崩溃中断（崩溃时正在跑）。
    2) status="pending" 且 created_at 早于 stale_minutes 分钟前 —— 队列卡住。

    run_parse_job 自带幂等：若状态已是 completed 则跳过。
    返回重新入队的任务数。
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import or_, select

    from app.core.database import SessionLocal
    from app.models import ParseJob

    db = SessionLocal()
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
            run_parse_job(db, str(j.id), upload_dir)
            count += 1
    finally:
        db.close()
    return count


def _derive_template_name(source_path: str) -> str:
    base = os.path.basename(source_path)
    name = os.path.splitext(base)[0]
    return name[:100] if name else "上传的模板"
