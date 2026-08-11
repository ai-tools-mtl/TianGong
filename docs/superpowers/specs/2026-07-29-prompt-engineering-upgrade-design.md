# 提示词工程升级设计（Prompt Engineering Upgrade）

> ⚠️ **本文档已降级为【支撑层文档】（2026-07-29 更新）**
>
> 本文档最初把"提示词工程"窄化为"工程治理"（JSON 解析 / 观测 / eval / 版本管理），方向偏了。提示词工程的**主线**是"在每次 agent request 中让模型理解用户、高质量输出"。
>
> 👉 **主线设计见**：[2026-07-29-prompt-content-design-design.md](2026-07-29-prompt-content-design-design.md)
>
> 本文档（P0/P1/P2/P3）降级为该主线的**支撑层附录**（其附录 A 全文复制了本文档的工程治理内容）。本文档的 P0（审查结构化输出）= 主线的阶段 5；P1/P2/P3（Langfuse 观测 / DeepEval eval / Promptfoo gate）是为内容设计主线兜底的脚手架，建议配合主线阶段 2 起并行推进。

---

> **版本**：v1.0 ｜ **日期**：2026-07-29 ｜ **状态**：已降级为支撑层（见上方声明）
> **作者**：tl.m
> **依赖 spec**：[2026-07-13-tiangong-mvp-design.md](2026-07-13-tiangong-mvp-design.md) §5.4/§5.5/§6、[2026-07-22-agent-skills-design.md](2026-07-22-agent-skills-design.md)、[2026-07-27-cross-section-context-design.md](2026-07-27-cross-section-context-design.md)

---

## 0. 本文档定位（已降级，见顶部声明）

**本文档原为「现状诊断 + 升级路线图」，聚焦工程治理（JSON 解析/观测/eval/版本）。** 经评审，此为提示词工程的支撑层而非主线。主线（内容设计）见顶部链接。下方原文保留，对应主线附录 A 的 P1/P2/P3 部分。

落地实施请另起 plan（参考 `docs/superpowers/plans/archive/` 现有计划的 TDD 结构）。本文档经评审、决策点确认后，再决定是否进入实现。

---

## 1. 现状诊断（代码已核实）

### 1.1 已经做对的（保留）

| 维度 | 实现 | 评价 |
|---|---|---|
| 分层上下文装配 | `apps/api/app/ai/context_assembler.py` `build_system_prompt()`（L155-212）五层拼接：项目元信息 [L4] → 已写章节 [前文直注入] → 用户记忆 → 当前章节策略 → 角色兜底 | ✅ 教科书级 Context Engineering，带 `WRITTEN_SECTIONS_CHAR_BUDGET = 8000` token 预算 |
| 章节 Prompt 注册表 | `apps/api/app/ai/section_prompts.py` `SECTION_PROMPTS` dataclass（9 章节 × 4 字段） | ✅ 知识资产沉淀到位 |
| ReAct / agent loop | `apps/api/app/ai/agent.py` `build_agent()` 用 deepagents + `rag_search` @tool | ✅ 边推理边调工具 |
| 自一致性 | `apps/api/app/services/review_service.py` `CONSISTENCY_RUNS = 2`（L21）每维度跑 2 次取均值 | ✅ Self-Consistency 已用 |
| Rubric 驱动审查 | `apps/api/app/ai/rubric_prompts.py` `build_score_prompt()` 参数化，`review_rubric.criteria` 可后台编辑 | ✅ 标准结构化进提示词 |

### 1.2 待补的缺口（本 spec 要解决）

| # | 缺口 | 现状代码 | 危害 | 对应章节 |
|---|---|---|---|---|
| G1 | **审查 JSON 用脆弱正则解析** | `review_service.py:130` `re.search(r"\{[^{}]*\}", text, re.DOTALL)`——**连嵌套 JSON 都匹配不了**；失败时静默返回 `(50, "评分失败", "请重试")`（L125-126） | 审查评分经常假性失败/退化为 50 分；且**该解析逻辑零单测覆盖** | §3 P0 |
| G2 | **未启用结构化输出** | 全局搜 `with_structured_output\|response_format` 零命中；审查靠手写正则 | 同 G1；且 Pydantic 在项目里只用于 API schema，没用于 LLM 输出约束 | §3 P0 |
| G3 | **`guide_questions` 字段定义了却从未注入** | `section_prompts.py` 每个章节都写了 2-3 个引导问题，但 `build_system_prompt`（L203-207）只用了 `goal` 和 `output_format` | 知识资产闲置；章节生成缺引导性 | §3 P0 / §5 |
| G4 | **提示词全硬编码、无版本、无观测** | 7 处提示词散落在 Python 代码里（见 §1.3）；`LLMCallLog` 表明确**红线「绝不存 prompt/completion 内容」**（隐私决策对，但副作用是无法 debug/eval） | 改提示词像盲改；无法回归 | §3 P1 |
| G5 | **无 eval / 回归机制** | `tests/test_prompts.py` 仅 3 个测试，只断言章节 key 注册表存在；`test_review_service.py` 实测的是知识库审核（KnowledgeReview）**不是评分解析**；无 LangSmith/Langfuse 集成 | 提示词改动无质量门禁 | §3 P2/P3 |
| G6 | **两套并存的装配逻辑（技术债）** | `assemble_messages()`（L28-70，旧 `stream_*` 用，Message 列表）vs `build_system_prompt()`（L155-212，agent loop 用，单字符串）——**逻辑重复 + 拼接顺序不同** | 维护双份；改一处忘改另一处 | §6（架构债，非本 spec 主线） |
| G7 | **设计偏差：无独立 SystemPromptBuilder 抽象** | MVP 设计图（`2026-07-13-tiangong-mvp-design.md` §架构图）画了 `SystemPromptBuilder / ContextAssembler / SectionPromptRegistry` 三组件；实际 `SystemPromptBuilder` 没落地，装配和上下文耦合在 `build_system_prompt` 里 | 扩展新场景（如未来「专利权利要求生成」）需改核心函数 | §6 |

### 1.3 提示词全量调用点清单（核实）

| 场景 | 文件:行 | 写法 | 结构化输出 |
|---|---|---|---|
| AI 对话/生成 | `orchestrator.py` `astream_chat`/`astream_generate` → `agent.py` `build_agent` | `build_system_prompt()` 动态装配 | ❌（流式文本） |
| 段落重写 | `orchestrator.py:213-216` | 内联 f-string `SystemMessage` | ❌ |
| 图注润色 | `api/ai.py:624-631` | 内联 f-string `SystemMessage` | ❌ |
| 审查评分 | `review_service.py:112-118` + `rubric_prompts.py` | `SCORE_SYSTEM_PROMPT` + `build_score_prompt` | ❌（手写正则） |
| 章节摘要 | `summary_service.py:39-43` | 内联 f-string | ❌（失败降级前 200 字） |
| 会话标题 | `conversation_service.py:35-42` | 内联 f-string | ❌（失败降级前 20 字） |
| 连通性测试 | `llm_config_service.py:234` | `HumanMessage("hi")` | N/A |
| RAG 问答 | 无独立提示词 | 检索结果以 tool_result 回流 agent | N/A |
| Embedding/Rerank | `rag/embedding.py`、`rag/reranker.py` | 无提示词（向量化/重排） | N/A |

**组织方式**：用 LangChain 但只用最底层的 `SystemMessage`/`HumanMessage`，**没用** `PromptTemplate`/`ChatPromptTemplate`（全局零命中）。变量插值全靠 f-string。

---

## 2. 设计目标与非目标

### 2.1 目标
1. **消灭审查评分的脆弱解析**（G1+G2）——这是 ROI 最高、最痛的一处。
2. **补齐提示词工程化治理**（G4）：版本管理 + 可观测。
3. **补齐 eval 基线**（G5）：提示词改动有质量门禁。
4. **激活闲置知识资产**（G3）：`guide_questions` 真正进提示词。
5. 全程**不破坏现有隐私边界**（`LLMCallLog` 不存内容）、**不引入外部 SaaS 依赖**（自托管优先）。

### 2.2 非目标
- ❌ 不在本 spec 范围：统一两套装配逻辑（G6）、抽 `SystemPromptBuilder`（G7）——见 §6，列为后续架构债，单独开 spec。
- ❌ 不重写现有已经 work 的提示词内容（除非 eval 证明退化）。
- ❌ 不引入新 agent 框架（deepagents 继续用）。

---

## 3. 升级路线图（P0 → P3）

### P0：结构化输出替换审查正则（G1+G2+G3）—— ROI 最高，1-2 天

**为什么 P0**：G1 是唯一有「正确性风险」的缺口（假性失败、退化 50 分、零单测），且改造面最小、栈最对齐。

#### P0-1：审查评分改 `with_structured_output`

**现状**（`review_service.py:109-133`）：
```python
def _score_dimension(criterion, sections, llm_config):
    llm = get_llm(llm_config)
    prompt = build_score_prompt(criterion, sections)
    try:
        resp = llm.invoke([SystemMessage(...), HumanMessage(content=prompt)])
        data = _parse_json_response(resp.content)  # ❌ 脆弱正则，嵌套 JSON 必挂
        return (max(0, min(100, int(data.get("score", 50)))), data.get("evidence",""), data.get("suggestion",""))
    except Exception:
        return (50, "评分失败", "请重试")  # ❌ 静默退化，污染总分

def _parse_json_response(text: str) -> dict:
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)  # ❌ [^{}]* 排除嵌套
    ...
```

**改造后**（新增 `apps/api/app/ai/schemas/review_schema.py`）：
```python
from pydantic import BaseModel, Field

class DimensionScore(BaseModel):
    """单个审查维度的结构化评分输出。"""
    score: int = Field(ge=0, le=100, description="该维度得分，0-100 整数")
    evidence: str = Field(description="评分依据，需引用交底书具体内容")
    suggestion: str = Field(description="可操作的改进建议，无改进空间时填『已达标』")

# review_service.py 改造
def _score_dimension(criterion, sections, llm_config):
    llm = get_llm(llm_config).with_structured_output(DimensionScore)  # ✅ 强约束
    prompt = build_score_prompt(criterion, sections)
    try:
        result: DimensionScore = llm.invoke([
            SystemMessage(content=SCORE_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        return (result.score, result.evidence, result.suggestion)
    except Exception as e:
        logger.warning("score_dimension failed: %s", e)
        return (50, "评分失败", "请重试")  # 兜底保留，但触发率应大幅下降
```

**配套改造**：
- `rubric_prompts.py` 的 `build_score_prompt` 末尾「输出 JSON 格式」段改为「按 schema 输出」（结构化输出模式下可弱化格式指令，但仍保留作兼容）。
- `SCORE_SYSTEM_PROMPT` 第 4 条「输出必须是合法 JSON」改为「严格按输出规范填写各字段」。

**决策点 D1**（见 §7）：是否所有 LLM provider 都支持 `with_structured_output`？

#### P0-2：补齐审查解析的单测（G5 的一部分）

`test_review_service.py` 目前**完全没覆盖评分解析**（它测的是知识库审核 KnowledgeReview）。新增 `tests/test_review_scoring.py`：
- `test_dimension_score_schema_validation`：mock LLM 返回合法/非法 JSON，断言 `DimensionScore` 正确解析/拒绝。
- `test_nested_json_now_parseable`：回归 G1——喂一段含嵌套 JSON 的响应，断言不再被正则误杀。
- `test_fallback_on_provider_error`：mock provider 报错，断言走 `(50, "评分失败", "请重试")` 兜底。

#### P0-3：激活 `guide_questions`（G3）

**现状**：`section_prompts.py` 每章节的 `guide_questions` 定义了却从未注入。
**改造**（`context_assembler.build_system_prompt` L203-207 附近）：
```python
parts.append("# 当前正在撰写章节")
parts.append(f"章节标题：【{section.title}】")
parts.append(f"本章目标：{sp.goal}")
# 【新增】引导问题注入（知识资产激活，G3）
if sp.guide_questions:
    q_text = "\n".join(f"- {q}" for q in sp.guide_questions)
    parts.append(f"引导要点（可主动追问用户）：\n{q_text}")
parts.append(f"输出格式要求：{sp.output_format}")
```

> 注意：注入到 system prompt 顶部（引导性信号），而非生成指令末尾——避免 LLM 把引导问题当成「必须全部回答的清单」。`assemble_messages`（旧路径）同步注入，保持一致。

**P0 验收**：
- ✅ `_parse_json_response` 正则解析被 `with_structured_output(DimensionScore)` 替换。
- ✅ 新增 3 个单测，覆盖合法/非法/嵌套 JSON 场景。
- ✅ `guide_questions` 在 `build_system_prompt` 和 `assemble_messages` 两处都注入。
- ✅ 现有 `test_review_service.py`（知识库审核）、`test_prompts.py`（注册表）不回归。

---

### P1：自托管 Langfuse 观测 + prompt 版本（G4）—— 1 周

**为什么 P1**：G4 是「改了不知道好坏」的根因。`LLMCallLog` 主动不存内容（隐私决策正确），导致 debug/eval 黑洞。Langfuse 自托管（Docker）能在**不外包数据**前提下补上观测。

#### P1-1：自托管 Langfuse 部署
- `docker-compose.yml` 新增 `langfuse` + `langfuse-worker` + 共用 Postgres（或独立 Postgres）服务。
- 环境变量 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 走 `.env`（参考现有 `llm_config_service` 的 env 解析模式）。

#### P1-2：Langfuse 集成（`@observe` 装饰器）
- 新增 `apps/api/app/ai/observability.py`，提供 `observed` 装饰器（对 `astream_chat`/`astream_generate`/`_score_dimension` 等关键函数）。
- **隐私边界**：Langfuse 默认会 trace input/output。需在装饰器内做**字段脱敏**——保留结构（是否调用工具、消息轮数、token 用量、耗时），**对 prompt/completion 文本按配置可关闭**。默认配置：开发环境存全文，生产环境只存 metadata（与 `LLMCallLog` 红线一致）。

**决策点 D2**（见 §7）：生产环境 Langfuse 是否存 prompt/completion 全文？

#### P1-3：Prompt 版本管理（可选，渐进）
Langfuse 支持 prompt 版本管理（存在 Langfuse DB，运行时拉取）。**渐进策略**：
- 阶段 1（P1 本体）：只接 tracing，提示词仍在代码里。
- 阶段 2（未来）：把高频迭代的提示词（如审查 `SCORE_SYSTEM_PROMPT`、章节策略）迁到 Langfuse 管理，代码侧按 name+version 拉取。
- **不强制一次性迁移**——避免引入「代码和 Langfuse 两处真相源」的混乱。

**P1 验收**：
- ✅ `docker compose up langfuse` 起得来，Web UI 可访问。
- ✅ 关键 LLM 调用有 trace（含 token/耗时/工具调用链）。
- ✅ 生产环境配置下，prompt/completion 文本按 D2 决策脱敏。
- ✅ 不影响现有 `LLMCallLog`（两者并存，Langfuse 是补充观测）。

---

### P2：DeepEval baseline eval（G5）—— 1-2 周

**为什么 P2**：P0/P1 完成后，有观测了，但还没有「自动判分」。DeepEval 是 pytest 风格，和现有 36 个测试最贴合。

#### P2-1：评估指标设计
针对专利交底书场景，定义 DeepEval 指标（放 `apps/api/tests/eval/`）：
- **章节生成质量**：`GEval`（自定义 LLM-as-judge）评「术语一致性 / 技术方案完整性 / 与前文章节连贯性」。
- **审查评分一致性**：同一交底书多次跑 review，断言 `dimension_scores` 标准差 < 阈值（量化现有 `CONSISTENCY_RUNS=2`）。
- **摘要忠实度**：`SummarizationMetric` 评 `summary_service` 生成的摘要是否忠实原文。
- **幻觉检测**：`FaithfulnessMetric` 评生成内容是否编造（对应 `SYSTEM_PROMPT` 第 2 条「不要替用户编造」）。

#### P2-2：Golden dataset
- 建立 `tests/eval/fixtures/` 下的小规模 golden set（5-10 个真实脱敏交底书 + 期望评分区间）。
- eval 用真实 LLM（非 mock），跑在 CI 的 nightly job（不阻塞 PR，只出报告）。

**P2 验收**：
- ✅ 至少 3 类指标（章节质量 / 审查一致性 / 摘要忠实度）有 eval 用例。
- ✅ nightly CI 跑通，产出 eval 报告（接 Langfuse 或独立 HTML）。
- ✅ 改动提示词后，能跑 eval 看是否退化。

---

### P3：Promptfoo 回归 gate（G5 加强）—— 按需

**为什么 P3 且可选**：P2 的 DeepEval 是「离线评估」，P3 的 Promptfoo 是「提示词改动的回归门禁」。

- 在 PR 改动 `section_prompts.py` / `rubric_prompts.py` 时，触发 Promptfoo 对比新旧版本输出。
- Promptfoo 的 `assert` 配合 LLM-as-judge，断言「新版本不比旧版本差」。
- 失败则 block merge（可选，先 warning）。

**P3 验收**：
- ✅ Promptfoo 配置覆盖至少审查 + 3 个核心章节。
- ✅ PR 流程能触发对比报告。

---

## 4. 方法论对照（Anthropic / Deep Agents / 专利领域）

> 本节不是新代码，而是用业界方法论对照现有实现，找出「已对齐的」和「可改进的」。

### 4.1 Anthropic Context Engineering 对照

来源：[Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)、[long-context prompting](https://www.anthropic.com/news/prompting-long-context)。

| Anthropic 原则 | 天工现状 | 评估 |
|---|---|---|
| 长文档放提示词**顶部** | `build_system_prompt` 顺序：项目元信息 [L4]→已写章节→记忆→章节策略→角色 | ✅ 对齐（长上下文在前，指令在后） |
| 起步最小化，按需扩 context | 全量注入已写章节（截断 8000 字） | ⚠️ 可改进：当前无「相关性筛选」，全量注入可能稀释信号。未来可按章节相关性裁剪 |
| 结构化 context（用 XML/Markdown 分段） | 用 `# 标题` + f-string 分段 | ✅ 对齐（用 Markdown 分段） |
| 避免 prompt 注入 | `SYSTEM_PROMPT` 有「不要替用户编造」；RAG 检索结果未做隔离 | ⚠️ 可改进：用户输入和 RAG 结果直接拼进 prompt，无注入防护。设计文档 §6.2 提过 prompt injection 防护，未落地 |

**本 spec 范围**：仅记录，不做改造（注入防护属安全范畴，另开 spec）。

### 4.2 Deep Agents 章节编排优化（方法论，非本 spec 实现）

天宫已用 deepagents，但可借鉴得更彻底。来源：[Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)。

Deep Agents 的 plan-and-execute + 虚拟文件系统 + subagent 隔离上下文，天然契合「9 章节生成」。**可借鉴模式**（记为未来方向，非本 spec）：
- **规划 agent**：先产出整份交底书的大纲 + 章节间依赖（如「solution」依赖「problem」）。
- **章节 subagent**：每章节在隔离上下文里起草，只注入相关章节摘要。
- **编辑 agent**：统稿，检查术语一致性。

> 这是 agent 编排层面的优化，属 G6/G7 架构债，不在本 spec。但 P0-3（激活 `guide_questions`）和 P2（eval）是它的前置——没有 eval 无法验证编排改动的收益。

### 4.3 专利写作领域提示词素材（可立即抄进 P0）

来源：[Patent Claim Master prompt 集合](https://www.patentclaimmaster.com/blog/best-practices-for-gpt-prompt-engineering-when-patent-drafting/)、[akonaip 示例](https://akonaip.com/example-prompts/)、学术证据 [FlowPlan-G2P](https://arxiv.org/html/2601.02589v2)（证明结构化生成显著优于 end-to-end prompting）。

**可直接借鉴的提示词策略**（强化 `section_prompts.py`）：

1. **`solution`（技术方案）章节**——补充「问题-方案对应」约束：
   ```
   guide_questions 增加：
   - 这个方案具体解决了「技术问题」章节里的哪个问题？（必须显式呼应前文）
   - 方案的每个关键组件，对应解决哪个子问题？
   completion_criteria 增加：必须显式引用「技术问题」章节的表述
   ```

2. **`claim`（权利要求，未来章节）**——学术证据 FlowPlan-G2P 表明**结构化分步生成**（先独立项→再从属项→再方法项）显著优于一次性生成：
   ```
   goal: 生成结构化的权利要求（独立项 + 从属项 + 方法项）
   output_format: 分三组输出，每组带编号
   ```

3. **`effect`（有益效果）章节**——补充「可量化」约束（当前 `output_format` 已有，但弱）：
   ```
   guide_questions 增加：
   - 每个效果能否给出量化指标或对比数据（如「效率提升 X%」「成本降低 Y」）？
   - 效果与技术方案的哪个组件直接相关？
   ```

**本 spec 范围**：这些素材作为 P0-3 的「弹药」，激活 `guide_questions` 时直接用上。但**不重写 `section_prompts.py` 全文**——先做最小注入，让 eval（P2）验证效果再迭代。

---

## 5. 红线（不可破坏的约束）

| # | 红线 | 来源 |
|---|---|---|
| R1 | **`LLMCallLog` 绝不存 prompt/completion 内容** | 设计文档红线、`llm_call_log.py` 注释 |
| R2 | **不外包数据给 SaaS**（Langfuse 必须自托管；不接 OpenAI 之外的云端观测） | 项目「数据主权 / 成本隔离」理念 |
| R3 | **不引入新 agent 框架**（deepagents 继续） | AGENTS.md 技术栈决策 |
| R4 | **国产 provider 兼容**（智谱/DeepSeek 等，GOTCHAS E3）——任何 structured output 方案必须在多 provider 下验证 | GOTCHAS E3 |
| R5 | **测试用 SQLite 兼容**（GOTCHAS G2）——不引入 PG-only 的新依赖 | GOTCHAS G2 |
| R6 | **提示词改动不引入回归**——必须有 eval 兜底（P2）或至少单测兜底（P0） | 本 spec |

---

## 6. 架构债（记录，非本 spec 实现）

- **G6 两套装配逻辑**：`assemble_messages`（Message 列表）与 `build_system_prompt`（单字符串）。建议未来统一为「装配产出 Message 列表」的单一入口，agent loop 和旧 stream 共用。单独开 spec。
- **G7 无独立 SystemPromptBuilder**：设计图画了但没落地。随 G6 一起重构。
- **Prompt 模板文件化**：本 spec P1 用 Langfuse 管版本，但代码内提示词仍是 f-string。是否引入 Jinja2 / PromptTemplate 抽象，待 P1 落地后视痛点决定。当前判断 f-string 够用（变量少、无复杂条件循环）。

---

## 7. 决策点（需评审确认）

| # | 决策点 | 选项 | 推荐 |
|---|---|---|---|
| **D1** | `with_structured_output` 的 provider 兼容性 | (a) 直接用 LangChain `with_structured_output`（依赖 provider 支持 function calling）；(b) 加 fallback：不支持时退回 prompt + Pydantic 重试解析 | **(b)**：天宫支持多 provider（智谱 GLM 部分型号、DeepSeek），部分可能不支持原生 structured output。加 fallback 保兼容（R4）。**需实测验证**：智谱/DeepSeek 当前主力型号是否支持。 |
| **D2** | 生产环境 Langfuse 是否存 prompt/completion 全文 | (a) 全存（最大化 debug）；(b) 只存 metadata（最严格，对齐 R1）；(c) 配置开关，默认 metadata | **(c)**：给运营选择权。但**默认值必须遵守 R1**——生产默认只存 metadata，开发可开全文。 |
| **D3** | P2 eval 的 LLM-as-judge 用哪个模型 | (a) 用户自己的 chat 配置；(b) 固定用一个强模型（如 GLM-4.6） | **(b)**：eval 需要稳定性，固定模型避免「用户配置弱→eval 失真」。但增加运营成本，需决策。 |
| **D4** | P3 Promptfoo 是否 block merge | (a) warning only；(b) block | **(a)**：先观察一段时间，数据足够再考虑 block。 |
| **D5** | 本 spec 是否现在进入实现，还是先做 P0 验证 | (a) 整体批准后分阶段实现；(b) 只先做 P0（1-2 天）验证方案可行性，再决定 P1+ | **由用户定**——这是本 spec 评审的核心问题。 |

---

## 8. 落地计划骨架（批准后另起 plan）

> 参考 `docs/superpowers/plans/archive/` 现有计划的 TDD 结构。每个阶段独立 plan。

### Phase P0（1-2 天，单 plan）
- T1: 新增 `apps/api/app/ai/schemas/review_schema.py`（`DimensionScore` Pydantic）—— TDD：先写 schema 校验单测
- T2: 改造 `review_service._score_dimension` 用 `with_structured_output`（含 D1 fallback）—— TDD：先写 provider 支持/不支持两条路径测试
- T3: 删除 `_parse_json_response`（或降级为 fallback 路径专用）—— TDD：回归测试
- T4: `build_system_prompt` + `assemble_messages` 注入 `guide_questions` —— TDD：断言 system prompt 含引导问题文本
- T5: 强化 `section_prompts.py` 的 solution/effect 章节（§4.3 弹药）—— TDD：注册表断言
- T6: 全量回归（`uv run pytest`）

### Phase P1（1 周，单 plan）
- T1: docker-compose 加 langfuse 服务
- T2: `apps/api/app/ai/observability.py` + `@observe` 装饰器（含 D2 脱敏）
- T3: 对关键函数加 trace
- T4: 文档（运维 + 隐私说明）

### Phase P2（1-2 周，单 plan）
- T1: golden dataset 收集（脱敏）
- T2: DeepEval 指标实现
- T3: nightly CI job

### Phase P3（按需）
- Promptfoo 配置 + PR gate

---

## 9. 开放问题（待研究，不阻塞本 spec）

1. **国产 provider 的 structured output 支持现状**（2026-07）——D1 的前置调研。智谱 GLM-4.6、DeepSeek-V3 等主力型号是否支持 function calling / json mode？需实测。
2. **Langfuse 自托管的运维成本**——单实例够吗？Postgres 共用还是独立？需 P1 启动前确认。
3. **eval 的 golden dataset 从哪来**——P2 前置。需要 5-10 个真实脱敏交底书。

---

## 附录 A：与现有 spec 的关系

| 现有 spec | 关系 |
|---|---|
| `2026-07-13-tiangong-mvp-design.md` §5.4/§5.5/§6 | 本 spec 是其提示词架构的「工程化补强」，不改设计决策 |
| `2026-07-22-agent-skills-design.md` | 正交（Skill 是动态能力注入，本 spec 是静态提示词工程） |
| `2026-07-27-cross-section-context-design.md` | 本 spec P0-3 在其 `build_system_prompt` 基础上增量改 |
| `2026-07-24-llm-config-redesign-design.md` | 正交（LLM 配置解析，本 spec 不动） |

---

## 附录 B：开源借鉴清单（本 spec 依据）

| 工具/项目 | 用途 | 对应阶段 | 来源 |
|---|---|---|---|
| [Instructor](https://github.com/567-labs/instructor) / LangChain `with_structured_output` | 结构化输出 | P0 | [十库横评](https://simmering.dev/blog/structured_output/) |
| [Langfuse](https://langfuse.com/)（自托管） | 观测 + prompt 版本 | P1 | [NearForm 评测](https://nearform.com/digital-community/prompt-management-systems-compared/) |
| [DeepEval](https://github.com/confident-ai/deepeval) | LLM eval（pytest 风格） | P2 | [Top 5 Eval Frameworks 2026](https://deepeval.com/blog/top-5-llm-evaluation-frameworks) |
| [Promptfoo](https://www.promptfoo.dev/) | 提示词回归 gate | P3 | [Promptfoo × Langfuse](https://langfuse.com/integrations/other/promptfoo) |
| Anthropic context engineering | 方法论对照 | §4.1 | [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) |
| Deep Agents | 章节编排（未来方向） | §4.2 | [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview) |
| FlowPlan-G2P / Patent prompt 集合 | 专利领域提示词素材 | §4.3 | [arxiv](https://arxiv.org/html/2601.02589v2)、[Patent Claim Master](https://www.patentclaimmaster.com/blog/best-practices-for-gpt-prompt-engineering-when-patent-drafting/) |
