"""[P2] eval 评估样本（spec 附录 A.3 / P2）。

样本含「好输出」和「坏输出」对，基于真实交底书（区块链访问控制/蚁群缓存等）抽象脱敏。
好输出符合 S1-S5 改进点（期望高分），坏输出违反改进点（期望低分）。
让 eval 能对比证明提示词改进的效果——如果 judge 给好输出打高分、坏输出打低分，
说明 judge 指标有效；进而可用 judge 评真实生成的输出。

expected_min/expected_max 是 judge 应落入的分数区间（用于 runner 判定 judge 是否合理）。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    """单个评估样本。"""
    metric_key: str        # structure / consistency / conformity
    output: str            # 待评输出
    context: str           # 前文上下文（consistency 用，其他可空）
    expected_min: int      # judge 期望分数下界
    expected_max: int      # judge 期望分数上界
    label: str             # good / bad（用于报告分组）
    name: str              # 样本标识（报告用）


SAMPLES: list[Sample] = [
    # ===== structure（结构完整性，验证 S1 激活 completion_criteria）=====

    Sample(
        metric_key="structure",
        label="good",
        name="solution_full_dimensions",
        output=(
            "## 技术方案\n\n"
            "为解决上述数据与控制策略分离导致控制失效的技术问题，本发明提出一种数据元件式访问控制系统，"
            "其特征在于包括以下组成部分：\n\n"
            "### 整体架构\n"
            "系统由数据元件封装模块、跨平台适配模块、嵌入式策略执行引擎三大核心组件构成，"
            "三者通过标准化接口协作。\n\n"
            "### 关键要素\n"
            "- 数据元件封装模块：负责将加密数据与访问控制策略封装为不可分离的整体；\n"
            "- 跨平台适配模块：自动识别目标环境特征并适配；\n"
            "- 嵌入式策略执行引擎：在用户访问时执行策略验证与数据解密。\n\n"
            "### 工作原理\n"
            "数据元件创建时建立完整性存证 → 传输至目标环境后验证完整性 → "
            "用户访问时引擎分层验证策略（时间/权限/网络）→ 验证通过则解密并处理数据。"
        ),
        context="",
        expected_min=80,
        expected_max=100,
    ),
    Sample(
        metric_key="structure",
        label="bad",
        name="solution_missing_dimensions",
        output=(
            "本发明是一种访问控制系统。"
            "它用了一些模块来处理数据。"
            "具体怎么做不太重要，反正能实现访问控制。"
        ),
        context="",
        expected_min=0,
        expected_max=40,
    ),

    # ===== consistency（前文一致性，验证 S3-1 一致性约束）=====

    Sample(
        metric_key="consistency",
        label="good",
        name="solution_echoes_problem",
        context=(
            "【技术问题】现有访问控制系统中，数据与控制策略是分离的。"
            "数据一旦离开原始控制环境，策略即失效，存在『一次验证、后续失控』的问题。"
            "本发明要解决的技术问题是：如何使数据与控制策略不可分离地绑定。"
        ),
        output=(
            "为解决上述『数据与控制策略分离导致后续失控』的技术问题，本发明将加密数据与访问控制策略"
            "封装为不可分离的数据元件。通过嵌入式策略执行引擎，确保数据在任何环境中都无法脱离策略控制，"
            "从根本上解决了『一次验证、后续失控』的问题。"
        ),
        expected_min=80,
        expected_max=100,
    ),
    Sample(
        metric_key="consistency",
        label="bad",
        name="solution_ignores_problem",
        context=(
            "【技术问题】现有访问控制系统中，数据与控制策略是分离的，存在『一次验证、后续失控』的问题。"
            "本发明要解决的技术问题是：如何使数据与控制策略不可分离地绑定。"
        ),
        output=(
            "本系统采用区块链技术。区块链是分布式账本，具有去中心化、不可篡改的特点。"
            "智能合约可以自动执行业务逻辑。本方案创新性地引入了共识机制。"
        ),
        expected_min=0,
        expected_max=40,
    ),

    # ===== conformity（章节规范度，验证 S4-1 few-shot）=====

    Sample(
        metric_key="conformity",
        label="good",
        name="professional_patent_style",
        output=(
            "本发明涉及数据访问控制技术领域，尤其涉及一种数据元件式访问控制方法。"
            "本发明通过将数据与控制策略封装为不可分离的数据元件，并采用基于任务启动时间的"
            "简化控制机制，实现了数据的可控流通。相比现有 RBAC、ABAC 等方案，"
            "本发明避免了复杂的实时监控，在保证安全性的同时降低了系统复杂度。"
        ),
        context="",
        expected_min=75,
        expected_max=100,
    ),
    Sample(
        metric_key="conformity",
        label="bad",
        name="marketing_hype_style",
        output=(
            "这是史上最牛的访问控制神器！！革命性突破，颠覆传统！"
            "用了绝对安全，黑客看了都流泪。性价比超高，买了就是赚到。"
            "我们的技术遥遥领先，友商根本比不了。"
        ),
        context="",
        expected_min=0,
        expected_max=40,
    ),
]
