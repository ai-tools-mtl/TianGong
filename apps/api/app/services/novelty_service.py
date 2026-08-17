"""新颖性评估服务（原设计 §2.3 定位「专业服务不做」，产品决策后落地为 AI 辅助评估）。

基于已检索的对比文件（Project.prior_art_refs.results，含 legal_status）+
项目核心章节文本，用 chat 强模型流式生成结构化 Markdown 评估报告：
总体风险 → 逐篇对比（重叠/区别/影响）→ 差异化建议 → 法律状态提示。

定位：AI 辅助参考，非法律意见——报告内与 system prompt 均明确声明。
持久化进 prior_art_refs["assessment"]（新检索会整体重置，评估随检索失效）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
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


def persist_assessment(db: Session, project: Project, *, content: str, model: str,
                       suggestions: list[dict] | None = None) -> None:
    """评估完成：写回 prior_art_refs.assessment（保留检索快照）。失败不阻断（尽力而为）。

    suggestions（T2 批4）：结构化差异化建议 [{section_key, text}]。None（解析失败
    fail-open）时不写该键——旧数据/失败态前端走手动兜底入口。
    """
    try:
        prior = dict(project.prior_art_refs or {})
        assessment = {
            "content": content,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
        }
        if suggestions:
            assessment["suggestions"] = suggestions
        prior["assessment"] = assessment
        project.prior_art_refs = prior
        db.commit()
    except Exception:  # noqa: BLE001 — 持久化失败不丢已流式给用户的报告
        db.rollback()


# ── T2 批4：建议结构化（lite 解析，fail-open）──────────────────────────────

_PARSE_SYSTEM = (
    "你是专利撰写顾问。从评估报告的「差异化撰写建议」段落中提取结构化修订建议。"
    "只输出 JSON，不要输出其他文字。"
)


def _build_parse_prompt(content: str) -> str:
    """解析 prompt：只关注「## 三、差异化撰写建议」段（报告四段结构固定，v1.2）。"""
    return (
        "以下是一份专利新颖性评估报告。请只解析其中「## 三、差异化撰写建议」段落，"
        "把每条建议整理为可直接执行的修订指令。\n"
        "每条：section_key（建议落点章节 key，从 ["
        + ", ".join(_CORE_SECTION_KEYS)
        + "] 中选最相关的一个）、text（≤200 字，动宾明确、自包含，可直接作为该章节"
        "的修订指令）。最多 4 条。\n"
        '只输出 JSON：{"suggestions": [{"section_key": "...", "text": "..."}]}\n\n'
        f"报告：\n{content[:6000]}\n\nJSON："
    )


def parse_suggestions(db: Session, *, user_id, content: str) -> list[dict] | None:
    """主报告完成后用 lite 模型解析结构化建议（done 事件前同步调用）。

    返回 [{section_key, text}]（白名单过滤后）；解析失败/无配置返回 None
    （fail-open，assessment 仅存 content）。最多 4 条。
    """
    from app.services.llm_config_service import resolve_lite_config

    try:
        llm_config = resolve_lite_config(db, user_id=user_id)
        if llm_config is None:
            return None
        llm = get_llm(llm_config)
        resp = llm.invoke([
            HumanMessage(content=_PARSE_SYSTEM),
            HumanMessage(content=_build_parse_prompt(content)),
        ])
        text = (getattr(resp, "content", "") or "").strip()
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        else:
            brace = re.search(r"\{.*\}", text, re.DOTALL)
            if brace:
                text = brace.group(0)
        data = json.loads(text)
        valid = set(_CORE_SECTION_KEYS)
        out = []
        for s in data.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            key = str(s.get("section_key", "")).strip()
            txt = str(s.get("text", "")).strip()
            # 白名单过滤：非法 section_key 丢弃该条（LLM 幻觉防护，spec §3.4）
            if key in valid and txt:
                out.append({"section_key": key, "text": txt[:200]})
        return out[:4] or None
    except Exception as e:  # noqa: BLE001 — fail-open 不阻断主流程
        logger.warning("novelty parse_suggestions 失败（fail-open）: %s", e)
        return None
