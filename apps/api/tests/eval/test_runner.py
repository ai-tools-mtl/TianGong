"""[P2] eval 运行器测试。

runner 跑所有样本 × judge，产出报告。核心验证：
- 报告含每个样本的分数
- 区分度判定：好样本应得高分、坏样本应得低分（验证 judge 指标有效）

测试 mock judge（不调真实 LLM），用固定分数验证 runner 的聚合/报告逻辑。
"""


def test_runner_produces_report(monkeypatch):
    """[P2] runner 跑完产出报告，含每个样本的分数。"""
    from app.eval import runner, judge as judge_mod
    from app.eval.judge import JudgeResult
    from app.services.llm_config_service import ResolvedChatConfig

    # mock judge 返回固定分数（区分好/坏）
    def _fake_judge(metric_key, output, llm_config, *, context=None):
        # 好样本（label good）高分，坏样本低分——靠 output 长度粗略区分
        score = 85 if len(output) > 50 else 20
        return JudgeResult(score=score, reason="测试理由")

    monkeypatch.setattr(runner, "judge", _fake_judge)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")

    report = runner.run_eval(llm_config=config)

    assert len(report.results) == len(runner.SAMPLES)
    for r in report.results:
        assert 0 <= r.score <= 100
        assert r.sample_name


def test_runner_report_has_summary(monkeypatch):
    """[P2] 报告含汇总：好/坏样本的平均分 + 区分度判定。"""
    from app.eval import runner
    from app.eval.judge import JudgeResult
    from app.services.llm_config_service import ResolvedChatConfig

    def _fake_judge(metric_key, output, llm_config, *, context=None):
        score = 88 if len(output) > 50 else 15
        return JudgeResult(score=score, reason="x")

    monkeypatch.setattr(runner, "judge", _fake_judge)
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")

    report = runner.run_eval(llm_config=config)

    assert hasattr(report, "good_avg")
    assert hasattr(report, "bad_avg")
    assert hasattr(report, "discriminates")  # 区分度：好样本均分是否显著高于坏样本
    # mock 下好样本应高分、坏样本低分 → 有区分度
    assert report.good_avg > report.bad_avg
    assert report.discriminates is True


def test_runner_discrimination_detection_when_no_separation(monkeypatch):
    """[P2] judge 无法区分好坏时，discriminates=False（提示 judge 指标无效）。"""
    from app.eval import runner
    from app.eval.judge import JudgeResult
    from app.services.llm_config_service import ResolvedChatConfig

    # mock judge 对所有样本打同样分（无区分度）
    monkeypatch.setattr(runner, "judge",
                        lambda metric_key, output, llm_config, *, context=None: JudgeResult(score=50, reason="x"))
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")

    report = runner.run_eval(llm_config=config)
    assert report.discriminates is False


def test_runner_report_render_text(monkeypatch):
    """[P2] 报告可渲染为文本（供 CLI/日志输出）。"""
    from app.eval import runner
    from app.eval.judge import JudgeResult
    from app.services.llm_config_service import ResolvedChatConfig

    monkeypatch.setattr(runner, "judge",
                        lambda metric_key, output, llm_config, *, context=None: JudgeResult(score=80, reason="ok"))
    config = ResolvedChatConfig(base_url="http://x", api_key="k", model="glm-4.7", source="env")

    report = runner.run_eval(llm_config=config)
    text = runner.render_report(report)
    assert "好样本" in text or "good" in text.lower()
    assert "区分度" in text or "discriminat" in text.lower()
