"""[P2] eval judge 测试 —— LLM-as-judge 给章节输出打分。

无参考评估：不对比「期望输出」，只评生成输出本身的质量维度。
judge 用项目已有的 get_llm + 结构化输出（复用 S5 DimensionScore 模式）。

评估指标（对应 S1–S5 的改进点，让 eval 能证明效果）：
- structure（结构完整性）：是否覆盖 completion_criteria 维度 → 验证 S1
- consistency（前文一致性）：是否沿用术语/呼应前文 → 验证 S3-1
- conformity（章节规范度）：是否符合专利表述范式 → 验证 S4-1

测试策略：mock get_llm 的 judge 调用，验证 judge 的 prompt 装配 + 结果解析正确。
不测 judge 的「打分准不准」（那依赖真实 LLM，属集成测试，非单测范畴）。
"""
import pytest


def test_eval_metrics_defined():
    """[P2] 三个评估指标已定义（structure/consistency/conformity）。"""
    from app.eval.metrics import METRICS

    assert "structure" in METRICS
    assert "consistency" in METRICS
    assert "conformity" in METRICS
    # 每个指标有 judge prompt 模板
    for key, metric in METRICS.items():
        assert metric.judge_prompt, f"{key} 缺 judge_prompt"
        assert metric.description, f"{key} 缺 description"


def test_judge_returns_score_and_reason(db_session, monkeypatch):
    """[P2] judge 返回 (score, reason)，score 为 0-100 整数。"""
    from app.eval import judge as judge_mod
    from app.services.llm_config_service import ResolvedChatConfig

    # mock judge 内部的 LLM 调用，返回固定评分
    monkeypatch.setattr(judge_mod, "_call_judge_llm",
                        lambda metric_key, output, llm_config, context=None: (85, "结构完整，覆盖三个维度"))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = judge_mod.judge(
        metric_key="structure",
        output="某发明的技术方案：包括 A 模块、B 模块...",
        llm_config=config,
    )
    assert result.score == 85
    assert "结构完整" in result.reason


def test_judge_score_clamped_to_range(db_session, monkeypatch):
    """[P2] judge 返回的 score 被 clamp 到 [0, 100]（防御 LLM 越界输出）。"""
    from app.eval import judge as judge_mod
    from app.services.llm_config_service import ResolvedChatConfig

    # mock 返回越界分数
    monkeypatch.setattr(judge_mod, "_call_judge_llm",
                        lambda metric_key, output, llm_config, context=None: (150, "极好"))

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = judge_mod.judge(metric_key="structure", output="x", llm_config=config)
    assert result.score == 100  # clamp 上界


def test_judge_unknown_metric_raises():
    """[P2] 未知指标抛 ValueError。"""
    import pytest as _pytest
    from app.eval import judge as judge_mod
    from app.services.llm_config_service import ResolvedChatConfig

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    with _pytest.raises(ValueError):
        judge_mod.judge(metric_key="nonexistent", output="x", llm_config=config)


def test_judge_llm_failure_returns_zero(db_session, monkeypatch):
    """[P2] judge LLM 调用失败时返回 0 分 + 失败原因（不抛异常，eval 不中断）。"""
    from app.eval import judge as judge_mod
    from app.services.llm_config_service import ResolvedChatConfig

    def _fail(metric_key, output, llm_config, context=None):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(judge_mod, "_call_judge_llm", _fail)

    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")
    result = judge_mod.judge(metric_key="structure", output="x", llm_config=config)
    assert result.score == 0
    assert "失败" in result.reason or "不可用" in result.reason
