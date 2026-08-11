"""PDF 导出服务：Tiptap JSON → HTML → weasyprint → PDF。

复用 export_service 的 Tiptap 遍历模式（walk + 按节点类型分派），
输出带语义标签的 HTML，再由 weasyprint 渲染为 PDF。

中文支持：CSS font-family 指定 Noto Sans CJK SC（Dockerfile 装 fonts-noto-cjk），
weasyprint 会自动 fallback 到系统其他中文字体。
"""
import base64
import io
import urllib.parse

from sqlalchemy.orm import Session

from app.models import Project
from app.services.export_service import _fetch_image_bytes, _get_ordered_sections


def export_pdf(db: Session, *, project: Project) -> bytes:
    """导出项目为 PDF 字节流。

    流程：取有序章节 → Tiptap JSON 转 HTML → 套页眉页脚 CSS → weasyprint 渲染。
    图片从 minio 取字节转 base64 data URI（与 markdown 导出同策略，自包含）。
    """
    sections = _get_ordered_sections(db, project)

    # 构建 HTML body
    body_parts = [f'<h1 class="doc-title">{project.title}</h1>']

    # 元信息（发明人/申请人/日期）
    if project.metadata_:
        meta = project.metadata_
        info_items = []
        if meta.get("inventors"):
            inventors = meta["inventors"]
            if isinstance(inventors, list):
                info_items.append(f"发明人：{'、'.join(inventors)}")
            else:
                info_items.append(f"发明人：{inventors}")
        if meta.get("applicant"):
            info_items.append(f"申请人：{meta['applicant']}")
        if meta.get("disclosure_date"):
            info_items.append(f"日期：{meta['disclosure_date']}")
        if info_items:
            body_parts.append(
                f'<p class="doc-meta">{" ｜ ".join(info_items)}</p>'
            )

    # 各章节
    for s in sections:
        body_parts.append(f'<h2 class="section-title">{s.title}</h2>')
        if s.content:
            body_parts.append(_tiptap_to_html(db, s.content))
        else:
            body_parts.append('<p class="placeholder">（待填写）</p>')

    html = _wrap_html(project.title, "\n".join(body_parts))

    # weasyprint 渲染（延迟 import：无系统库环境跳过）
    from weasyprint import HTML
    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes


def _tiptap_to_html(db: Session, doc_json: dict) -> str:
    """Tiptap JSON → HTML 片段（复用 export_service 的遍历模式）。

    支持节点：paragraph/heading/image/bulletList/orderedList/listItem/table。
    图片转 base64 data URI 自包含（与 markdown 导出同策略）。
    """
    parts: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "text":
                text = _escape_html(node.get("text", ""))
                marks = node.get("marks", [])
                if any(m.get("type") == "bold" for m in marks):
                    text = f"<strong>{text}</strong>"
                if any(m.get("type") == "italic" for m in marks):
                    text = f"<em>{text}</em>"
                parts.append(text)
            elif ntype == "paragraph":
                parts.append("<p>")
                for child in node.get("content", []):
                    walk(child)
                parts.append("</p>")
            elif ntype == "heading":
                level = node.get("attrs", {}).get("level", 2)
                level = min(max(level, 1), 6)  # HTML h1-h6
                parts.append(f"<h{level + 1}>")  # +1：h1 留给文档标题
                for child in node.get("content", []):
                    walk(child)
                parts.append(f"</h{level + 1}>")
            elif ntype == "image":
                src = node.get("attrs", {}).get("src", "")
                alt = node.get("attrs", {}).get("alt", "")
                img_bytes = _fetch_image_bytes(db, src)
                if img_bytes:
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    mime = "image/png"
                    if ".jp" in src:
                        mime = "image/jpeg"
                    elif ".gif" in src:
                        mime = "image/gif"
                    parts.append(f'<img src="data:{mime};base64,{b64}" alt="{_escape_html(alt)}" />')
                if alt:
                    parts.append(f"<figcaption>{_escape_html(alt)}</figcaption>")
            elif ntype in ("bulletList", "orderedList"):
                tag = "ul" if ntype == "bulletList" else "ol"
                parts.append(f"<{tag}>")
                for child in node.get("content", []):
                    walk(child)
                parts.append(f"</{tag}>")
            elif ntype == "listItem":
                parts.append("<li>")
                for child in node.get("content", []):
                    walk(child)
                parts.append("</li>")
            elif ntype == "table":
                parts.append('<table class="data-table">')
                for child in node.get("content", []):
                    walk(child)
                parts.append("</table>")
            elif ntype == "tableRow":
                parts.append("<tr>")
                for child in node.get("content", []):
                    walk(child)
                parts.append("</tr>")
            elif ntype in ("tableHeader", "tableCell"):
                tag = "th" if ntype == "tableHeader" else "td"
                parts.append(f"<{tag}>")
                for child in node.get("content", []):
                    walk(child)
                parts.append(f"</{tag}>")
            else:
                for child in node.get("content", []):
                    walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc_json)
    return "".join(parts)


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _wrap_html(title: str, body: str) -> str:
    """套完整 HTML 文档 + CSS 样式（页眉页脚 + 中文字体 + 表格样式）。"""
    escaped_title = _escape_html(title)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{escaped_title}</title>
<style>
  @page {{
    size: A4;
    margin: 2.5cm 2cm 2cm 2cm;
    @top-center {{
      content: "{escaped_title}";
      font-size: 9pt;
      color: #888;
    }}
    @bottom-center {{
      content: counter(page) " / " counter(pages);
      font-size: 9pt;
      color: #888;
    }}
  }}
  body {{
    font-family: "Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei",
                 "PingFang SC", "Hiragino Sans GB", sans-serif;
    font-size: 11pt;
    line-height: 1.8;
    color: #1a1a1a;
  }}
  .doc-title {{
    font-size: 20pt;
    font-weight: 700;
    text-align: center;
    margin: 0 0 0.5cm 0;
    padding-bottom: 0.3cm;
    border-bottom: 2px solid #1a1a1a;
  }}
  .doc-meta {{
    text-align: center;
    font-size: 10pt;
    color: #555;
    margin-bottom: 1cm;
  }}
  .section-title {{
    font-size: 14pt;
    font-weight: 600;
    margin-top: 0.8cm;
    margin-bottom: 0.3cm;
    padding-bottom: 0.1cm;
    border-bottom: 1px solid #ddd;
  }}
  h2 {{ font-size: 14pt; font-weight: 600; margin-top: 0.6cm; }}
  h3 {{ font-size: 12pt; font-weight: 600; margin-top: 0.4cm; }}
  p {{ margin: 0.3cm 0; text-indent: 0; }}
  ul, ol {{ margin: 0.3cm 0; padding-left: 0.8cm; }}
  li {{ margin: 0.1cm 0; }}
  img {{
    max-width: 100%;
    margin: 0.3cm auto;
    display: block;
  }}
  figcaption {{
    text-align: center;
    font-size: 9pt;
    color: #888;
    margin-top: 0.1cm;
  }}
  .data-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 0.4cm 0;
    font-size: 10pt;
  }}
  .data-table th, .data-table td {{
    border: 1px solid #999;
    padding: 0.15cm 0.2cm;
    text-align: left;
  }}
  .data-table th {{
    background: #f0f0f0;
    font-weight: 600;
  }}
  .placeholder {{
    color: #aaa;
    font-style: italic;
  }}
</style>
</head>
<body>
{body}
</body>
</html>"""
