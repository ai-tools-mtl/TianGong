"""审查报告 PDF 导出服务：生成审查报告 HTML → weasyprint 渲染。

复用 pdf_service 的 HTML→PDF 基建（功能2），但 HTML 内容是审查报告而非交底书。
报告含：项目标题 + 总分 + 维度评分表 + 跨章节问题 + 按章节问题清单 + 趋势（多轮）。
"""
import urllib.parse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, ReviewRecord


def export_review_report(
    db: Session, *, project: Project, review: ReviewRecord
) -> bytes:
    """生成审查报告 PDF 字节流。"""
    # 取多轮趋势数据
    all_reviews = list(db.scalars(
        select(ReviewRecord)
        .where(ReviewRecord.project_id == project.id)
        .order_by(ReviewRecord.created_at.asc())
    ))

    html = _build_report_html(project, review, all_reviews)

    from weasyprint import HTML
    return HTML(string=html).write_pdf()


def _build_report_html(
    project: Project, review: ReviewRecord, all_reviews: list[ReviewRecord]
) -> str:
    """构建审查报告 HTML。"""
    parts = [
        f'<h1 class="report-title">交底书审查报告</h1>',
        f'<p class="project-name">{project.title}</p>',
        f'<p class="meta">第 {review.round} 轮审查 · 总分 {review.total_score}</p>',
    ]

    # 总分趋势（多轮）
    if len(all_reviews) >= 2:
        parts.append("<h2>分数趋势</h2><table class='data-table'><tr><th>轮次</th><th>总分</th></tr>")
        for r in all_reviews:
            parts.append(f"<tr><td>第 {r.round} 轮</td><td>{r.total_score}</td></tr>")
        parts.append("</table>")

    # 维度评分表
    parts.append("<h2>维度评分</h2>")
    parts.append("<table class='data-table'><tr><th>维度</th><th>权重</th><th>得分</th><th>依据</th></tr>")
    for d in review.dimension_scores:
        parts.append(
            f"<tr><td>{d['name']}</td><td>{d['weight'] * 100:.0f}%</td>"
            f"<td>{d['score']}</td><td>{d.get('evidence', '')}</td></tr>"
        )
    parts.append("</table>")

    # 维度改进建议
    if review.remaining_issues:
        parts.append("<h2>改进建议</h2><ul>")
        for issue in review.remaining_issues:
            parts.append(f"<li>{issue}</li>")
        parts.append("</ul>")

    # 跨章节一致性问题
    if review.cross_section_issues:
        parts.append("<h2>跨章节一致性问题</h2>")
        for issue in review.cross_section_issues:
            locations = "、".join(issue.get("location_sections", []))
            parts.append(
                f"<div class='issue-block'><p class='issue-type'>"
                f"[{_issue_type_label(issue.get('type', ''))}] 涉及：{locations}</p>"
                f"<p>{issue.get('description', '')}</p>"
                f"<p class='suggestion'>建议：{issue.get('suggestion', '')}</p></div>"
            )

    # 按章节问题定位
    if review.section_issues:
        parts.append("<h2>按章节问题定位</h2>")
        for sec in review.section_issues:
            parts.append(f"<h3>{sec['section_title']}</h3><ul>")
            for issue in sec.get("issues", []):
                parts.append(f"<li>{issue}</li>")
            parts.append("</ul>")

    body = "\n".join(parts)
    return _wrap_html(body)


def _issue_type_label(type_str: str) -> str:
    """问题类型中文标签。"""
    return {
        "terminology": "术语不一致",
        "reference": "引用错位",
        "contradiction": "逻辑矛盾",
        "other": "其他",
    }.get(type_str, type_str)


def _wrap_html(body: str) -> str:
    """套完整 HTML + CSS。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>审查报告</title>
<style>
  @page {{
    size: A4;
    margin: 2.5cm 2cm;
    @bottom-center {{ content: counter(page) " / " counter(pages); font-size: 9pt; color: #888; }}
  }}
  body {{
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    font-size: 11pt; line-height: 1.8; color: #1a1a1a;
  }}
  .report-title {{ font-size: 20pt; font-weight: 700; text-align: center; margin-bottom: 0.2cm; }}
  .project-name {{ font-size: 13pt; text-align: center; color: #555; margin-bottom: 0.1cm; }}
  .meta {{ font-size: 10pt; text-align: center; color: #888; margin-bottom: 1cm; }}
  h2 {{ font-size: 14pt; font-weight: 600; margin-top: 0.8cm; border-bottom: 1px solid #ddd; padding-bottom: 0.1cm; }}
  h3 {{ font-size: 12pt; font-weight: 600; margin-top: 0.5cm; }}
  .data-table {{ width: 100%; border-collapse: collapse; margin: 0.3cm 0; font-size: 10pt; }}
  .data-table th, .data-table td {{ border: 1px solid #999; padding: 0.15cm; text-align: left; }}
  .data-table th {{ background: #f0f0f0; }}
  .issue-block {{ margin: 0.3cm 0; padding: 0.2cm 0.3cm; background: #fafafa; border-left: 3px solid #d44; }}
  .issue-type {{ font-weight: 600; color: #d44; font-size: 10pt; }}
  .suggestion {{ color: #555; font-size: 10pt; }}
  ul {{ margin: 0.2cm 0; padding-left: 0.8cm; }}
  li {{ margin: 0.1cm 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
