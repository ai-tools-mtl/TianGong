# 借鉴机制落地计划（下一波开发）

> 日期：2026-08-27。前置状态：08-25 加固计划批次 1-6 全部完成；批次 0（T2 dogfood
> 人工走查）仍留给用户执行。全量约 1351 测试绿，三 job CI 就位（pytest / tsc+build /
> Playwright 冒烟）。
>
> 本计划来源：对两个开源 harness（deepseek-harness / DeerFlow）的架构调研结论
> （2026-08-27 会话）。**原则：只移植机制，不引框架**——两者均不适合作天工地基
> （dsh 为 TS monorepo，DeerFlow 迁移成本超线性增长），但其可靠性件/纪律件可以
> cherry-pick 进现有代码。排序原则：**成本项优先**（每一笔账单都在计息）→
> 工程卫生 → 安全审计 → 可靠性 → 运维 → 质量。总量约 6 个工作日，
> 批次间无硬依赖，可与内测节奏并行截断。
>
> **v1.1（同日复核修订）**：① 摸底发现 `llm_call_log` 只有 token_prompt/completion
> 两列、**无缓存命中字段**——批次 A 增补「usage 采集链补列」子项（验收数据来源
> 由此落地，见 A-3）；② 记忆中四处标注「未提交」的 WIP（Lightbox 缩放 / 图集重写 /
> 图注降级前端兜底 / diff hunk 复合 key）经 git 核实**已全部进主干**
> （6077e79 / 9ab8b8d / 200e9c4 / 61fcf42），无需设清点批次；③ 微排序：C 先于 D
> （两者都动 resume 链路，先后做完避免返工面）。
>
> **v1.2（第三轮清点增补）**：④ **新增批次 H「AI 输出反馈采集」**——DeerFlow 应用
> 表自带 feedback 能力，摸底确认天工 api/models 全仓零 feedback 痕迹，dogfood 期对
> AI 输出的评价全靠口头转述、无落库信号；⑤ 批次 A 增加 **A-4 单 turn token 预算
> 熔断**——现仅有 120s 时间上限（`tool_timeout.py:30`），token 维度零上限，病态
> 工具循环在时限内敞口烧钱；⑥ F 增加**本地 opt-in 真冒烟层**（有 key 自动启用、
> 无 key 自跳过的 pytest 标记层），修正 v1.0 对「真 API 冒烟」的一刀切否定，CI 定时
> 版仍去范围（口径钉死在新增的「明确去范围」小节）。总量约 6 → 约 7 个工作日。

## 批次总览

| 批次 | 内容 | 预估 | 类型 | 来源 |
|---|---|---|---|---|
| 0（沿承） | T2 修订管线 dogfood 人工走查 | 0.5 天 | 人工 | 08-25 计划遗留 |
| ~~A~~ ✅ | ~~Prefix cache 友好化（静态系统提示词）~~ 已完成 `018f6d5`（2026-08-27，含 A-3/A-4/灵魂测试；实施偏差两处：已写章节+术语表按 EV 分析留在了静态前缀而非计划原文的易变块——会话内通常字节不变且体积大，进前缀按命中价计费更省；README 进度行随批提交） | 1.5 天 | 成本优化 | DeerFlow DynamicContext |
| ~~B~~ ✅ | ~~llm-usage.md 自动生成目录 + CI 门禁~~ 已完成（gen_llm_usage.py，含 B+ SystemSetting 键目录；AGENTS.md 顺带修正 embedding 全局 key 漂移描述）| 0.5 天 | 工程卫生 | dsh 生成目录门禁 |
| ~~C~~ ✅ | ~~HITL 决策审计持久化（log-only）~~ 已完成（hitl_audit_service 双事件 + chat/resume 接线 + 前端 hitl_resolved 徽标；端点级集成由批次 0 dogfood 走查清单覆盖，服务层 8 测试钉死双阶段/幂等/悬挂/不进上下文四契约）| 0.5 天 | 安全审计 | dsh approval 双事件 |
| D | SSE 断线自动接续（复用 resume 语义） | 1 天 | 可靠性 | DeerFlow StreamBridge/join |
| E | doctor 环境体检 + 子进程 env 脱敏守卫 | 1 天 | 运维 | DeerFlow make doctor / env_policy |
| F | eval 基线真跑首建 + 结构校验加固 | 0.5 天+人工 | 质量纵深 | dsh 测试政策 |
| G | Agent Notes 决策记录机制 | 0.5 天 | 流程纪律 | dsh Agent Notes |
| H | AI 输出反馈采集（👍/👎+归因标签） | 0.5-1 天 | 产品纵深 | DeerFlow feedback 表 |

---

## 批次 0（沿承）：T2 dogfood 走查

08-25 计划遗留的用户人工项，清单见原文件。仍先行——抽检暴露的问题按严重度
插入本计划批次之间。

---

## 批次 A：Prefix cache 友好化（本计划核心项）

**问题**：`context_assembler.py:42` 起把全部动态内容（章节摘要、知识库检索结果、
术语表、热门记忆 top-15）拼进 SystemMessage 每轮重建。全局 chat 供应商为 DeepSeek
（自动磁盘级 prefix caching，命中价约为未命中价的 1/10），而检索结果是按 query
变化的——等于每轮请求都把整段 system prompt 打成 cache miss，长对话成本近乎全额。

**目标形态**（DeerFlow `DynamicContextMiddleware` 的静态提示词模式）：

```
system prompt   = SYSTEM_PROMPT + 本章 title/goal/output_format/达标判定/few-shot
                  （同一章节写作期内字节稳定 → 跨轮命中）
history         = messages 表原文逐轮回放（append-only，字节稳定 → 跨轮命中）
当轮 HumanMessage = 用户输入 + <system-reminder>易变上下文块</system-reminder>
                  （摘要/KB检索/术语表/热门记忆快照，每轮只影响尾部新消息）
```

### 设计决策 D1：易变快照「发送时注入、落库剥离」

三个候选里选定：**(b) 落库剥离、仅发送时向当轮消息注入**。
- 否决 (a) 整块落库进消息正文：旧检索快照会随每轮请求重复计费（即使 cache 命中
  也白占 context window），且旧知识滞留历史可能误导后续轮次。
- 否决 (c) 会话首条统一注入：做不到字节稳定——首条注入的是当时快照，第二轮起
  它就是过时信息，要么过期要么刷新（刷新则破坏前缀）。
- (b) 下历史永远 = DB 原文，唯一每轮变化的是尾部新消息，与缓存前缀模型完全对齐。

**注入实现要点**：
- 新增 helper 于 `context_assembler`（`build_system_prompt` 同文件）：volatile 块
  渲染函数返回字符串；`assemble_messages` / agent 路线在**当轮新 HumanMessage**
  content 前包一层 `<system-reminder>...</system-reminder>`。
- 落库与 UI 过滤：消息表只存用户原文。前端聊天面板收到的当轮用户消息照常渲染
  （注入发生在 orchestrator 出口侧、DB 写入侧剥离，具体接缝以现状代码为准——
  若前端经自己的 store 显示本地输入则天然无感，核实一遍即可）。
- **记忆检索顺序稳定化**：热门记忆 top-15 的排序 tie-breaker 固定（如 id 升序），
  防 hit_count 相同时每轮乱序抖动破坏快照稳定。
- few-shot 双装配约定（`:51` 注释）随改造同步核对，别留下双路不一致。
- revise/generate（checkpointer=None）路线收益较小（无跨轮前缀可谈），但统一走
  同一装配路径，不为它们做分支。

**热门记忆偏移的边界**：用户当轮提问触发的按-query 检索本来就轮轮变，这是预期
内的 miss 来源，不值得进一步优化（deer-flow 同样如此），诚实接受。

**A-3 usage 采集链补列**（验收的数据前提，摸底确认现状没有）：
- `llm_call_log` 加 `token_prompt_cached` 列（nullable Integer，双方言迁移）；
- orchestrator usage 捕获点（`orchestrator.py:216-221` 一带）同时兼容两种响应形态：
  DeepSeek 原生 `prompt_cache_hit_tokens` 与 OpenAI 兼容层
  `prompt_tokens_details.cached_tokens`，取到即透传给落库 helper；
- admin stats 的 by_model / by_day 聚合各加一列 cached tokens——批次 2 已有的
  折线图直接多一条序列，「计划级验收指标」一节由此有数可看。

**显式边界**：
- 项目初始化助手（`api/assistant.py` chat/generate）**不做此改造**——generate 单发、
  init chat 是短会话，没有跨轮前缀收益，不为一致性强行套用；文档里写明这例外。
- 连续视图切换激活章 = system prompt 换前缀 = 冷启动一次 miss，属预期行为
  （每章独立会话线程，各自 warm 后仍稳定命中），不做任何「预热」花活。

**A-4 单 turn token 预算熔断**（成本兜底缺口，v1.2 新增）：
现状只有时间上限（120s 总超时 + 分工具超时表），token 维度零限制——病态工具循环
或复读机输出在两分钟时限内可以无节制烧钱。
- orchestrator usage 捕获点（与 A-3 同一处）累计当 turn 的 prompt+completion；
  超阈值后向 loop 注入温和收尾指令（复用现有超时提示事件形态），落库消息标记
  `meta.budget_capped`。
- 阈值走 `SystemSetting agent_turn_token_budget`：默认开启、上限取宽松值（具体
  数字实施时按真实会话 token 分布定，计划不拍死），console 可调可关。宽松误杀率
  ≈0 的前提下兜住失控敞口。

**测试补充（A-4）**：假 usage 流触发熔断、临界不触发、`budget_capped` 标记落库、
收尾指令后正常 done 不算失败。

**测试**：
1. **前缀稳定性断言**（本批灵魂测试）：模拟同 thread 连续两轮，序列化比对第 N 轮
   发送的 `[system, *history]` 与第 N-1 轮完全一致，差异只允许出现在末尾新消息。
2. 注入块不出现在落库 Message.content；不进入压缩器（`context_compactor` 只取
   `{role,content}`，天然满足，补回归断言）。
3. 现有 context_assembler 相关测试迁移适配。

**验收**：实跑一段 6+ 轮真实对话，查 `llm_call_log.token_prompt_cached`（A-3 落列
后）确认命中数随轮次增长且占比可观（观测目标见「计划级验收指标」）；stats 页
折线出现 cached 序列。

---

## 批次 B：llm-usage.md 自动生成目录 + CI 门禁

**问题**：AGENTS.md 要求「新增/调整 LLM 调用时同步更新 docs/llm-usage.md」——
纯手工维护的 catalog，必然漂移（这正是 dsh 用「生成目录 + freshness 门禁」消灭的
一类问题）。

**范围**：
- `apps/api/scripts/gen_llm_usage.py`：AST 扫描 `app/` 下所有 `resolve_chat_config`
  与轻量模型调用点，提取所在函数名/文件行号/用途注释，生成 Markdown 表格区块，
  插入 `docs/llm-usage.md` 的定界符之间（`<!-- BEGIN AUTO --> / <!-- END AUTO -->`）；
  区块外的手写章节（触发场景描述、降级策略叙述）保持手工。
- `--check` 模式：生成结果与现存文件不一致即 exit 1（可再生成就 regenerate，
  PR 里不可重新生成的文档改动才允许 reject）。
- CI（ci.yml backend job）追加一步 `python scripts/gen_llm_usage.py --check`。

**明确不做**：从调用点反推「触发场景/降级策略」这类叙事性内容——它们本来就是
人写的判断，自动化只会产出 slop。

**测试**：scanner 的 AST 提取单测（嵌套调用/别名 import/测试目录排除）。

**可选扩展 B+（默认做，~0.25 天）**：同一套生成器机制顺手覆盖 **SystemSetting 键
目录**——配置键现已散落六七处服务文件（`vision_model_markers` /
`agent_hitl_config` / `llm_global_chat_config` / `llm_global_embedding_config` /
`figure_style_presets` / 余额告警两个键 / 支持码有效期等），扫 `SystemSetting`
key 常量定义处生成附录表（键名、默认值、 owning service、console 哪个页面用）。
配置类事故排查（「这个键叫什么来着」）是目前真实痛点。CI 门禁同机制复用，
增量成本几乎为零。

---

## 批次 C：HITL 决策审计持久化（log-only 双事件）

**摸底事实**：HITL approve/reject 决策目前**没有任何持久化**——只作为 resume
输入瞬态进入 langgraph checkpoint；好的一面是它天然不会进入后续轮次模型上下文
（history 从 messages 表重建，压缩器只取 role/content，`context_compactor.py:157`）。

**借鉴点**（dsh approval：每次 ask/decide 写一对仅入日志、不进模型转录的事件）：
我们要补的就是「入日志」这一半。

**范围**（v1.1 起按 dsh 原型采「双事件」形态：ask 与 decide 各留痕）：
- 新表 `hitl_decisions`：`id / message_id(interrupt 所在 turn 的 user 消息) /
  tool_name / asked_at / decision(approve|reject|**pending**) / decision_note /
  decided_by(user_id) / decided_at`。
- **两段写入**：① agent loop 抛出 interrupt 时（`orchestrator.py:235-238` 捕获点
  一带，fail-open 容错——审计写失败不阻断流）先落一行 `pending`（asked_at 有值）；
  ② resume 端点校验通过后（`ai.py:457` 附近）更新该行为 approve/reject + 理由 +
  时间。这样**用户从不回复的悬挂审批也有完整痕迹**——只记 decided 的半套实现
  看不见这类案例，而它们恰是审核卡点的真实信号。
- 同 message_id 的 pending 行更新而非新插； resume 前置的可续性预检失败等异常
  分支保持 pending 不动（如实反映无人处置）。
- 回读：聊天面板时间线复用 `meta.tool_events` 回放通道，interrupt 卡片旁展示
  「待确认/已批准/已拒绝(+理由)」状态徽标（数据从新表拉，merge 进现有 events
  合并逻辑 `ai.py:488-490` 附近）。
- **绝不进入模型上下文**：不加任何发送侧引用；上表仅供审计与 UI。写一条单测钉死
  「持久化不影响 derive/history 序列化」（防未来有人顺手把审计塞回 prompt）。

**测试**：ask/decide 两段写入单测（含 pending 悬挂不阻塞、重复 decide 幂等）、
SQLite 双方言迁移、admin 维度查询端点可选（内测期先不上查询页，只落数据）、
契约测试 resume 响应不受影响。

---

## 批次 D：SSE 断线自动接续（纯前端 + 微量后端）

**摸底事实**：服务端 resume 语义已经完备（崩溃续跑 input=None 从 checkpoint 整段
重放 + `collect_final_answer` 权威全文 `orchestrator.py:438-456` + 可续性预检
`ai.py:467-476`）；断连时服务端捕获 `asyncio.CancelledError` 落库 `meta.incomplete`
（`ai.py:354-364`）。缺口只在**前端遇到网络层断开时的行为**：`api.ts:_consumeSSE`
的网络异常直接抛裸 TypeError → 面板当通用错误 toast，用户只能手动找「继续」按钮。

**为什么不做 StreamBridge/后台任务解耦**（DeerFlow 的 producer/consumer + join 端点）：
run 任务脱离响应生命周期需要管任务注册表/孤儿回收/TIANGONG_TESTING 守卫/
多 worker Redis 缓冲——工程量为周级，而内测期最常见的痛点只是「网断一下半截稿子
要手动抢救」。用已有的 resume 语义在前端闭合，一天内完成，正交不堵死将来升级。

**范围**：
- **错误三分类**（`api.ts` 各流方法，摸底确认 `_consumeSSE` 在 `api.ts:1253-1316`）：
  ① AbortError = 用户主动停；② SSE `error` 事件 = 业务错（现有 throw ApiError
  行为保留）；③ fetch reader 流中途抛出的裸 TypeError / network error = **网络断开**，
  打标记传出——第三类是本批唯一新语义。
- `ai-chat-panel.tsx`：捕获网络断开标记且非主动停止时——自动调一次现有 resume 流程
  接续（复用 incomplete 消息的继续按钮链路，面板提示「连接中断，正在恢复…」）；
  自动恢复失败再降级 toast + 显式「重新连接」按钮（手动兜底，不做无限重试——
  服务端不可达时静默循环重试只会烧日志）。
- **顺手统一解析器**：`streamAssistantGenerate` 自带独立 reader 循环
  （`api.ts:511-561`），与 `_consumeSSE` 双轨并存是漂移隐患——收编为同一实现后
  它天然也获得断线标记。改动控制在 api.ts 内部签名兼容层，调用方无感。
- 仅聊天主链路先启用，revise/novelty 等短流维持现状（断了重新发起成本低）。
- 后端零协议变更。已知代价如实记录：checkpoint 重放会对被中断节点的已产 token
  重复计费一次——比整套后台任务架构便宜得多，值。
- 与批次 C 的接缝：C 先做（同在 resume 链路区域），D 的自动恢复顺带让 C 落的
  审计数据更完整（恢复路径也会留下痕迹）。

**测试**：E2E（Playwright，接入现有第三 job）：route.abort 中途掐断 → 断言自动
出现 resume 请求且最终 done 渲染完整全文。前端单测对错误分类函数。

---

## 批次 E：doctor 环境体检 + 子进程 env 脱敏守卫

**动机**：内测部署排查靠人肉翻容器日志；两微服务软依赖（NLI fail-open /
drawio fail-closed）行为不同，出问题时最花时间的是分清「谁挂了、挂了要不要紧」。
借 DeerFlow `make doctor` 形态落地一条命令。

**doctor 脚本**（`apps/api/scripts/doctor.py`，`python -m scripts.doctor`）：
检查项与**预期动作分级**（关键：报告要说清依赖的失效语义）：
| 检查 | 硬度 | 失败处置 |
|---|---|---|
| postgres 可达 + alembic head 一致 | 硬 | exit 非零 |
| minio bucket 可写探针 | 硬（附件链路） | exit 非零 |
| drawio :8001 健康 | **fail-closed 标注**：挂了则附图生成整体 503 | 黄字警告 + exit 非零（部署完整性口径）|
| NLI :7999 健康 | **fail-open 标注**：挂了仅降级 neutral 合并不误删 | 绿字提示可继续运行 |
| 全局 chat/embedding 配置可解析（默认 provider 拼装能否走到 httpx 层）| 软 | 提示未配置 |
| 磁盘剩余 / 数据卷大小 | 信息 | 打印 |

- 结果输出文本报告；`--json` 供部署文档回写。
- 明确守卫：所有探测网络操作带 `TIANGONG_TESTING` 跳过（老规矩，docker 未起时
  别让测试套卡死）。

**env 脱敏守卫**（一行事 + 规矩）：
- `app/sandbox/docker_runner.py` 增加模块级 helper：凡未来向 `containers.run(...)`
  传 `environment=` 的调用必须先过 `sanitize_env()`（剥离 `*KEY*/*SECRET*/*TOKEN*
  /*PASSWORD*` 类键）。当前 runner 未传 env 参数（风险本来不存在），helper 先行
  落地并在 GOTCHAS 开新条目立规矩：**新增子进程/docker 执行入口必须过脱敏**。
  BYOK 密钥服务端加密托管，这条是未来的泄漏面保险丝。

---

## 批次 F：eval 基线真跑首建 + 结构校验加固

**摸底事实**：`review_baseline.py` 模块与 ±15 容差逻辑齐备且有单测；缺的只是
(a) `app/eval/baselines/` 首跑产物从未生成——CLI 需要 `resolve_chat_config(db,
None)` 有值，否则 exit 1；(b) 评分解析健壮性。这也是 08-26 记忆里的两项待办之一。

**范围**：
- **真跑首建**（用户配合项，与「DeepSeek balance 实测」合并同一个时段做，token
  成本极小）：配好全局 chat → `python -m app.eval.review_baseline` → 人工确认
  首跑分数合理 → 提交 `review_baseline.json`。
- **结构校验加固**（dsh「验证世界而非自我汇报」原则——不信 judge 自述，验产物）：
  review 管线评分输出增加 schema 级校验（维度键齐全、分值域内、必填建议字段存在），
  校验失败的样本计入失败而非静默 0 分混入基线。现有括号配平解析保留为前置容错。
- 使用方式写入 AGENTS.md 的演进流程：改 rubric prompt / 换模型 / 调自一致性参数
  后手动跑一次确认漂移。
- **本地 opt-in 真冒烟层**（v1.2 新增，dsh「inference is cheap here」的中间档）：
  `tests/real_api/test_chat_smoke.py` 带 `real_llm` pytest 标记——检测到全局 chat
  配置可解析才运行、否则 skip。断言的不是分数而是**结构合法性**：流式产出非空、
  用法 payload 字段齐全（连带 A-3 的 cached tokens 采集有真数据回归）、图注/审查
  等短链路各一条最小调用。mock 单测验证逻辑，这层验证「真端点没坏」；CI 无凭据
  自然全跳，零维护成本。约 0.25 天。

---

## 批次 G：Agent Notes 决策记录机制

**动机**：GOTCHAS 记「踩了什么坑」，归档 plans 记「做了什么」，唯独缺**决策当时的
备选方案记录**（为什么这么选、放弃了什么）——本批机制来自 dsh，也是面试深挖时
最有说服力的一手材料来源。

**落地形式（裁剪版，不搬它的 CI 门禁全家桶）**：
- 目录约定 `docs/notes/{proposed,implemented,rejected}/YYYY-MM-DD-主题.md`，
  骨架固定四段：Problem / Decision / **Alternatives considered（强制至少一条）** /
  Consequences。
- Status 行声明生命周期，文件夹与 Status 互验；rejected 保留理由，implemented
  归档冻结不改（历史修正另开新 note 引用旧的）。
- 极简 lint 脚本并入 ci.yml frontend job 旁边（路径模式 + 必填段落存在性检查，
  ~50 行），防止骨架腐化但不追求 dsh 的封闭分类集那套强度。
- 第一篇示范 note：就写本计划的 D1 决策（prefix cache 注入策略三选一的取舍）。

**AGENTS.md 补一句**：「非 trivial 架构取舍建议留 Agent Note」，引导而非强制。

**与既有目录的分工约定**（防双头维护）：`docs/superpowers/plans/` 记「做什么、
怎么做、批次拆解」；notes 只记「为什么这么选、放弃了什么」。一份决策只住一处：
计划里写了取舍理由的（如本计划 D1），note 引用计划不复制全文。

---

## 批次 H：AI 输出反馈采集（v1.2 新增）

**动机**：DeerFlow 共享应用表自带 `feedback`，而天工 api/models 全仓零反馈痕迹。
dogfood/内测期用户对 AI 输出的评价目前只能口头转述——没有任何落库信号能回答
「哪些环节的产出质量最差」。这也是批次 F 未来样本池（samples.py）的天然蓄水处。

**范围**：
- 新表 `message_feedback`：`id / message_id FK(answers) / user_id /
  rating(good|bad) / tags[错字|事实|格式|没帮助] 多选 / note 可空 / created_at`；
  同 message 同 user **upsert 覆盖**（改主意不留历史——内测期信号新鲜度优先，
  简化统计口径）。
- 前端：AI 消息尾部 👍/👎；点 👎 展开标签快选 + 可选备注提交；提交后本条锁定
  显示当前评价。放置于聊天面板消息气泡组件，revise/diff 候选稿等非持久化内容
  不采集（候选稿本来要人工 diff 才落地）。
- admin console stats 页加反馈卡：好坏比、坏评按 action/章节类型聚合 top；
  内测期够用，不做逐条审核台。
- 与 eval 衔接只留注释锚点：坏评聚集的消息是未来 samples 候选，人工挑选入库，
  **不自动搬运**。

**明确不做**：反馈自动触发审查、反馈驱动 prompt 自动调优、跨用户公开聚合页
（内测用户少，隐私面收窄优先）。

**测试**：upsert 幂等（重复评价覆盖不插新行）、鉴权（他人 message 404）、
tags 合法值校验、admin 聚合端点 admin-only、前端 E2E 一条（冒烟 job 里补）。

---

## 并行用户项（不占用开发窗口）

| 项 | 说明 |
|---|---|
| T2 dogfood 走查（批次 0） | 清单见 08-25 计划；问题按严重度插队 |
| DeepSeek balance 实测 | 余额告警探测端点（4507f07）拿真实响应结构核一遍假设 |
| eval 基线真跑 | 与上项同时段（见批次 F） |

---

## 明确去范围（v1.2 新增，口径钉死）

| 项 | 原因 |
|---|---|
| CI 定时跑真 LLM 冒烟 | CI 无生产凭据、成本管理复杂；真 API 冒烟降级为批次 F 的本地 opt-in 层 |
| 反馈驱动的 prompt 自动调优 | 人在环：反馈是信号不是控制器，自动调优出事没有回滚故事 |
| read-before-write 类写入前内容哈希门 | 天工 agent 无直接文件写路径（编辑走保存接口、正文走 apply-diff），无适用场景 |

---

## 规划候选池（本计划不排期，触发条件各自标注）

| 项 | 触发条件 | 备注 |
|---|---|---|
| 后台 run 任务解耦 + join 端点（StreamBridge 模式） | 内测反馈断线频率高，批次 D 的 resume 补救体验不够 / 多 worker 部署启动 | 那时再付周级成本 |
| goal-runner 项目级一键成稿（隐藏 HumanMessage 续跑 + 无进展熔断 + 预算上限） | 内测用户明确表达「希望 AI 自己推着各章走」 | DeerFlow /goal 形态；熔断器设计直接抄 |
| 大工具输出外溢 spill（检索结果落存储+locator） | novelty/检索类工具输出频繁顶到截断阈值 | 替代粗暴截断 |
| skills 激活式注入 + allowed-tools 白名单 | skill 数量增长到提示词常驻成本可观 | MinIOSkillStore 地基已在 |
| alembic 混合 bootstrap（advisory lock / safe helpers / 排除引擎自管表） | 交付环境出现并发迁移或存量库疑难 | 现 init_db 幂等方案尚可支撑 |
| support-bundle 脱敏排障包（一键收集日志/版本/配置摘要出 zip + AI issue 草稿） | 远程用户报障次数多到人工问询成本高 | doctor（批次 E）是它的前置件 |
| 结构化澄清中断（agent 主动 ask_user_question 卡片） | init 阶段信息不足导致幻觉假定的报障出现 | HITL `interrupt_on` 基建已通，只需问题 schema + 确认卡片新类型 |
| 输入转向 steering（agent 忙碌时输入排队下轮注入，而非禁用） | 内测用户抱怨「正在生成时插不上话」体验差 | dsh inbox 双队列 / DeerFlow turn-stopping 协商两种实现可参考 |
| MCP 数据源扩展位（langchain-mcp-adapters 薄集成） | 需要接外部数据源生态（如官方专利库查询）时评估 | 只当工具接入层用，不引运行时框架 |

---

## 计划级验收指标（v1.1 新增——本计划做完怎么算成功）

计划粒度的观测目标，**全部是观测指标非硬门禁**（硬门禁在各批次测试与 CI）：

| 指标 | 来源 | 目标口径 |
|---|---|---|
| 缓存命中率 | by_day 折线 cached/prompt 比值（A-3 落列后） | 多轮 warm 会话 ≥50%；init/单发场景不计入 |
| 实际账单对比 | 批次 2 的按天 token 序列，A 上线前后各一周 | prompt tokens 总量显著下降（同一使用强度粗比） |
| 断线恢复成功率 | 批次 D E2E + 内测期实际断线的用户反馈 | 中途掐流场景 E2E 稳定绿；真机「无感续写」为主观达标 |
| 审计完整性 | hitl_decisions 行数 vs interrupt 发生数 | 两者相等（含 pending 悬挂），零漏记 |
| 部署体检基线 | doctor 在部署机一次全绿输出回写 deploy 文档 | 硬依赖全绿 + 两软依赖分级标注正确 |

**运行时观察项**（暂不行动，留证据再定，v1.2 登记）：
- **压缩后工具产物记忆丢失**：压缩器只保留 role/content——长会话被压缩后，模型
  可能忘记「本章已生成过图N」而重复发起 generate_figure。若内测报此类案例，最小
  修法是批次 A 的易变注入块里补一行「当前附图清单」事实（不动压缩器）。
- **工具循环重试**：120s 时间上限 + A-4 token 熔断已是双保险，专门 LoopDetection
  不做；A-4 上线后若仍频见预算打满，再加重复调用指纹识别。
- **压缩触发条件压力自适应**：现有 BudgetConfig 结构够用，dsh 的 pressure 触发算
  优化不算缺口。

---

## 批内注意事项（跨批次通用）

- 所有新增启动期/脚本网络调用带 `TIANGONG_TESTING` 跳过守卫（老规矩）。
- 新表沿用 SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")` 双方言约束（G2）。
- 每批次独立原子提交；完成一批更新 README「开发进度」；涉及新 LLM 调用点时同步
  llm-usage.md（批次 B 之后此项由生成器兜底）。
- 批次 A 动的是所有 AI 链路的公共装配层，**排在批次 C/D/E 前**完成，其后的批次
  都受益于稳定后的装配测试网。
