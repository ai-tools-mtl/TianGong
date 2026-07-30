"""[P2] eval 评估样本测试。

样本含「好输出」和「坏输出」对——好输出符合 S1-S5 改进点（高分），
坏输出违反改进点（低分）。让 eval 能对比证明提示词改进的效果。
样本基于真实交底书抽象，脱敏处理。
"""


def test_samples_have_good_and_bad_pairs():
    """[P2] 样本集含好/坏输出对（每个指标至少一对）。"""
    from app.eval.samples import SAMPLES

    assert len(SAMPLES) >= 6  # 3 指标 × 好坏各一
    # 每个指标都有好样本和坏样本
    metrics_present = {s.metric_key for s in SAMPLES}
    assert {"structure", "consistency", "conformity"}.issubset(metrics_present)
    # 至少有期望高分和期望低分的样本
    has_good = any(s.expected_min >= 70 for s in SAMPLES)
    has_bad = any(s.expected_max <= 50 for s in SAMPLES)
    assert has_good, "缺少好输出样本（期望高分）"
    assert has_bad, "缺少坏输出样本（期望低分）"


def test_sample_structure_fields():
    """[P2] 每个样本有 metric_key/output/expected_min/expected_max 字段。"""
    from app.eval.samples import SAMPLES

    for s in SAMPLES:
        assert s.metric_key in ("structure", "consistency", "conformity")
        assert s.output and len(s.output) > 10, "样本输出不应过短"
        assert 0 <= s.expected_min <= s.expected_max <= 100
        assert s.label in ("good", "bad"), f"样本 label 应为 good/bad，实际: {s.label}"


def test_structure_bad_sample_misses_dimensions():
    """[P2] structure 坏样本应明显缺失维度（对应 S1 激活 completion_criteria 要解决的问题）。"""
    from app.eval.samples import SAMPLES

    bad_structure = [s for s in SAMPLES if s.metric_key == "structure" and s.label == "bad"]
    assert bad_structure, "缺少 structure 的坏样本"
    # 坏样本期望低分（缺失维度）
    assert bad_structure[0].expected_max <= 50


def test_consistency_bad_sample_ignores_context():
    """[P2] consistency 坏样本应未呼应前文（对应 S3-1 一致性约束要解决的问题）。"""
    from app.eval.samples import SAMPLES

    bad_consistency = [s for s in SAMPLES if s.metric_key == "consistency" and s.label == "bad"]
    assert bad_consistency, "缺少 consistency 的坏样本"
    # consistency 样本必须有 context（前文）
    assert bad_consistency[0].context, "consistency 样本必须有前文 context"
