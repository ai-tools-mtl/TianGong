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
    """执行解析任务。"""
    job = db.get(ParseJob, job_id)
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


def _derive_template_name(source_path: str) -> str:
    base = os.path.basename(source_path)
    name = os.path.splitext(base)[0]
    return name[:100] if name else "上传的模板"
