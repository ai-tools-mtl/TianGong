"""项目术语表服务（T2 spec §3.3）：CRUD + AI 抽取候选 + 一致性检查。

术语表是机器可检查的强约束（variants 可扫描），与 WritingProfile.terminology
（用户级自由文本软偏好）并存——项目级优先（spec §3.3.4）。

LLM 调用约定（docs/llm-usage.md）：extract / check 的 LLM 路均走
resolve_lite_config（轻量），降级模式照抄 outline_extractor 先例
（invoke + 容错 JSON 解析，失败返回空结果不抛错）。
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Project, ProjectTerm, Section
from app.services.llm_config_service import resolve_lite_config

# 抽取输入总额上限（字符）——控制 token（spec §3.3.2）
_EXTRACT_TOTAL_LIMIT = 12000


def _get_owned_project(db: Session, user_id, project_id: str) -> Project:
    import uuid as uuid_mod
    try:
        pid = uuid_mod.UUID(str(project_id))
    except ValueError:
        raise NotFoundError("项目不存在")
    project = db.get(Project, pid)
    if project is None or project.user_id != user_id:
        raise NotFoundError("项目不存在")
    return project


def _get_owned_term(db: Session, user_id, term_id: str) -> ProjectTerm:
    import uuid as uuid_mod
    try:
        tid = uuid_mod.UUID(str(term_id))
    except ValueError:
        raise NotFoundError("术语不存在")
    term = db.get(ProjectTerm, tid)
    if term is None:
        raise NotFoundError("术语不存在")
    # 归属校验链：term → project → owner（越权 404，spec §3.3.2）
    project = db.get(Project, term.project_id)
    if project is None or project.user_id != user_id:
        raise NotFoundError("术语不存在")
    return term


def list_terms(db: Session, *, user_id, project_id: str) -> list[ProjectTerm]:
    project = _get_owned_project(db, user_id, project_id)
    return list(db.scalars(
        select(ProjectTerm)
        .where(ProjectTerm.project_id == project.id)
        .order_by(ProjectTerm.term)
    ))


def create_term(db: Session, *, user_id, project_id: str, term: str,
                definition: str | None, variants: list[str], source: str = "manual") -> ProjectTerm:
    project = _get_owned_project(db, user_id, project_id)
    exists = db.scalar(select(ProjectTerm).where(
        ProjectTerm.project_id == project.id, ProjectTerm.term == term))
    if exists:
        raise ConflictError("该术语已存在")
    row = ProjectTerm(
        project_id=project.id, term=term, definition=definition,
        variants=variants or [], enabled=True, source=source,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_term(db: Session, *, user_id, term_id: str,
                term: str | None = None, definition: str | None = None,
                variants: list[str] | None = None, enabled: bool | None = None) -> ProjectTerm:
    row = _get_owned_term(db, user_id, term_id)
    if term is not None and term != row.term:
        dup = db.scalar(select(ProjectTerm).where(
            ProjectTerm.project_id == row.project_id, ProjectTerm.term == term))
        if dup:
            raise ConflictError("该术语已存在")
        row.term = term
    if definition is not None:
        row.definition = definition
    if variants is not None:
        row.variants = variants
    if enabled is not None:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def delete_term(db: Session, *, user_id, term_id: str) -> None:
    row = _get_owned_term(db, user_id, term_id)
    db.delete(row)
    db.commit()


# ── 规则扫描（纯函数，零 token）──────────────────────────────────────────────

def scan_variants(
    terms: list[dict], section_texts: dict[str, str], key_map: dict[str, str],
) -> list[dict]:
    """对每个 enabled 术语的每个 variant 做逐章节纯文本精确子串扫描。

    误报定性（spec §3.3.2 / D10）：子串扫描必然命中复合词（变体「单元」会命中
    「存储单元」）——结果是提示性质，由用户结合上下文判断；可选 llm_verify
    复核剔除。不做中文词边界精确匹配（复杂度不成比例）。

    terms: [{term, variants, enabled?}]；section_texts: {标题: 文本}；
    key_map: {标题: key}。返回 [{term, variant, section_keys, count}]。
    """
    issues: list[dict] = []
    for t in terms:
        if not t.get("enabled", True):
            continue
        for variant in (t.get("variants") or []):
            if not variant:
                continue
            section_keys: list[str] = []
            count = 0
            for title, text in section_texts.items():
                n = text.count(variant)
                if n > 0:
                    count += n
                    key = key_map.get(title)
                    if key and key not in section_keys:
                        section_keys.append(key)
            if count > 0:
                issues.append({
                    "term": t["term"], "variant": variant,
                    "section_keys": section_keys, "count": count,
                })
    return issues


# ── 章节文本装配 ─────────────────────────────────────────────────────────────

def _load_section_texts(db: Session, project_id) -> tuple[dict[str, str], dict[str, str]]:
    """返回 ({标题: 纯文本}, {标题: key})。"""
    from app.services.summary_service import _extract_text
    sections = list(db.scalars(
        select(Section).where(Section.project_id == project_id).order_by(Section.order)
    ))
    texts = {s.title: _extract_text(s.content) if s.content else "" for s in sections}
    key_map = {s.title: s.key for s in sections}
    return texts, key_map


def _parse_llm_json(raw) -> dict:
    """容错解析 LLM 输出 JSON（照抄 outline_extractor._parse_outline_json 模式：
    去 ```json 围栏 / 抓首个 {...} / 失败返回 {}）。"""
    text = raw.strip() if isinstance(raw, str) else ""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# ── AI 抽取候选（不入库，返回候选列表）───────────────────────────────────────

_EXTRACT_SYSTEM = (
    "你是专利交底书术语审计专家。从给定章节正文中识别应统一的核心技术术语："
    "同一概念在正文中有多种表述时，推荐标准术语并列出观察到的变体。"
    "只输出 JSON，不要输出其他文字。"
)


def extract_candidates(db: Session, *, user_id, project_id: str) -> dict:
    """AI 抽取候选术语（lite）。返回 {candidates: [...], warning?: str}。

    候选不入库——前端勾选后逐条 POST /terms 入库（source='ai'）。
    LLM 失败降级空候选 + warning（不阻断，照抄 outline_extractor 先例）。
    """
    project = _get_owned_project(db, user_id, project_id)
    texts, _ = _load_section_texts(db, project.id)
    if not any(t.strip() for t in texts.values()):
        raise ConflictError("项目尚无已写章节，无法抽取术语")

    llm_config = resolve_lite_config(db, user_id=user_id)
    if llm_config is None:
        raise ValidationError("未配置 LLM，无法抽取术语")

    corpus = "\n\n".join(f"## {title}\n{text[:3000]}" for title, text in texts.items())
    corpus = corpus[:_EXTRACT_TOTAL_LIMIT]
    prompt = (
        "请从以下专利交底书章节正文中抽取需要统一的核心技术术语，"
        "按重要性降序返回最多 15 条。每条：term（推荐标准术语）、"
        "definition（简短定义，可空）、variants（正文中观察到的其它表述）、"
        "occurrences（标准术语+变体合计出现次数，整数）。\n"
        '只输出 JSON：{"candidates": [{"term": "...", "definition": "...", '
        '"variants": ["..."], "occurrences": 0}]}\n\n'
        f"章节正文：\n{corpus}\n\nJSON："
    )
    try:
        llm = get_llm(llm_config)
        resp = llm.invoke([
            SystemMessage(content=_EXTRACT_SYSTEM),
            HumanMessage(content=prompt),
        ])
        data = _parse_llm_json(getattr(resp, "content", ""))
        if not data:
            # 输出完全解析不出 JSON = LLM 失效降级（区别于「无候选」的正常空列表）
            return {"candidates": [], "warning": "术语抽取结果解析失败，请重试"}
        candidates = data.get("candidates") or []
        cleaned = [
            {
                "term": str(c.get("term", "")).strip()[:100],
                "definition": str(c.get("definition", "")).strip() or None,
                "variants": [str(v).strip() for v in (c.get("variants") or []) if str(v).strip()][:10],
                "occurrences": c.get("occurrences") if isinstance(c.get("occurrences"), int) else 0,
            }
            for c in candidates if isinstance(c, dict) and str(c.get("term", "")).strip()
        ]
        return {"candidates": cleaned[:15]}
    except Exception as e:  # noqa: BLE001 — 降级不阻断
        logger.warning("terms extract 失败降级空候选: %s", e)
        return {"candidates": [], "warning": f"术语抽取失败：{e}"}


# ── 一致性检查（规则 + LLM 双路）────────────────────────────────────────────

_DRIFT_SYSTEM = (
    "你是专利交底书术语一致性专家。给定章节正文与现有术语表，"
    "找出「同一概念有多种说法但均未登记进术语表」的漂移表述。只输出 JSON。"
)


def check_consistency(db: Session, *, user_id, project_id: str, llm_verify: bool = False) -> dict:
    """一致性检查：规则路（零 token）+ LLM 路（表外漂移，fail-open）+ 可选复核。

    术语表为空 → 直接空结果（不调 LLM）。LLM 失败 → llm_suggestions 空 + warning。
    """
    project = _get_owned_project(db, user_id, project_id)
    terms = list(db.scalars(
        select(ProjectTerm).where(ProjectTerm.project_id == project.id)))
    if not terms:
        return {"rule_issues": [], "llm_suggestions": []}

    texts, key_map = _load_section_texts(db, project.id)
    term_dicts = [{"term": t.term, "variants": t.variants or [], "enabled": t.enabled}
                  for t in terms]
    rule_issues = scan_variants(term_dicts, texts, key_map)

    result: dict = {"rule_issues": rule_issues, "llm_suggestions": []}

    llm_config = resolve_lite_config(db, user_id=user_id)
    if llm_config is None:
        # 无 LLM：规则路照常返回（确定性部分不受影响）
        result["warning"] = "未配置 LLM，跳过漂移检测"
        return result

    corpus = "\n\n".join(f"## {title}\n{text[:2000]}" for title, text in texts.items())
    corpus = corpus[:_EXTRACT_TOTAL_LIMIT]
    manifest = "；".join(
        f"{t.term}（禁用：{'、'.join(t.variants or [])}）" if t.variants else t.term
        for t in terms if t.enabled
    )

    try:
        llm = get_llm(llm_config)
        # ① 表外漂移检测
        drift_prompt = (
            "现有术语表：\n" + manifest + "\n\n"
            "请检查以下章节正文，找出同一概念的多种不同说法（均未在术语表中登记）。"
            "每条：concept（建议登记的标准术语）、variants（观察到的其它说法）、"
            "section_keys（涉及章节 key，从下方清单取值）。\n"
            f"章节 key 清单：{'; '.join(f'{k}: {t}' for t, k in key_map.items())}\n"
            '只输出 JSON：{"drifts": [{"concept": "...", "variants": ["..."], '
            '"section_keys": ["..."]}]}\n\n'
            f"章节正文：\n{corpus}\n\nJSON："
        )
        resp = llm.invoke([
            SystemMessage(content=_DRIFT_SYSTEM),
            HumanMessage(content=drift_prompt),
        ])
        data = _parse_llm_json(getattr(resp, "content", ""))
        if not data:
            # 解析失败 = LLM 路降级（规则路结果已在上方返回，不受影响）
            result["warning"] = "漂移检测结果解析失败，请重试"
            return result
        valid_keys = set(key_map.values())
        drifts = []
        for d in data.get("drifts") or []:
            if not isinstance(d, dict) or not str(d.get("concept", "")).strip():
                continue
            drifts.append({
                "concept": str(d["concept"]).strip()[:100],
                "variants": [str(v).strip() for v in (d.get("variants") or []) if str(v).strip()][:10],
                "section_keys": [k for k in (d.get("section_keys") or []) if k in valid_keys],
            })
        result["llm_suggestions"] = drifts[:10]

        # ② 可选 LLM 复核规则路误报（默认关；开启时逐条判真阳性）
        if llm_verify and rule_issues:
            result["rule_issues"] = _verify_rule_issues(
                llm, rule_issues, corpus, manifest)
    except Exception as e:  # noqa: BLE001 — fail-open
        logger.warning("terms check LLM 路失败降级: %s", e)
        result["warning"] = f"漂移检测失败：{e}"

    return result


def _verify_rule_issues(llm, rule_issues: list[dict], corpus: str, manifest: str) -> list[dict]:
    """LLM 复核规则路命中（复合词误报剔除）：每条加 verified 字段。"""
    items = [
        {"index": i, "term": r["term"], "variant": r["variant"]}
        for i, r in enumerate(rule_issues)
    ]
    prompt = (
        "现有术语表：\n" + manifest + "\n\n"
        "以下是子串匹配到的疑似术语误用（term 为标准术语，variant 为疑似误用的词）。"
        "请逐条结合正文上下文判断：该 variant 在正文中是否真的是 term 的误用"
        "（而非其它名词的组成部分，如「存储单元」中的「单元」不属于「处理模块」的误用）。\n"
        f"待判定列表：{json.dumps(items, ensure_ascii=False)}\n"
        '只输出 JSON：{"results": [{"index": 0, "verified": true}]}\n\n'
        f"章节正文：\n{corpus}\n\nJSON："
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    data = _parse_llm_json(getattr(resp, "content", ""))
    verdicts = {r.get("index"): bool(r.get("verified"))
                for r in (data.get("results") or []) if isinstance(r, dict)}
    out = []
    for i, r in enumerate(rule_issues):
        # 未获判定的条目保守保留（verified 缺省 True——宁多提示）
        r2 = dict(r)
        r2["verified"] = verdicts.get(i, True)
        out.append(r2)
    return out
