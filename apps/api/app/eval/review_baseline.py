"""[优化计划批次 5] 审查评分回归基线：防「改 prompt/rubric/模型后评分漂移」。

与 runner.py 的分工：
- runner（P2）验证 **judge 指标有效**（好坏样本区分度）；
- 本模块验证 **评分管线稳定**——固定样本 × 真实 run_review 评分阶段（不落库），
  与已提交基线比对，偏差超阈值（默认每维度 ±15）报警退出非零。

使用场景：改 rubric prompt / 换模型 / 调自一致性参数后跑一次确认没漂。

CLI（手动触发，调真 LLM 有成本，不进 CI）：
    python -m app.eval.review_baseline            # 与基线比对（无基线则生成）
    python -m app.eval.review_baseline --update   # 有意变更后重建基线

首跑生成 app/eval/baselines/review_baseline.json，人工确认分数合理后提交入库。
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.services.llm_config_service import ResolvedChatConfig

BASELINE_PATH = Path(__file__).parent / "baselines" / "review_baseline.json"
DEFAULT_TOLERANCE = 15  # 单维度允许偏差（LLM 评分固有抖动 + 自一致性部分平滑）


# ── 样本：两篇固定交底书（好/中两档——好样本验证高分稳定，中样本验证中分段稳定）──
# 内容脱敏抽象自真实交底书主题，与 samples.py 同源但组织为完整章节集。

DISCLOSURE_GOOD: dict[str, str] = {
    "技术领域": (
        "本发明涉及数据安全技术领域，尤其涉及一种数据元件式访问控制方法及系统。"
    ),
    "背景技术": (
        "现有访问控制系统中，数据与访问控制策略是分离管理的。数据一旦离开原始控制环境，"
        "预置的控制策略即告失效，存在『一次验证、后续失控』的问题。已有 RBAC/ABAC 方案"
        "依赖控制中心实时监控，跨环境场景下延迟高且存在单点故障。"
    ),
    "技术问题": (
        "本发明要解决的技术问题是：如何使数据与访问控制策略不可分离地绑定，"
        "使数据在任何环境下都处于策略控制之下，同时避免控制中心的实时监控依赖。"
    ),
    "技术方案": (
        "为解决上述技术问题，本发明提出一种数据元件式访问控制方法，包括：\n"
        "（1）数据元件封装步骤：将加密数据与访问控制策略封装为不可分离的数据元件，"
        "封装时建立完整性证；\n"
        "（2）跨平台适配步骤：数据元件到达目标环境后，适配模块自动识别环境特征并"
        "完成本地化注册；\n"
        "（3）策略执行步骤：用户访问时，嵌入式策略执行引擎分层验证时间、权限、"
        "网络三类策略，验证通过后解密并交付数据。\n"
        "进一步地，策略执行采用基于任务启动时间的简化控制机制，任务结束后自动失效，"
        "无需实时监控。"
    ),
    "有益效果": (
        "（1）数据与策略封装为整体，脱离原始环境后策略依然有效，杜绝『一次验证、后续失控』；"
        "（2）策略执行本地化，无控制中心实时监控依赖，跨环境延迟低且无单点故障；"
        "（3）任务级时效控制以简化机制达到实时监控的等效安全性。"
    ),
}

DISCLOSURE_MEDIOCRE: dict[str, str] = {
    "技术领域": "本发明涉及一种访问控制系统。",
    "背景技术": (
        "现在的访问控制系统有很多问题，数据和策略分开管，容易出安全事故，"
        "用起来也很麻烦，需要改进。"
    ),
    "技术问题": "本发明要解决访问控制不方便、不安全的问题。",
    "技术方案": (
        "本发明把数据和策略绑在一起，做成一个整体的东西传输。"
        "到了目标环境再检查一下有没有被改过，用户访问的时候验证权限。"
        "具体实现方式比较灵活，可以有多种变化。"
    ),
    "有益效果": "本发明更安全，也更方便，效果比现有技术好。",
}

BASELINE_SAMPLES: dict[str, dict[str, str]] = {
    "disclosure_good": DISCLOSURE_GOOD,
    "disclosure_mediocre": DISCLOSURE_MEDIOCRE,
}


@dataclass
class BaselineReport:
    """基线比对报告。"""
    results: list[dict] = field(default_factory=list)  # {sample, key, base, now, diff}
    tolerance: int = DEFAULT_TOLERANCE
    has_baseline: bool = True
    updated: bool = False

    @property
    def max_abs_diff(self) -> float:
        return max((abs(r["diff"]) for r in self.results), default=0.0)

    @property
    def passed(self) -> bool:
        return self.has_baseline and all(abs(r["diff"]) <= self.tolerance for r in self.results)


def _score_sample(
    criteria: list[dict], sections: dict[str, str],
    llm_config: ResolvedChatConfig, runs: int,
) -> dict[str, int]:
    """对一篇样本跑全部 rubric 维度（每维度 runs 次取平均，与生产口径一致）。"""
    from app.services.review_service import _score_dimension

    out: dict[str, int] = {}
    for criterion in criteria:
        scores = []
        for _ in range(runs):
            score, _evidence, _suggestion = _score_dimension(criterion, sections, llm_config)
            scores.append(score)
        out[criterion["key"]] = round(sum(scores) / len(scores))
    return out


def run_baseline(
    db, llm_config: ResolvedChatConfig, *, update: bool = False,
    baseline_path: Path = BASELINE_PATH, runs: int = 2,
) -> BaselineReport:
    """跑样本并与基线比对（无基线或 update=True 时生成基线）。

    rubric 取系统默认（user_id=None）——基线必须锚定在稳定配置上，
    避免某用户的自定义 rubric 让比对失去意义。
    """
    from app.services.rubric_service import get_effective_rubric
    from app.services.review_service import CONSISTENCY_RUNS

    rubric = get_effective_rubric(db, user_id=None)
    criteria = rubric.criteria
    runs = runs or CONSISTENCY_RUNS

    current: dict[str, dict[str, int]] = {}
    for name, sections in BASELINE_SAMPLES.items():
        logger.info("基线评分样本 {}/{}: {}", len(current) + 1, len(BASELINE_SAMPLES), name)
        current[name] = _score_sample(criteria, sections, llm_config, runs)
        time.sleep(0.5)  # 轻 ratelimit 缓冲

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_data = None
    if baseline_path.exists() and not update:
        baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))

    report = BaselineReport()
    if baseline_data is None:
        # 生成基线
        payload = {
            "meta": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "model": llm_config.model,
                "provider_source": llm_config.source,
                "runs_per_dimension": runs,
                "tolerance": DEFAULT_TOLERANCE,
            },
            "samples": current,
        }
        baseline_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report.has_baseline = False
        report.updated = True
        for name, dims in current.items():
            for key, score in dims.items():
                report.results.append(
                    {"sample": name, "key": key, "base": None, "now": score, "diff": None}
                )
        return report

    report.tolerance = int(baseline_data.get("meta", {}).get("tolerance", DEFAULT_TOLERANCE))
    base_samples = baseline_data.get("samples", {})
    for name, dims in current.items():
        base_dims = base_samples.get(name, {})
        for key, score in dims.items():
            base = base_dims.get(key)
            report.results.append({
                "sample": name, "key": key,
                "base": base, "now": score,
                "diff": None if base is None else score - base,
            })
    return report


def render_report(report: BaselineReport) -> str:
    lines = ["=" * 64, "审查评分回归基线报告", "=" * 64]
    if report.updated:
        lines.append(
            "\n📦 已生成基线文件（首跑或 --update）。请人工确认下列分数合理后提交："
        )
        for r in report.results:
            lines.append(f"  {r['sample']:<22} {r['key']:<16} {r['now']}")
        lines.append(f"\n基线路径：{BASELINE_PATH}")
        return "\n".join(lines)

    lines.append(f"\n容差：±{report.tolerance}（单维度）")
    lines.append(f"\n{'样本':<22} {'维度':<16} {'基线':>4} {'当前':>4} {'偏差':>5} 状态")
    lines.append("-" * 64)
    for r in report.results:
        if r["base"] is None:
            lines.append(f"{r['sample']:<22} {r['key']:<16} {'—':>4} {r['now']:>4} {'—':>5} ⚠️ 基线缺失")
        else:
            ok = abs(r["diff"]) <= report.tolerance
            lines.append(
                f"{r['sample']:<22} {r['key']:<16} {r['base']:>4} {r['now']:>4} "
                f"{r['diff']:>+5} {'✅' if ok else '❌ 漂移'}"
            )
    lines.append(f"\n最大偏差：{report.max_abs_diff:+.0f}")
    lines.append(f"结论：{'✅ 评分体系稳定' if report.passed else '❌ 存在超容差漂移——回查 prompt/rubric/模型变更'}")
    return "\n".join(lines)


def __main__() -> None:
    import sys

    from app.core.database import SessionLocal
    from app.services.llm_config_service import resolve_chat_config

    update = "--update" in sys.argv
    db = SessionLocal()
    try:
        cfg = resolve_chat_config(db, user_id=None)
        if cfg is None:
            logger.error("未配置 LLM，无法运行基线。请先配置全局/环境 LLM。")
            sys.exit(1)
        report = run_baseline(db, cfg, update=update)
        print(render_report(report))
        sys.exit(0 if (report.passed or report.updated) else 1)
    finally:
        db.close()


if __name__ == "__main__":
    __main__()
