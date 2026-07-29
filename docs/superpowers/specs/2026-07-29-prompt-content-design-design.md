# 提示词内容设计：让模型理解用户、高质量输出

> **版本**：v1.0 ｜ **日期**：2026-07-29 ｜ **状态**：待评审
> **作者**：tl.m
> **定位**：天工提示词工程的**主线设计**。覆盖**所有 agent request**，让模型在**每次调用**里最好地理解用户、最高质量地输出。
> **关系**：旧 spec [2026-07-29-prompt-engineering-upgrade-design.md](2026-07-29-prompt-engineering-upgrade-design.md) 降级为本文档的**支撑层附录**（见附录 A）。工程治理（观测/eval/版本）是为本主线兜底的脚手架，不是主角。

---

## 0. 为什么要单独写这份 spec

前两轮产出犯过一个错：把"提示词工程"窄化为"提示词的工程治理"（JSON 解析、观测、eval、版本管理）。那是**支撑层**，不是提示词工程本身。

提示词工程的核心命题是：

> **在每一次 agent request 中，让模型 (A) 理解用户 + (B) 高质量输出。**

这条命题贯穿所有场景（chat / generate / rewrite / caption / review / summary / title）。本 spec 围绕这两条轴重新设计天工的提示词内容。

---

## 1. 核心框架：两条轴

```
┌──────────────── A. 理解用户 ────────────────┐  ┌──────── B. 高质量输出 ────────┐
│ ① 用户此刻想要什么（意图）                    │  │ ⑥ 给模型看「好样子」（few-shot） │
│ ② 用户是谁、什么水平（画像/领域）             │  │ ⑦ 让模型「先想后写」（CoT）      │
│ ③ 对话进行到哪了（状态/进度）                 │  │ ⑧ 专利写作硬规范（领域约束）     │
│ ④ 前文已定了什么（一致性约束）                │  │ ⑨ 怎么算达标（验收标准）         │
│ ⑤ 用户的长稳偏好（记忆）                      │  │ ⑩ 结构化输出（schema）          │
└───────────────────────────────────────────────┘  └────────────────────────────────┘
```

**诊断后，①②⑨ 是当前最大空白，③⑥⑦⑧ 次之，④⑤⑩ 已有但需加强。**（详见 §3）

---

## 2. 现状诊断（代码已核实）

### 2.1 请求体信号极其单薄 ⚠️ 根因

```python
# apps/api/app/schemas/ai.py
class ChatRequest(BaseModel):
    message: str
    chat_source: str | None = None
    conversation_id: str | None = None

class GenerateRequest(BaseModel):
    chat_source: str | None = None   # 连 message 都没有
```

**前端只传 `message` + `chat_source`，所有"理解用户"信号都靠后端从 DB 推断。** 用户意图、用户水平、对话进度——这些前端天然知道（用户点了"生成草稿"按钮 vs 在对话框提问）的信号，**一个都没传过来**。这是 A 轴所有问题的根。

### 2.2 提示词调用点 × 两轴缺口矩阵

| 场景 | 文件:行 | A 理解用户 | B 高质量输出 |
|---|---|---|---|
| **chat 引导对话** | `orchestrator.py:81` → `build_system_prompt` | ❌①② ❌③ ⚠️④⑤ | ⚠️⑧⑨（goal+output_format） |
| **generate 生成草稿** | `orchestrator.py:137` → 同上 | ❌①② ❌③ ⚠️④⑤ | ⚠️⑧⑨ ❌⑥⑦ |
| **rewrite 段落重写** | `orchestrator.py:213` | ❌①② | ❌⑥⑦⑨ |
| **caption 图注** | `api/ai.py:624` | ❌①② | ❌⑥⑨ |
| **review 审查评分** | `review_service.py:112` | N/A | ❌⑩（正则）⚠️⑨ |
| **summary 摘要** | `summary_service.py:39` | N/A | ⚠️⑨ |
| **title 标题** | `conversation_service.py:35` | N/A | ⚠️⑨ |

图例：`❌` 缺失 ｜ `⚠️` 有但弱 ｜ `N/A` 不适用。编号对应 §1 框架。

### 2.3 关键代码级缺口（按危害排序）

**A 轴（理解用户）：**

1. **❌① 意图识别完全缺失**：`chat` 端点把 `payload.message` 直接当记忆检索 query（`context_assembler.py:195`）+ 直接塞进 messages（`orchestrator.py:111`）。模型不知道用户是「想要信息 / 想被引导 / 想 AI 代写 / 想改某段」。后果：用户随便问一句，AI 可能直接甩一大段草稿（或反过来，该代写时却不停追问）。

2. **❌② 用户画像/领域水平缺失**：`SYSTEM_PROMPT`（`context_assembler.py:16`）写死"专业但通俗"，不区分用户是技术发明人（需要把专利术语翻译成大白话）还是专利代理人（可以高密度专业表达）。已有 `user_memory` 机制但只用于写作偏好，没有"专业水平"维度。

3. **❌③ 对话状态/进度感知缺失**：`section.status`（empty/drafting/confirmed，`section.py:21`）后端有，但**没进 prompt**。模型不知道当前章节是"白纸待引导"还是"已有草稿待打磨"。

4. **⚠️④ 前文一致性"只注入不约束"**：`build_system_prompt`（`context_assembler.py:182-184`）把已写章节塞进去了，但**没有约束指令**（如"必须沿用前文术语""必须显式呼应 problem 章节"）。

5. **⚠️⑤ 记忆注入是"裸堆"**：`context_assembler.py:198-201` 检索回来的记忆直接 `f"- {m.content}"` 堆进去，没告诉模型"何时用、怎么用、不要机械复读"。

**B 轴（高质量输出）：**

6. **❌⑥ 零 few-shot**：全局 `few_shot|examples=` 零命中。模型从没见过"一篇好的交底书章节长什么样"。

7. **❌⑦ 零 CoT**：没有任何"先理清技术问题→再设计方案→再核对效果"的推理引导。生成草稿是端到端的。

8. **⚠️⑧ 专利领域约束弱**：`section_prompts.py` 偏通用。缺专利硬规范（如 solution 必须呼应 problem、effect 必须可量化、术语跨章节必须一致、权利要求结构）。

9. **⚠️⑨ `completion_criteria` 全量闲置**：`section_prompts.py` 每章节定义了"完成判定"（如 solution 章节"至少覆盖结构、流程、关键要素三个维度"），**但 `build_system_prompt` 只注入 goal + output_format，`completion_criteria` 从没进过模型**——模型根本不知道什么算"写完了"。这是最直接的"高质量输出"缺口。

10. **⚠️⑩ 审查评分无结构化输出**：`review_service.py:130` 的 `\{[^{}]*\}` 正则连嵌套 JSON 都解析不了（详见附录 A）。

---

## 3. 设计目标与非目标

### 3.1 目标
1. **A 轴：让模型理解用户**——补齐意图、画像、状态三个核心信号（缺口 1/2/3），加强一致性和记忆使用指令（4/5）。
2. **B 轴：让模型高质量输出**——激活 `completion_criteria`（9，ROI 最高）、引入专利领域 few-shot（6）和 CoT（7）、强化领域约束（8）、审查结构化输出（10）。
3. **不破坏现有隐私边界和数据流**——`LLMCallLog` 不存内容红线、不引入新 agent 框架。

### 3.2 非目标
- ❌ 不重构 `assemble_messages` vs `build_system_prompt` 双装配（附录 A §6 架构债，另开 spec）。
- ❌ 不做工程治理（观测/eval/版本）——那是附录 A，本 spec 只在 §6 验收里要求"配合 eval 兜底"。
- ❌ 不动 agent 编排（deepagents plan-and-execute 优化属未来方向，见附录 A §4.2）。

---

## 4. 主线设计：分层落地

> 按"改动面 × 见效"排序，从最快见效的 B 轴开始，再补 A 轴。每个阶段独立、可单独评审。

### 阶段 1：B 轴激活（最快见效，1-2 天）

> B 轴先做：因为缺口 9（`completion_criteria` 闲置）是**改动最小、见效最直接**的——代码现成，只需注入。

#### S1-1：激活 `completion_criteria`（缺口 9）

**改 `context_assembler.build_system_prompt`（L203-207）和 `assemble_messages`（L38-41）**：
```python
parts.append("# 当前正在撰写章节")
parts.append(f"章节标题：【{section.title}】")
parts.append(f"本章目标：{sp.goal}")
# 【新增 S1】引导问题 + 完成标准（知识资产激活）
if sp.guide_questions:
    parts.append("引导要点（可主动追问，不必逐条回答）：")
    parts.append("\n".join(f"- {q}" for q in sp.guide_questions))
parts.append(f"输出格式要求：{sp.output_format}")
parts.append(f"达标判定：{sp.completion_criteria}")  # ✅ 关键：让模型知道"什么算写完"
```

> 注入位置在**章节策略层（中部）**，与 goal/output_format 同层。`completion_criteria` 让模型在生成时有明确的"完成线"，这是最直接的质量提升杠杆。

#### S1-2：强化 `section_prompts.py` 的专利领域约束（缺口 8）

用附录 A §4.3 的专利提示词素材，**最小强化**几个核心章节（不重写全文，只补关键字段）：

| 章节 | 强化点 |
|---|---|
| `solution` | `completion_criteria` 增「必须显式呼应『技术问题』章节」；`guide_questions` 增「方案每个组件对应解决哪个子问题」 |
| `effect` | `guide_questions` 增「效果能否量化（效率提升 X%、成本降低 Y）」「与技术方案哪个组件相关」 |
| `problem` | `guide_questions` 增「这个问题是『技术问题』而非商业问题」（专利法核心区分） |
| `embodiment` | `output_format` 增「至少一个完整实施例，含具体参数」 |

**S1 验收**：`build_system_prompt` 输出含 `completion_criteria`；`section_prompts` 测试不回归；新增断言"达标判定"文本存在。

---

### 阶段 2：A 轴意图与状态（1 周）

> A 轴先补"后端能独立做的"：意图识别 + 章节状态感知。这两项**不需要前端配合**，纯后端 prompt 工程。

#### S2-1：章节状态感知注入（缺口 3，最易）

`section.status` 后端已有，只需注入。改 `build_system_prompt`：
```python
# 章节状态 → 行为模式切换（缺口③）
status_hint = {
    "empty": "本章还是空白。你的首要任务是【引导用户补充关键技术细节】，不要急着代写。",
    "drafting": "本章已有草稿。用户可能在打磨或追问，【根据用户意图决定是补充、修改还是答疑】。",
    "confirmed": "本章已定稿。用户若再次提问，【默认是微调或答疑，避免大改】。",
}.get(section.status, "")
if status_hint:
    parts.append(f"章节进度：{status_hint}")
```
> 这一条直接缓解缺口 1（意图）的一部分——至少模型知道"白纸 vs 草稿"该用不同策略。

#### S2-2：意图识别（缺口 1，核心）

**方案：轻量意图识别，不引入新模型调用，复用现有 chat 流。** 在 `astream_chat` 装配前，用规则 + LLM 混合识别用户意图：

- **规则层（前置，0 成本）**：关键词匹配（"帮我写/生成/起草" → `draft_intent`；"什么是/为什么/区别" → `info_intent`；"改一下/重写/调整" → `edit_intent`）。规则命中则不调 LLM。
- **LLM 层（兜底）**：规则未命中时，在 system prompt 里加一段「意图判断指令」，让主模型在回复前先内隐判断意图并据此调整行为（CoT 式，输出不暴露给用户）。

**实现（`orchestrator.py:astream_chat`）**：
```python
intent = classify_intent(user_input)  # 规则层，返回 draft/info/edit/guide/None
agent = build_agent(db, llm_config=llm_config, user_id=..., section=section,
                    user_input=user_input, intent=intent)  # 透传给 build_system_prompt
```
`build_system_prompt` 按 intent 注入行为指令：
```python
INTENT_HINTS = {
    "draft": "用户想让你【代写草稿】。综合对话和前文，直接产出结构化内容。",
    "info": "用户在【问问题】。简洁答疑，必要时举例，不要借机代写整段。",
    "edit": "用户想【改某段】。先定位要改的内容，按指令最小修改。",
    "guide": "用户在【寻求引导】。用引导式提问帮其厘清思路。",
}
```

> **关键决策点 D1（§6）**：意图识别走"纯规则"还是"规则+LLM兜底"？前者零成本但粗糙，后者更准但可能加延迟/成本。

#### S2-3：用户画像/领域水平（缺口 2）

**渐进方案**：复用现有 `user_memory` 机制，新增一类「画像记忆」（source 标记）。系统主动引导收集：
- 首次对话时，通过 prompt 引导模型识别并 `save_memory`（如"用户是机械领域工程师" / "用户是专利代理人"）。
- `build_system_prompt` 注入画像记忆时，加**表达密度指令**：
  ```python
  if profile_memory:
      parts.append(f"用户画像：{profile_memory}")
      if "代理人" in profile_memory or "律师" in profile_memory:
          parts.append("→ 可使用高密度专利专业术语，无需过度解释。")
      else:
          parts.append("→ 用户是技术发明人，把专利术语翻译成大白话，必要时类比。")
  ```

**S2 验收**：`build_system_prompt` 输出含状态提示 + 意图指令；chat 场景对"代写/问答/改写"三种输入产出明显不同的行为；画像记忆能被 save_memory 写入。

---

### 阶段 3：一致性 + 记忆使用指令（1-2 周）

#### S3-1：前文一致性约束指令（缺口 4）

**改 `build_system_prompt` 已写章节注入段（L182-184）**，从"只注入"升级为"注入+约束"：
```python
if written:
    parts.append("# 已完成章节内容（请保持一致性）")
    parts.append(written)
    parts.append(  # ✅ 新增约束指令
        "一致性要求：① 沿用上文已确立的术语，不要换同义词；"
        "② 本章节若涉及『技术问题』，必须显式呼应其表述；"
        "③ 不要与上文的技术方案矛盾。"
    )
```

#### S3-2：记忆使用指令化（缺口 5）

**改 `build_system_prompt` 记忆注入段（L198-201）**：
```python
if memories:
    parts.append("# 关于这位用户的长期记忆")
    parts.append("\n".join(f"- {m.content}" for m in memories))
    parts.append(  # ✅ 新增使用指令
        "使用规则：这些是用户跨项目的稳定偏好/事实。【自然融入】，不要机械复读；"
        "与当前任务无关的记忆【忽略】；只在影响表达风格或领域判断时启用。"
    )
```

**S3 验收**：system prompt 含一致性约束 + 记忆使用规则；生成内容与前文章节术语一致性提升（需 eval 量化，附录 A P2）。

---

### 阶段 4：few-shot + CoT（2-3 周，需数据积累）

> 这两项需要"好例子"作为弹药，依赖 P2 eval 的 golden dataset（附录 A）。建议 eval 跑通后再做，否则无法验证收益。

#### S4-1：章节级 few-shot（缺口 6）

为每个核心章节准备 1 个**脱敏的优秀范例**（来自 golden dataset），注入 system prompt：
```python
# section_prompts.py 扩展 dataclass
@dataclass
class SectionPrompt:
    ...
    few_shot_example: str | None = None  # 新增：优秀章节范例（脱敏）
```
注入：
```python
if sp.few_shot_example:
    parts.append("# 参考范例（学习其结构与深度，不要照抄内容）")
    parts.append(sp.few_shot_example)
```

> **决策点 D2**：few-shot 放 system prompt（固定，每次都带）还是按需检索（用 RAG 从历史优秀交底书检索相似范例）？前者简单但 token 重，后者灵活但需检索质量。

#### S4-2：生成草稿的 CoT（缺口 7）

**改 `orchestrator.astream_generate` 的 instruction（L167-170）**，从"直接生成"改"分步思考"：
```python
instruction = (
    f"请整理生成本章节【{section.title}】的草稿。"
    f"要求：{sp.output_format}。达标判定：{sp.completion_criteria}\n\n"
    f"思考步骤（不输出思考过程，只输出最终草稿）：\n"
    f"1. 先回顾对话中已确定的技术要点和前文章节的关键信息\n"
    f"2. 梳理本章应覆盖的维度（按 completion_criteria）\n"
    f"3. 检查与『技术问题』『技术方案』等前文章节的一致性\n"
    f"4. 输出最终 Markdown 草稿"
)
```

**S4 验收**：核心章节生成含 few-shot 参考时，结构完整度提升（eval 量化）；CoT 让生成内容的"前文呼应"和"维度覆盖"改善。

---

### 阶段 5：审查结构化输出（缺口 10，1-2 天）

> 这一项就是附录 A 的 P0。单独列是因为它属 B 轴（结构化输出），但逻辑上独立、可先做。

详见附录 A §3 P0：`review_service._score_dimension` 用 `with_structured_output(DimensionScore)` 替掉正则，补单测，加 provider fallback。

---

## 5. 信号流总览（改造后的目标态）

```
前端                          后端                          Prompt
─────────────────────────────────────────────────────────────────────
ChatRequest{                  orchestrator.astream_chat      build_system_prompt
  message,        ────────►    ├─ classify_intent()    ───►  ├─ [L4] 项目元信息
  chat_source,                 ├─ section.status       ───►  ├─ [前文] 已写章节 + 一致性约束 ✨
  conversation_id              ├─ user_memory          ───►  ├─ [记忆] 偏好 + 使用规则 ✨
}                              └─ profile_memory       ───►  ├─ [画像] 专业水平 + 表达密度 ✨
                                                              ├─ [章节] goal + guide_q + format + criteria ✨
                                                              ├─ [状态] empty/drafting/confirmed 行为 ✨
                                                              ├─ [意图] draft/info/edit/guide 指令 ✨
                                                              └─ [角色] SYSTEM_PROMPT 兜底
                              agent loop (deepagents)
                              ├─ rag_search @tool ─────► 知识库检索回流
                              └─ save_memory @tool ────► 画像/偏好沉淀
```
✨ = 本 spec 新增/加强的信号。

**未来可选增强**（非本 spec）：前端显式传 `intent` / `user_level`，省掉后端推断。见 §6 D3。

---

## 6. 决策点（需评审确认）

| # | 决策点 | 选项 | 推荐 |
|---|---|---|---|
| **D1** | 意图识别方案（阶段 2） | (a) 纯规则关键词（0 成本，粗糙）；(b) 规则+LLM 兜底（更准，加延迟/成本） | **(b)**，但规则层先上、LLM 兜底默认关闭，观察 miss case 再开 |
| **D2** | few-shot 注入方式（阶段 4） | (a) 固定范例进 system prompt（简单，token 重）；(b) RAG 按需检索相似优秀章节（灵活，需检索质量） | **(a)** 先做（MVP 用 1 个固定范例/token 可控）；数据多了再升级 (b) |
| **D3** | 是否让前端显式传意图/画像 | (a) 后端全推断（本 spec 现状）；(b) 前端传 intent/user_level 显式信号 | **(a)** 先做后端推断（不动前端契约）；跑顺后再考虑 (b) 优化精度 |
| **D4** | 阶段推进顺序 | (a) 按 S1→S5 顺序；(b) 先做 S5（审查结构化）因为最独立 | **(a)**：S1 见效最快且不动审查；S5 独立可随时插队 |
| **D5** | 本 spec 是否进入实现 | (a) 整体批准分阶段；(b) 先做 S1（1-2 天）验证 | **由用户定** |

---

## 7. 红线与约束

| # | 约束 | 来源 |
|---|---|---|
| R1 | 不在 `LLMCallLog` 存 prompt/completion 内容 | 设计文档红线 |
| R2 | 不引入新 agent 框架（deepagents 继续） | AGENTS.md |
| R3 | 国产 provider 兼容（智谱/DeepSeek，GOTCHAS E3） | GOTCHAS E3 |
| R4 | 不破坏现有 API 契约（`ChatRequest`/`GenerateRequest` 字段不删，只加可选） | 向后兼容 |
| R5 | 每个阶段需 eval 或单测兜底，不盲改 | 与附录 A P2 配合 |

---

## 8. 阶段验收（与附录 A eval 配合）

| 阶段 | 核心验收 | 量化手段 |
|---|---|---|
| S1 | system prompt 含 completion_criteria；solution/effect 章节约束强化 | 单测断言文本 + 注册表测试 |
| S2 | chat 对 draft/info/edit 输入行为分化；状态提示生效 | 人工 spot check + 附录 A P2 的一致性指标 |
| S3 | 生成内容与前文术语一致；记忆不机械复读 | 附录 A P2 的术语一致性 eval |
| S4 | 核心章节结构完整度提升 | 附录 A P2 的章节质量 eval |
| S5 | 审查解析不再失败退化为 50 分 | 单测 + 附录 A P0 |

> **关键**：S2-S4 的质量提升**必须用 eval 量化**（附录 A P2），否则无法证明"高质量输出"真的达成了。建议附录 A 的 P2（DeepEval）与本 spec 的 S2 并行启动。

---

## 9. 落地计划骨架（批准后另起 plan）

每个阶段独立 plan，参考 `docs/superpowers/plans/` 的 TDD 结构。

- **Plan S1**（1-2 天）：激活 completion_criteria + 强化 section_prompts
- **Plan S2**（1 周）：章节状态注入 + 意图识别 + 画像机制
- **Plan S3**（1-2 周）：一致性约束指令 + 记忆使用规则
- **Plan S4**（2-3 周）：few-shot + CoT（依赖附录 A P2 数据）
- **Plan S5**（1-2 天）：审查结构化输出（= 附录 A P0）
- **并行**：附录 A P2（DeepEval eval）与 S2 同步启动，为 S2-S4 提供量化验收

---

## 附录 A：支撑层（原 prompt-engineering-upgrade spec，降级）

> 以下是**工程治理层**——为上面的内容设计主线提供观测、评估、结构化输出兜底。从原 spec [2026-07-29-prompt-engineering-upgrade-design.md](2026-07-29-prompt-engineering-upgrade-design.md) 降级而来。

### A.1 P0 = 本 spec S5（审查结构化输出）
审查评分 `with_structured_output` 替正则。详见本 spec §4 阶段 5。

### A.2 P1：自托管 Langfuse 观测（1 周）
- 补 `LLMCallLog` 不存内容导致的观测黑洞。
- 自托管（Docker），不外包 SaaS（红线 R1/R2）。
- 生产环境脱敏配置（只存 metadata）。
- **与本 spec 关系**：为本 spec S2-S4 的提示词改动提供 debug 能力。**建议在 S2 之前完成 P1**，否则改完 prompt 没法看效果。

### A.3 P2：DeepEval baseline eval（1-2 周）⚠️ 关键前置
- 量化本 spec S2-S4 的质量提升，是它们的**验收依赖**。
- 指标：章节质量（GEval LLM-as-judge）/ 审查一致性（标准差）/ 摘要忠实度 / 幻觉检测。
- golden dataset（5-10 个脱敏交底书）。
- **与本 spec 关系**：S2 启动时 P2 必须同步启动。

### A.4 P3：Promptfoo 回归 gate（按需）
- 提示词改动 PR 触发新旧对比，block/warning 可选。

---

## 附录 B：方法论对照（Anthropic / Deep Agents）

### B.1 Anthropic Context Engineering 对照
| Anthropic 原则 | 天工现状（本 spec 前） | 本 spec 改造 |
|---|---|---|
| 长文档放 prompt 顶部 | ✅ 已对齐 | 保持 |
| 起步最小化、按需扩 context | ⚠️ 全量注入 | S3 后有约束指令但仍全量；未来按相关性裁剪 |
| 结构化 context（分段） | ✅ Markdown 分段 | 保持 |
| 明确的完成标准 | ❌ completion_criteria 闲置 | **S1 激活** |

### B.2 Deep Agents 编排（未来方向，非本 spec）
plan-and-execute + subagent 隔离上下文，契合 9 章节生成。属架构债（附录 C），本 spec 不动，但 S1-S4 是它的前置（没有 eval 验证不了编排收益）。

---

## 附录 C：架构债（记录，非本 spec）

- 两套装配逻辑（`assemble_messages` vs `build_system_prompt`）——建议统一，另开 spec。
- 无独立 `SystemPromptBuilder` 抽象——随双装配统一一起重构。
- Prompt 是否模板文件化（Jinja2）——待 P1 落地后视痛点决定，当前 f-string 够用。
