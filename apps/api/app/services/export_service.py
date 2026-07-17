"""导出服务：Tiptap JSON → docx / Markdown（设计 13.5）。

存储改造(T3):图片从本地路径改为从 minio 取字节流。
"""

import io
import re
import uuid
from typing import Any

from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, Project, Section


def export_markdown(db: Session, *, project: Project) -> str:
    """导出为 Markdown 文本。"""
    sections = _get_ordered_sections(db, project)
    lines = [f"# {project.title}\n"]

    if project.metadata_:
        meta = project.metadata_
        if meta.get("inventors"):
            lines.append(f"**发明人**：{', '.join(meta['inventors'])}\n")
        if meta.get("applicant"):
            lines.append(f"**申请人**：{meta['applicant']}\n")

    for s in sections:
        lines.append(f"\n## {s.title}\n")
        if s.content:
            lines.append(_tiptap_to_markdown(s.content))
        lines.append("")
    return "\n".join(lines)


def export_docx(db: Session, *, project: Project) -> bytes:
    """导出为 .docx 字节。"""
    doc = Document()
    doc.add_heading(project.title, level=0)

    if project.metadata_:
        meta = project.metadata_
        info_parts = []
        if meta.get("inventors"):
            info_parts.append(f"发明人：{', '.join(meta['inventors'])}")
        if meta.get("applicant"):
            info_parts.append(f"申请人：{meta['applicant']}")
        if meta.get("disclosure_date"):
            info_parts.append(f"日期：{meta['disclosure_date']}")
        if info_parts:
            doc.add_paragraph(" | ".join(info_parts))

    sections = _get_ordered_sections(db, project)
    for s in sections:
        doc.add_heading(s.title, level=1)
        if s.content:
            _render_tiptap_to_docx(doc, s.content, db)
        else:
            doc.add_paragraph("（待填写）")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _get_ordered_sections(db: Session, project: Project) -> list[Section]:
    return list(db.scalars(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    ))


def _tiptap_to_markdown(doc_json: dict) -> str:
    """Tiptap JSON → Markdown 纯文本。"""
    parts: list[str] = []

    def walk(node: Any):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "text":
                text = node.get("text", "")
                marks = node.get("marks", [])
                if any(m.get("type") == "bold" for m in marks):
                    text = f"**{text}**"
                parts.append(text)
            elif ntype == "paragraph":
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n\n")
            elif ntype == "heading":
                level = node.get("attrs", {}).get("level", 2)
                parts.append(f"\n{'#' * level} ")
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n\n")
            elif ntype == "image":
                src = node.get("attrs", {}).get("src", "")
                alt = node.get("attrs", {}).get("alt", "")
                parts.append(f"\n\n![{alt}]({src})\n\n")
            elif ntype in ("bulletList", "orderedList"):
                for child in node.get("content", []):
                    walk(child)
            elif ntype == "listItem":
                parts.append("- ")
                for child in node.get("content", []):
                    walk(child)
                parts.append("\n")
            else:
                for child in node.get("content", []):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc_json)
    return "".join(parts).strip()


def _render_tiptap_to_docx(doc: Document, doc_json: dict, db: Session) -> None:
    """把 Tiptap JSON 渲染到 python-docx Document。

    图片节点:src 形如 /api/v1/projects/{pid}/attachments/{aid}/file,
    从中提 attachment_id → 查 storage_path → 从 minio 取字节 → add_picture。
    图片缺失不阻断导出(try/except 兜底)。
    """
    def walk(node: Any):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "paragraph":
                texts = [_get_text(c) for c in node.get("content", [])]
                doc.add_paragraph("".join(texts))
            elif ntype == "heading":
                level = node.get("attrs", {}).get("level", 2)
                texts = [_get_text(c) for c in node.get("content", [])]
                doc.add_heading("".join(texts), level=min(level, 3))
            elif ntype == "image":
                src = node.get("attrs", {}).get("src", "")
                alt = node.get("attrs", {}).get("alt", "")
                buf = _fetch_image_bytes(db, src)
                if buf:
                    try:
                        doc.add_picture(io.BytesIO(buf))
                    except Exception:
                        pass  # 图片损坏不阻断导出
                doc.add_paragraph(alt)
            elif ntype in ("bulletList", "orderedList"):
                style = "List Bullet" if ntype == "bulletList" else "List Number"
                for item in node.get("content", []):
                    if item.get("type") == "listItem":
                        texts = [_get_text(c) for c in item.get("content", [])]
                        doc.add_paragraph("".join(texts), style=style)
            else:
                for child in node.get("content", []):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc_json)


# 匹配附件下载 URL 里的 attachment_id(UUID)
_ATT_URL_RE = re.compile(r"/attachments/([0-9a-fA-F-]{36})/file")


def _fetch_image_bytes(db: Session, src: str) -> bytes | None:
    """从 Tiptap image src 反查 attachment,从 minio 取图片字节。失败返回 None。"""
    if not src:
        return None
    m = _ATT_URL_RE.search(src)
    if not m:
        return None
    try:
        att_id = uuid.UUID(m.group(1))
    except ValueError:
        return None
    att = db.get(Attachment, att_id)
    if att is None or not att.storage_path:
        return None
    try:
        from app.core.storage import get_storage

        return get_storage().get("personal", att.storage_path)
    except Exception:
        return None


def _get_text(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    return ""
