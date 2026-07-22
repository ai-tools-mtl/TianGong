"""模板解析服务：上传 → 解析 → 存 Template。

存储改造(计划 T3):文件从本地磁盘 uploads/ 改存 minio。
source_path 字段语义从"本地路径"变为"minio object key",
原始文件名通过 ParseJob.source_filename 单独保留(原从路径 basename 提取)。
"""

import os
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.storage import Storage
from app.models import ParseJob, Template

# ZIP 魔数（docx 本质是 ZIP 文件）
_ZIP_MAGIC = b"PK"


def validate_docx_bytes(file_bytes: bytes, filename: str) -> None:
    """校验上传文件是否为有效 docx。

    docx 文件本质是 ZIP，必须以 PK 魔数开头。DRM 加密文件不以 PK 开头。
    """
    if not file_bytes.startswith(_ZIP_MAGIC):
        # 检测是否 DRM 加密文件（华途/亿赛通/奇安信等常见 DRM 标识）
        if file_bytes[:4] == b"\x18DRM":
            raise ValidationError(
                f"「{filename}」是受 DRM 加密保护的文档，无法解析。"
                " 请先在文档安全系统中解密后再上传。",
            )
        raise ValidationError(
            f"「{filename}」不是有效的 .docx 文件。"
            " .docx 文件必须是 Office Open XML 格式（本质为 ZIP 压缩包），"
            " 请确认文件未被加密或损坏。",
        )


def _normalize_docx_namespaces(file_bytes: bytes) -> bytes:
    """将 docx 内 purl.oclc.org 命名空间替换为标准 schemas.openxmlformats.org。

    部分 Office 版本（尤其中文版）使用 http://purl.oclc.org/ooxml 作为替代命名空间，
    且其路径结构不含 2006/ 版本段。需要：
    1. domain 替换：purl.oclc.org/ooxml → schemas.openxmlformats.org
    2. 路径修正：在 officeDocument/relationships、wordprocessingml 等类型后插入 2006/
    """
    import zipfile
    from io import BytesIO

    OLD_DOMAIN = b"http://purl.oclc.org/ooxml/"
    NEW_DOMAIN = b"http://schemas.openxmlformats.org/"

    # purl 路径中缺少 2006/ 版本段的命名空间类型→标准路径修正
    _PATH_FIXES: list[tuple[bytes, bytes]] = [
        (b"officeDocument/relationships/", b"officeDocument/2006/relationships/"),
        (b"wordprocessingml/", b"wordprocessingml/2006/"),
    ]

    in_zip = zipfile.ZipFile(BytesIO(file_bytes), "r")
    changed = False
    items = []

    for item in in_zip.infolist():
        content = in_zip.read(item.filename)
        if item.filename.endswith(".xml") or item.filename.endswith(".rels"):
            if OLD_DOMAIN in content:
                content = content.replace(OLD_DOMAIN, NEW_DOMAIN)
                changed = True
            for old_path, new_path in _PATH_FIXES:
                if old_path in content and new_path not in content:
                    content = content.replace(old_path, new_path)
                    changed = True
        items.append((item, content))

    if not changed:
        in_zip.close()
        return file_bytes

    logger.info("检测到 purl.oclc.org 命名空间，正在归一化为 schemas.openxmlformats.org ...")
    out_buf = BytesIO()
    out_zip = zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED)
    for item, content in items:
        out_zip.writestr(item, content)
    in_zip.close()
    out_zip.close()
    return out_buf.getvalue()


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
        logger.info(f"解析任务 {job_id[:8]}... 开始从 minio 读取文件 {job.source_path}")
        doc_bytes = storage.get("personal", job.source_path)
        logger.info(f"解析任务 {job_id[:8]}... 文件读取完成，{len(doc_bytes)} 字节")

        # 归一化命名空间：部分 Office 版本用 purl.oclc.org，python-docx 只认 schemas.openxmlformats.org
        doc_bytes = _normalize_docx_namespaces(doc_bytes)

        try:
            doc = Document(BytesIO(doc_bytes))
        except KeyError as e:
            msg = str(e)
            if "officeDocument" in msg:
                raise ValidationError(
                    "文件无法作为 .docx 打开（缺少文档主体部件）。"
                    ' 请尝试在 Word 中打开文件，点击「文件 → 另存为」，'
                    ' 选择「Word 文档 (*.docx)」格式重新保存后再上传。',
                )
            raise ValidationError(f"文件解析失败：{msg}")
        logger.info(f"解析任务 {job_id[:8]}... python-docx 加载成功，开始提取结构")
        parsed = parse_docx(doc)
        logger.info(
            f"解析任务 {job_id[:8]}... 解析完成：{len(parsed.structure)} 个章节，"
            f"样式 {len(parsed.styles)} 个，编号 {'有' if parsed.numbering else '无'}",
        )

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
        logger.exception(f"解析任务 {job_id[:8]}... 失败：{e}")
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
