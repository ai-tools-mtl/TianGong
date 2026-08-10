"""[P2] eval 运行器：跑样本 × judge，产出报告（spec 附录 A.3 / P2）。

核心价值：验证 judge 指标对好/坏样本的区分度。
- 若 judge 给好样本打高分、坏样本打低分（discriminates=True），说明指标有效，
  可用于评真实生成输出。
- 若区分不出（discriminates=False），说明 judge 指标或 prompt 需调整。

run_eval 调真实 LLM（judge），较慢且有成本；单测 mock judge 验证聚合逻辑。
生产用法：配好 LLM 后跑 `python -m app.eval.runner`，看报告。
"""
from dataclasses import dataclass, field

from app.eval.judge import judge
from app.eval.samples import SAMPLES
from app.services.llm_config_service import ResolvedChatConfig

# 区分度阈值：good_avg - bad_avg >= 此值视为 judge 能区分好坏。
# 20 分是经验值——LLM-as-judge 对好/坏样本的分数差通常 >= 30，留余量。
DISCRIMINATION_THRESHOLD = 20


@dataclass
class EvalResult:
    """单样本评估结果。"""
    sample_name: str
    metric_key: str
    label: str
    score: int
    reason: str


@dataclass
class EvalReport:
    """整体评估报告。"""
    results: list[EvalResult] = field(default_factory=list)
    good_avg: float = 0.0
    bad_avg: float = 0.0
    discriminates: bool = False

    def avg_by_label(self, label: str) -> float:
        scores = [r.score for r in self.results if r.label == label]
        return sum(scores) / len(scores) if scores else 0.0


def run_eval(llm_config: ResolvedChatConfig) -> EvalReport:
    """跑所有样本，返回评估报告。

    Args:
        llm_config: judge 用的 LLM 配置。

    Returns:
        EvalReport，含每个样本分数 + 好/坏均分 + 区分度判定。
    """
    report = EvalReport()
    for sample in SAMPLES:
        result = judge(
            metric_key=sample.metric_key,
            output=sample.output,
            llm_config=llm_config,
            context=sample.context or None,
        )
        report.results.append(EvalResult(
            sample_name=sample.name,
            metric_key=sample.metric_key,
            label=sample.label,
            score=result.score,
            reason=result.reason,
        ))
    report.good_avg = report.avg_by_label("good")
    report.bad_avg = report.avg_by_label("bad")
    report.discriminates = (report.good_avg - report.bad_avg) >= DISCRIMINATION_THRESHOLD
    return report


def render_report(report: EvalReport) -> str:
    """渲染报告为文本（供 CLI/日志输出）。"""
    lines = ["=" * 60, "提示词质量评估报告（P2 eval）", "=" * 60]
    lines.append(f"\n样本数：{len(report.results)}")
    lines.append(f"好样本均分：{report.good_avg:.1f}")
    lines.append(f"坏样本均分：{report.bad_avg:.1f}")
    lines.append(f"区分度：{'✅ 有效' if report.discriminates else '❌ 不足（judge 指标需调整）'}")
    lines.append(f"（区分度阈值：好/坏均分差 >= {DISCRIMINATION_THRESHOLD}）")
    lines.append("\n明细：")
    lines.append(f"{'样本':<32} {'指标':<14} {'标签':<6} {'分数':<6} 理由")
    lines.append("-" * 60)
    for r in report.results:
        lines.append(f"{r.sample_name:<32} {r.metric_key:<14} {r.label:<6} {r.score:<6} {r.reason[:30]}")
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI 入口：配好环境变量后跑 `python -m app.eval.runner`
    import sys
    from loguru import logger

    from app.core.database import SessionLocal
    from app.services.llm_config_service import resolve_chat_config

    db = SessionLocal()
    try:
        # 用环境/全局配置作为 judge（eval 需稳定，不建议用用户自配）
        cfg = resolve_chat_config(db, user_id=None)
        if cfg is None:
            logger.error("未配置 LLM，无法运行 eval。请先配置全局/环境 LLM。")
            sys.exit(1)
        rpt = run_eval(cfg)
        print(render_report(rpt))
    finally:
        db.close()
