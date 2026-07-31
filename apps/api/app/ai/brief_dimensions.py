"""项目初始化 brief 维度定义 + 覆盖率计算。

这是 init 助手「维度覆盖率」的**唯一权威数据源**：
- 哪些章节 key 参与 ready 判断（核心维度 vs 边缘维度）
- 覆盖率/缺失项怎么算
- ready 阈值（核心维度全覆盖 + 缺点/问题/效果对齐偏差 ≤ 阈值）

借鉴 patent-disclosure-pro skill 的「五方强制对齐」思想
（references/section-alignment.md：技术背景难题→缺点→技术问题→有益效果→保护点
数量必须一致、语义对应）——把生成期的对齐规则前置成 init 阶段的 ready 判据，
让 [READY_TO_CREATE] 从「LLM 直觉自吐标记字符串」升级为「基于维度覆盖率的可靠判断」。

章节 key 从 seed_service.DEFAULT_STRUCTURE 派生（与 outline_extractor._OUTLINE_KEYS
同源），不另起炉灶。前端 outline-preview.tsx 的 CHAPTERS 是这份的镜像
（注释标明对齐关系，单一来源是这里）。

设计取舍：
- 核心 vs 边缘：name/drawings/embodiment 不卡 ready（drawings/embodiment 往往要
  到生成期才能补全，init 阶段强行要求会逼用户编造）。
- 对齐检查是「软」的：缺点/问题/效果条数偏差 ≤ ALIGN_TOLERANCE 即放行，不强制
  精确等数（init 阶段信息粒度粗，精确等数太苛刻）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.seed_service import DEFAULT_STRUCTURE

# ── 维度分级 ──────────────────────────────────────────────────────────
# 核心维度：init 阶段必须收集到才能 ready（直接决定后续 8 章生成质量）。
# 取自 patent-disclosure-pro 五方对齐的前四方（保护点属生成期，不进 init）：
#   field 技术领域 / background 现有技术缺点 / problem 技术问题 / solution 方案 / effect 有益效果
CORE_DIMENSIONS: list[str] = ["field", "background", "problem", "solution", "effect"]

# 边缘维度：参与展示（OutlinePreview 右栏），但不卡 ready 判断。
# drawings/embodiment 通常生成期才补全；name 是衍生信息（从 field+solution 即可提炼）。
EDGE_DIMENSIONS: list[str] = ["name", "drawings", "embodiment"]

# 参与「对齐检查」的三方：缺点 / 问题 / 效果。
# patent-disclosure-pro 五方对齐的核心可量化指标——这三方数量应大致一致。
ALIGNMENT_DIMENSIONS: list[str] = ["background", "problem", "effect"]

# 对齐容差：三方条数最大差异超过此值视为「未对齐」。
# init 阶段信息粒度粗，容差取 1（允许例如 缺点2/问题2/效果1）。
ALIGN_TOLERANCE: int = 1

# 所有维度（核心在前，边缘在后，与 DEFAULT_STRUCTURE 顺序无关——这里按重要性排）。
ALL_DIMENSIONS: list[str] = CORE_DIMENSIONS + EDGE_DIMENSIONS

# key → 中文标题（从 DEFAULT_STRUCTURE 派生，单一来源）。
# 前端 OutlinePreview 的 CHAPTERS 镜像这份。
_TITLE_BY_KEY: dict[str, str] = {s["key"]: s["title"] for s in DEFAULT_STRUCTURE}


def dimension_title(key: str) -> str:
    """取维度中文名（未知 key 返回 key 本身）。前端镜像也用此命名。"""
    return _TITLE_BY_KEY.get(key, key)


def is_core(key: str) -> bool:
    return key in CORE_DIMENSIONS


@dataclass
class Coverage:
    """覆盖率计算结果。

    Attributes:
        covered: 已收集到信息的核心维度 key 列表。
        missing: 未收集到信息的核心维度 key 列表（供前端提示「还需补充：…」）。
        ready: 是否达到可创建项目的阈值（核心全覆盖 + 对齐达标）。
        core_filled: 核心维度已填数 / 总数（如 3/5）。
        aligned: 缺点/问题/效果是否对齐（条数偏差 ≤ ALIGN_TOLERANCE）。
        alignment_detail: 对齐细节 {dim: 条数}，供调试/前端可选展示。
    """
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    ready: bool = False
    core_filled: tuple[int, int] = (0, len(CORE_DIMENSIONS))
    aligned: bool = True
    alignment_detail: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为可塞进 SSE done 事件 / draft_outline 的结构。"""
        return {
            "covered": self.covered,
            "missing": self.missing,
            "ready": self.ready,
            "core_filled": list(self.core_filled),
            "aligned": self.aligned,
            "alignment_detail": self.alignment_detail,
        }


def _count_points(content: str) -> int:
    """粗估某维度内容的「条数」用于对齐检查。

    用启发式计数：按分号/换行/序号（①②③/1.2.3./(1)(2)）切分，取较大者。
    空内容返回 0；无明确分点但有实质内容算 1 条。

    这是对齐检查的「软」估算——init 阶段不要求精确，只要三方数量别差太远。
    """
    import re

    text = (content or "").strip()
    if not text:
        return 0
    # 序号分点：①②③、1. 2.、(1) (2)、一、二、
    numbered = re.split(r"[①②③④⑤⑥⑦⑧⑨⑩]|\d+[.、)]|[（(]\d+[)）]|[一二三四五六七八九十]、", text)
    numbered = [s for s in numbered if s and s.strip()]
    # 分号/换行分点
    by_sep = re.split(r"[；;\n]", text)
    by_sep = [s for s in by_sep if s and s.strip()]
    # 取较大者，但至少 1（有实质内容）
    points = max(len(numbered), len(by_sep))
    return max(points, 1)


def compute_coverage(outline: dict | None) -> Coverage:
    """根据 draft_outline 计算维度覆盖率。

    Args:
        outline: {key: {"title": str, "content": str, ...}}，来自 outline_extractor。
            None / 空 dict 视为全空。

    Returns:
        Coverage 对象。ready 判定：核心 5 维 content 全非空 AND 对齐达标。
    """
    if not outline:
        return Coverage(missing=list(CORE_DIMENSIONS), aligned=True, alignment_detail={})

    covered: list[str] = []
    missing: list[str] = []
    for key in CORE_DIMENSIONS:
        content = (outline.get(key) or {}).get("content", "")
        if content and content.strip():
            covered.append(key)
        else:
            missing.append(key)

    # 对齐检查：缺点/问题/效果三方条数偏差
    detail: dict[str, int] = {}
    counts: list[int] = []
    for key in ALIGNMENT_DIMENSIONS:
        content = (outline.get(key) or {}).get("content", "")
        n = _count_points(content)
        detail[key] = n
        counts.append(n)
    # 只在三方都有内容时才检查对齐（某方为 0 说明还没收集到，不算「未对齐」）
    nonzero = [c for c in counts if c > 0]
    aligned = True
    if len(nonzero) == len(ALIGNMENT_DIMENSIONS):
        aligned = (max(nonzero) - min(nonzero)) <= ALIGN_TOLERANCE

    core_filled = (len(covered), len(CORE_DIMENSIONS))
    all_core_covered = len(missing) == 0
    ready = all_core_covered and aligned

    return Coverage(
        covered=covered,
        missing=missing,
        ready=ready,
        core_filled=core_filled,
        aligned=aligned,
        alignment_detail=detail,
    )
