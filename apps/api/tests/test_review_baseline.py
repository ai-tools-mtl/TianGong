"""审查评分回归基线测试（优化计划批次 5）。

LLM 全 mock（_score_dimension 打桩固定分数），验证基线生成/比对/漂移判定逻辑。
"""

import json
from unittest.mock import patch

import pytest

from app.eval import review_baseline as rb
from app.services.seed_service import ensure_default_rubric


def _mock_score(value: int):
    """固定分数的 _score_dimension 桩（evidence/suggestion 随便给）。"""
    return lambda criterion, sections, llm_config: (value, "e", "s")


def test_baseline_generated_on_first_run(db_session, tmp_path):
    """无基线文件 → 生成基线并标记 updated（exit 语义：生成即成功）。"""
    ensure_default_rubric(db_session)
    bp = tmp_path / "baseline.json"

    with patch("app.services.review_service._score_dimension", _mock_score(80)):
        report = rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    assert report.updated is True
    assert report.passed is False  # 首跑无比对语义
    data = json.loads(bp.read_text(encoding="utf-8"))
    assert set(data["samples"]) == {"disclosure_good", "disclosure_mediocre"}
    # 全部维度分数 = 桩值
    for dims in data["samples"].values():
        assert dims and all(v == 80 for v in dims.values())
    assert data["meta"]["tolerance"] == rb.DEFAULT_TOLERANCE


def test_baseline_compare_within_tolerance(db_session, tmp_path):
    """与基线偏差在容差内 → passed=True。"""
    ensure_default_rubric(db_session)
    bp = tmp_path / "baseline.json"
    with patch("app.services.review_service._score_dimension", _mock_score(80)):
        rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    # 当前分数漂 +10（容差 15 内）
    with patch("app.services.review_service._score_dimension", _mock_score(90)):
        report = rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    assert report.updated is False
    assert report.passed is True
    assert all(r["diff"] == 10 for r in report.results)


def test_baseline_drift_detected(db_session, tmp_path):
    """偏差超容差 → passed=False（CLI 退出非零的依据）。"""
    ensure_default_rubric(db_session)
    bp = tmp_path / "baseline.json"
    with patch("app.services.review_service._score_dimension", _mock_score(80)):
        rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    with patch("app.services.review_service._score_dimension", _mock_score(50)):  # -30 漂移
        report = rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    assert report.passed is False
    assert report.max_abs_diff == 30  # 绝对值口径（报告展示用）


def test_baseline_update_overwrites(db_session, tmp_path):
    """--update 重建基线（有意变更后的人工确认流程）。"""
    ensure_default_rubric(db_session)
    bp = tmp_path / "baseline.json"
    with patch("app.services.review_service._score_dimension", _mock_score(80)):
        rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    with patch("app.services.review_service._score_dimension", _mock_score(70)):
        report = rb.run_baseline(db_session, _fake_cfg(), update=True, baseline_path=bp)

    assert report.updated is True
    data = json.loads(bp.read_text(encoding="utf-8"))
    for dims in data["samples"].values():
        assert all(v == 70 for v in dims.values())


def test_render_report_contains_drift_marker(db_session, tmp_path):
    """报告文本：漂移维度有 ❌ 标记 + 总结行（人读 CLI 输出的契约）。"""
    ensure_default_rubric(db_session)
    bp = tmp_path / "baseline.json"
    with patch("app.services.review_service._score_dimension", _mock_score(80)):
        rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)

    with patch("app.services.review_service._score_dimension", _mock_score(40)):
        report = rb.run_baseline(db_session, _fake_cfg(), baseline_path=bp)
    text = rb.render_report(report)
    assert "漂移" in text
    assert "审查评分回归基线报告" in text


def _fake_cfg():
    from app.services.llm_config_service import ResolvedChatConfig
    return ResolvedChatConfig(
        base_url="http://test", api_key="sk-test", model="test-model", source="global",
    )
