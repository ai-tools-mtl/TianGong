"""导出服务：Tiptap JSON → docx / Markdown（设计 13.5）。"""

import io
from typing import Any

from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Section


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
            _render_tiptap_to_docx(doc, s.content)
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


def _render_tiptap_to_docx(doc: Document, doc_json: dict) -> None:
    """把 Tiptap JSON 渲染到 python-docx Document。"""
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
                import os
                if src and os.path.exists(src.split("?")[0]):
                    doc.add_picture(src.split("?")[0])
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


def _get_text(node: dict) -> str:
    if node.get("type") == "text":
        return node.get("text", "")
    return ""
