"""新颖性评估服务（原设计 §2.3 定位「专业服务不做」，产品决策后落地为 AI 辅助评估）。

基于已检索的对比文件（Project.prior_art_refs.results，含 legal_status）+
项目核心章节文本，用 chat 强模型流式生成结构化 Markdown 评估报告：
总体风险 → 逐篇对比（重叠/区别/影响）→ 差异化建议 → 法律状态提示。

定位：AI 辅助参考，非法律意见——报告内与 system prompt 均明确声明。
持久化进 prior_art_refs["assessment"]（新检索会整体重置，评估随检索失效）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models import Project, Section

# 参与评估的章节 key（按重要性排序）：技术方案核心四要素 + 背景兜底
_CORE_SECTION_KEYS = ("problem", "solution", "effect", "background", "summary")

# 单章截断与总预算（字符）：防止长交底书撑爆上下文
_PER_SECTION_LIMIT = 1500
_TOTAL_LIMIT = 6000

_SYSTEM_PROMPT = (
    "你是资深专利代理人，擅长现有技术检索分析与新颖性评估。"
    "请基于给定的「本交底书核心内容」与「检索到的对比文件」输出评估报告。"
    "要求：只依据给定材料，不臆测；区别点要具体到技术特征而非空话；"
    "报告是 AI 辅助参考，不构成法律意见，结尾无需免责声明（由产品侧展示）。"
)


def load_assessment_context(db: Session, *, user_id, project_id: str) -> tuple[Project, list[dict], str]:
    """加载评估上下文：项目（归属校验）+ 对比文件 + 核心章节文本。

    Raises:
        NotFoundError: 项目不存在 / 非 owner。
        ConflictError: 尚未检索过对比文件（先 /patents/search）或核心章节全空。
    """
    import uuid as _uuid

    try:
        pid = _uuid.UUID(project_id)
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")

    prior = project.prior_art_refs or {}
    results = prior.get("results") or []
    if not results:
        raise ConflictError("尚未检索对比文件，请先执行专利检索")

    sections = list(db.scalars(
        select(Section).where(Section.project_id == project.id).order_by(Section.order)
    ))
    by_key = {s.key: s for s in sections if s.content}
    picked: list[Section] = []
    for key in _CORE_SECTION_KEYS:
        if key in by_key and all(p.key != key for p in picked):
            picked.append(by_key[key])
    # 兜底：核心 key 都没有内容时取前几个有内容的章节
    if not picked:
        picked = [s for s in sections if s.content][:4]

    parts: list[str] = []
    total = 0
    for s in picked:
        text = _extract_text(s.content)[:_PER_SECTION_LIMIT]
        if not text:
            continue
        if total + len(text) > _TOTAL_LIMIT:
            text = text[: max(0, _TOTAL_LIMIT - total)]
        if not text:
            break
        parts.append(f"### {s.title}\n{text}")
        total += len(text)
    sections_text = "\n\n".join(parts)
    if not sections_text:
        raise ConflictError("项目章节尚无内容，先完成交底书核心章节再评估")
    return project, results, sections_text


def _extract_text(content) -> str:
    """Tiptap JSON → 纯文本（只取 text 节点，忽略图片/图注等）。"""
    if isinstance(content, str):
        return content
    out: list[str] = []

    def _walk(node):
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str):
                out.append(node["text"])
            for child in node.get("content", []) or []:
                _walk(child)
        elif isinstance(node, list):
            for child in node:
                _walk(child)

    _walk(content)
    return "\n".join(t for t in out if t.strip())


def build_assessment_messages(results: list[dict], sections_text: str) -> list:
    """构造评估消息（纯函数，便于测试）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    refs = []
    for r in results:
        refs.append(
            f"- 专利号：{r.get('patent_number', '未知')}｜标题：{r.get('title', '')}\n"
            f"  申请人：{r.get('applicant', '')}｜公开日：{r.get('publication_date', '')}"
            f"｜法律状态：{r.get('legal_status', '未知')}\n"
            f"  摘要：{r.get('abstract', '')}"
        )

    user = (
        "## 本交底书核心内容\n" + sections_text + "\n\n"
        "## 检索到的对比文件\n" + "\n".join(refs) + "\n\n"
        "## 输出要求\n"
        "请输出 Markdown 格式的新颖性评估报告，结构固定为：\n"
        "## 一、总体新颖性风险\n（高/中/低 + 一段核心理由）\n"
        "## 二、逐篇对比分析\n（每篇对比文件一节：### 专利号 标题（法律状态）；"
        "重叠点 / 区别点 / 对新颖性与创造性的影响 各一条）\n"
        "## 三、差异化撰写建议\n（如何突出区别特征、规避风险的 2-4 条具体建议）\n"
        "## 四、法律状态提示\n（基于各对比文件法律状态给出注意点，如失效专利可作背景引用）"
    )
    return [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user)]


def persist_assessment(db: Session, project: Project, *, content: str, model: str) -> None:
    """评估完成：写回 prior_art_refs.assessment（保留检索快照）。失败不阻断（尽力而为）。"""
    try:
        prior = dict(project.prior_art_refs or {})
        prior["assessment"] = {
            "content": content,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
        }
        project.prior_art_refs = prior
        db.commit()
    except Exception:  # noqa: BLE001 — 持久化失败不丢已流式给用户的报告
        db.rollback()
