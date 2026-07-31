# apps/api/tests/test_brief_dimensions.py
"""brief_dimensions 维度覆盖率计算单测（纯函数，无 DB/LLM 依赖）。

覆盖 compute_coverage 的各种维度组合 + 对齐达标判定 + ready 阈值。
"""
from app.ai.brief_dimensions import (
    ALIGNMENT_DIMENSIONS,
    CORE_DIMENSIONS,
    Coverage,
    compute_coverage,
    dimension_title,
    is_core,
)


def _outline(**filled):
    """构造 outline：filled 传 key->content，未传的 key 为空。

    返回 {key: {title, content}} 结构（兼容 compute_coverage 的输入）。
    """
    return {
        k: {"title": dimension_title(k), "content": v}
        for k, v in filled.items()
    }


def test_empty_outline_not_ready():
    """空 outline：核心维度全缺，未就绪。"""
    cov = compute_coverage({})
    assert cov.ready is False
    assert cov.core_filled == (0, 5)
    assert set(cov.missing) == set(CORE_DIMENSIONS)
    assert cov.aligned is True  # 全空不算未对齐


def test_none_outline_not_ready():
    """None outline 同样未就绪。"""
    cov = compute_coverage(None)
    assert cov.ready is False
    assert cov.core_filled == (0, 5)


def test_all_core_filled_ready():
    """核心 5 维全填满 + 对齐达标 → ready。"""
    cov = compute_coverage(_outline(
        field="新能源电池领域",
        background="现有技术散热差",
        problem="需要提升散热",
        solution="用新型液冷结构",
        effect="散热效率提升",
    ))
    assert cov.ready is True
    assert cov.core_filled == (5, 5)
    assert cov.missing == []
    assert cov.aligned is True


def test_missing_one_core_not_ready():
    """缺一个核心维度 → 未就绪，missing 包含该维度。"""
    cov = compute_coverage(_outline(
        field="新能源",
        background="散热差",
        problem="要提升散热",
        solution="液冷结构",
        # 缺 effect
    ))
    assert cov.ready is False
    assert cov.core_filled == (4, 5)
    assert "effect" in cov.missing
    # 对齐三方有一方(effect)为 0，不检查对齐，仍算 aligned
    assert cov.aligned is True


def test_edge_dimensions_do_not_affect_ready():
    """边缘维度(name/drawings/embodiment)填不填都不影响 ready。"""
    cov = compute_coverage(_outline(
        field="领域", background="缺点", problem="问题", solution="方案", effect="效果",
        name="发明名称", drawings="图1", embodiment="实施例",
    ))
    assert cov.ready is True
    assert cov.core_filled == (5, 5)


def test_alignment_misalignment_blocks_ready():
    """核心 5 维全填，但对齐三方条数偏差过大 → 未就绪。

    background 1 条、problem 1 条、effect 3 条（偏差 2 > ALIGN_TOLERANCE=1）。
    """
    cov = compute_coverage(_outline(
        field="领域",
        background="现有技术散热差；成本高",  # 2 条（分号切分）
        problem="需要提升散热",  # 1 条
        solution="液冷结构",
        effect="① 散热提升\n② 成本降低\n③ 寿命延长",  # 3 条（换行+序号切分，取较大者）
    ))
    assert cov.core_filled == (5, 5)
    assert cov.aligned is False
    assert cov.ready is False  # 对齐未达标


def test_alignment_within_tolerance_ready():
    """核心 5 维全填，对齐三方偏差 ≤ 1 → 就绪。"""
    cov = compute_coverage(_outline(
        field="领域",
        background="缺点1；缺点2",  # 2 条
        problem="问题1",  # 1 条
        solution="方案",
        effect="效果1；效果2",  # 2 条，偏差 2-1=1 ≤ 容差
    ))
    assert cov.aligned is True
    assert cov.ready is True


def test_to_dict_serializable():
    """to_dict 输出可 JSON 序列化（塞进 SSE done 事件）。"""
    import json
    cov = compute_coverage(_outline(field="x"))
    d = cov.to_dict()
    # core_filled 在 to_dict 里转成 list（tuple 不可 JSON 序列化）
    assert d["core_filled"] == [1, 5]
    json.dumps(d)  # 不抛异常即可


def test_is_core_and_dimension_title():
    """辅助函数：is_core + dimension_title。"""
    assert is_core("field") is True
    assert is_core("name") is False
    assert dimension_title("field") == "技术领域"
    assert dimension_title("unknown_key") == "unknown_key"


def test_evidence_type_preserved_but_irrelevant_to_coverage():
    """outline 带 evidence_type 字段不影响覆盖率计算（覆盖率只看 content 非空）。"""
    cov = compute_coverage({
        "field": {"title": "技术领域", "content": "新能源", "evidence_type": "实测"},
        "background": {"title": "背景技术", "content": "散热差"},
        "problem": {"title": "问题", "content": "提升散热"},
        "solution": {"title": "方案", "content": "液冷"},
        "effect": {"title": "效果", "content": "散热好", "evidence_type": "复杂度"},
    })
    assert cov.ready is True
