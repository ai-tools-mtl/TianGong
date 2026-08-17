# LLM 调用与模型选型清单

> 本文件梳理天工后端所有 LLM 调用点、各自用的模型（chat 强模型 / 轻量模型）、
> 触发场景与降级策略。**新增或调整 LLM 调用时，请同步更新本表**，方便团队梳理成本与选型。
>
> 配置入口：admin 后台 `/admin/console/llm`。
> - **Chat 配置**：核心撰写用的强模型（全局 Key，`llm_global_chat_config`）。
> - **轻量任务模型**：高频轻量任务用的便宜/免费模型，典型 GLM-4.7-Flash
>   （`llm_lite_config`，未配时自动回退 Chat 配置，功能不中断）。

## 一、轻量 LLM 的解析链路与回退

所有「轻量任务」经统一入口 `resolve_lite_config(db, user_id)` 解析配置
（`apps/api/app/services/llm_config_service.py`）：

```
轻量任务
  └─ resolve_lite_config(db, user_id)
       ├─ 已配 llm_lite_config（完整）→ 用轻量模型    source="lite"   ✅ 省钱
       └─ 未配 / 不完整 → 回退 resolve_chat_config(user_id)
                            ├─ admin → 全局 chat 配置
                            ├─ 用户 → grant / 自定义 chat 配置
                            └─ 兜底 → env (glm_api_key)
```

> **判定是否真用了轻量模型**：看 admin 是否配了「轻量任务模型」。未配时 B1/B2
> 实际仍走 chat 模型（后端日志 `source=` 字段区分：`lite` / `user` / `global` / `admin` / `env`）。

## 二、已接入轻量 LLM 的服务（B 类）

| 服务 | 文件:行 | 触发场景 | 任务内容 | 调用方式 | 失败降级 |
|------|---------|----------|----------|----------|----------|
| **会话标题生成** | `conversation_service.py:30` | 草稿会话首条对话完成（`/sections/{id}/chat` 流程，`api/ai.py:254`） | 据首条 user+AI 消息生成 ≤12 字标题 | `resolve_lite_config` → `get_llm().invoke()` | LLM 失败/无配置 → 用户消息前 20 字 |
| **章节摘要** | `summary_service.py:35` | 确认章节时 | 生成 100-200 字摘要，供跨章节上下文用 | `resolve_lite_config` → `get_llm().invoke()` | LLM 失败/无配置 → 正文前 200 字 |
| **大纲草稿提取** | `outline_extractor.py:111` `extract_outline` | init 助手每轮对话完成（`/assistant/conversations/{id}/chat` 流程，`api/assistant.py` chat 端点 done 前） | 从对话历史提取 8 章结构化要点（JSON），供右侧文档预览实时刷新 | `resolve_lite_config` → `get_llm().invoke()` | LLM 失败/无配置/JSON 解析失败 → 返回空 dict（预览不更新，不影响对话） |
| **术语抽取候选**（T2） | `term_service.py` `extract_candidates`（`/projects/{pid}/terms/extract`） | 术语面板「从已写章节抽取」 | 从章节正文抽 ≤15 条候选术语（JSON：term/definition/variants/occurrences），不入库由用户勾选 | `resolve_lite_config` → `get_llm().invoke()` | LLM 失败/解析失败 → 空候选 + warning（200 不阻断） |
| **术语一致性检查**（T2） | `term_service.py` `check_consistency`（`/projects/{pid}/terms/check`） | 术语面板「检查全文」（规则路零 token；LLM 路查表外漂移，可选 llm_verify 复核误报） | 漂移检测 + 复核均 JSON 输出 | `resolve_lite_config` → `get_llm().invoke()` | LLM 失败 → `llm_suggestions: []` + warning（规则路不受影响）；无配置 → 跳过漂移检测 |
| **新颖性建议解析**（T2） | `novelty_service.py` `parse_suggestions` | 新颖性评估 done 前（主报告流结束后同步，1-3s） | 把报告「三、差异化撰写建议」段解析为 `[{section_key, text}]` 持久化 | `resolve_lite_config` → `get_llm().invoke()` | 失败 → None（assessment 仅存 content，前端走手动兜底入口） |

## 三、轻量配置的管理端点（不执行任务，仅读写/测试配置）

| 端点 | 文件:行 | 用途 |
|------|---------|------|
| `GET /admin/lite-config` | `admin/console.py:237` | 读取轻量配置（含 `configured` 标志） |
| `PUT /admin/lite-config` | `admin/console.py:248` | 保存轻量配置（写审计 `set_lite_config`，不含 key 明文） |
| `POST /admin/lite-config/test` | `admin/console.py` | 测试轻量模型连通（支持传值/用已存值复检） |
| `POST /admin/lite-config/models` | `admin/console.py` | 拉 provider 可用模型列表 |

## 四、仍用 Chat 强模型、可后续替换为轻量的调用点

这些目前共用 chat 模型，是**潜在的后续替换对象**（替换价值按 token 消耗排序）：

| 功能 | 文件:行 | 特点 | 替换价值 | 备注 |
|------|---------|------|----------|------|
| **审查引擎评分**（B3） | `review_service.py:108` `_score_dimension` | 每维度跑 `CONSISTENCY_RUNS=2` 次自一致性 + `with_structured_output` | ⭐⭐⭐ 最高 | token 消耗最大的点；但涉及结构化输出质量，替换前需评估 |
| **LLM-as-judge**（B4） | `eval/judge.py:64` | 离线 CLI（`python -m app.eval.runner`），线上无端点 | ⭐ 低 | 仅影响离线评测 |

## 五、核心撰写功能（A 类，**不应**换轻量模型）

这些是专利交底书撰写主线，依赖强模型的推理/工具调用能力，保持用 chat 强模型：

| 功能 | 入口 | 说明 |
|------|------|------|
| 对话引导 + 草稿生成 | `ai/orchestrator.py` `astream_chat` / `astream_generate` | 走 deepagents agent loop + 工具（rag_search/save_memory）；崩溃/HITL 中断的 turn 可经 `/messages/{id}/resume` 续跑（`astream_resume`，记账 action=`chat_resume`，同 thread 续跑不重发 input） |
| 段落重写 | `ai/orchestrator.py` `astream_rewrite` | 选中文字 + 指令流式重写 |
| 批量生成项目 8 章初稿 | `ai/init_orchestrator.py` `astream_init_generate` | 裸 `astream_llm` 逐章生成 Markdown |
| 项目初始化冷启动引导 | `ai/init_orchestrator.py` `astream_init_chat` | 引导用户把技术想法说清 |
| 图注润色 | `api/ai.py` `caption_figures` | drawings 章节 AI 看图说话（多模态 vision，model 不支持时降级文字描述）生成规范图注。vision 探测名单 admin 可配（`/admin/console/vision-markers`，`SystemSetting vision_model_markers`） |
| **新颖性评估** | `api/patents.py` `assess_novelty` + `services/novelty_service.py` | 专利检索页「AI 新颖性评估」：对比文件（含 legal_status）× 交底书核心章节 → 流式 Markdown 报告（总体风险/逐篇对比/差异化建议/法律状态提示），完成持久化 `prior_art_refs.assessment`。记账 action=`novelty_assess` |
| **章节针对性修订**（T2） | `ai/orchestrator.py` `astream_revise`（`POST /sections/{sid}/revise`） | 评估建议（审查报告/术语检查/新颖性建议）→ directives → 流式修订稿（最小改动约束 + 术语表优先）。走 agent loop（可用 rag 等工具）但 **checkpointer 显式 None、不带聊天历史、不落库**——候选稿必经 /diff 人工审核。记账 action=`revise`（meta.origin 记来源） |
| **附图生成** | `services/figure_service.py` `generate_figure` | drawings 章节 AI 生成专利附图：`resolve_chat_config` → `get_llm().invoke()` 出 drawio XML → 调 drawio 渲染微服务出 PNG。**非流式同步调用**，记账 action=`figure`（`log_chat_call`）。渲染失败（`ServiceUnavailableError`）不落库，fail-closed。**默认被 HITL 拦截**（`agent_hitl_config`，工具确认后执行） |

## 六、维护说明

- **新增轻量任务**：在第二节加一行；调用 `resolve_lite_config(db, user_id=user_id)`，
  并保留 try/except 降级（轻量任务允许失败兜底）。
- **新增 chat 强模型任务**：在第五节加一行；用 `resolve_chat_config` 或 agent loop。
- **B3/B4 若决定替换为轻量**：从第四节移到第二节，并按 B1/B2 模式接入 `resolve_lite_config`。
- **行号会随代码漂移**，以函数名/文件名为准；如偏差较大请顺手校正。
