# 天工 (TianGong) — MVP 设计文档

> AI 驱动的专利交底书撰写智能体
> 从技术交底到专利申请文件，巧夺天工。

- **文档版本**: v1.5（新增 LLM Key 管理与自定义配置）
- **创建日期**: 2026-07-13
- **状态**: 待评审
- **作者**: tl.m + ZCode
- **修订记录**:
  - v1.0 (2026-07-13): 初版
  - v1.1 (2026-07-13): 补充审查发现的 3 严重 + 7 重要遗漏（模板编号解析方案、附图多模态边界、交底书元信息、纯手写路径、summary 生成时机、导出渲染器、资源级授权、异步任务恢复、自动保存、模板变更语义）
  - v1.2 (2026-07-13): 纳入全生命周期愿景（事务所协作/审查答复/归档），新增知识库与 RAG 架构（pgvector + embedding），MVP 实现基础 RAG，Project 预留 stage 字段
  - v1.3 (2026-07-13): 引入双框架（LangGraph 编排 + LlamaIndex RAG），审查与评分纳入 MVP P0，新增确定性评估管线（Rubric + 自一致性 + 跨会话记忆）根治评分跨对话不稳定，新增三套自定义能力（审查标准覆盖式 / 知识库·技能增量式）
  - v1.4 (2026-07-13): 新增管理员角色（MVP 做 C 系统运维版，数据模型预留 A/B 演进），明确角色权限矩阵与数据可见性红线（用户私人数据默认不可见）
  - v1.5 (2026-07-13): 新增 LLM Key 管理与自定义配置（管理员全局开关 + 用户可覆盖 + 任意 OpenAI 兼容 Provider），新增 SystemSetting 表与 UserLLMConfig 实体，明确 Provider 解析优先级
  - v1.5.1 (2026-07-14): ⚠️ **实现现状校正**。v1.3 计划的 LangGraph + LlamaIndex 双框架在落地中调整，本文档原描述保留作为设计意图，差异见下方「实现现状」说明

---

> ## ⚠️ 实现现状（2026-07-14 校正）
>
> v1.3 设计规划用 **LangGraph（编排）+ LlamaIndex（RAG）** 双框架，但实际落地有调整。下文保留原设计描述作为意图参考，阅读时请注意以下差异：
>
> | 维度 | 原设计（v1.3） | 实际实现（MVP 已落地） |
> |---|---|---|
> | **RAG 检索** | LlamaIndex | **LangChain `OpenAIEmbeddings` + pgvector 直连**。原因：LlamaIndex 的 `OpenAIEmbedding` 强制校验模型名，不支持智谱等国产 embedding 模型（详见 GOTCHAS E3） |
> | **AI 编排** | LangGraph StateGraph + Checkpoint + HITL + PostgresSaver + Store | **LangChain `ChatOpenAI` + 手搓编排器**（`app/ai/orchestrator.py`，Python generator 流式 yield）。章节状态推进用 Section.status + 服务层逻辑实现，未用 StateGraph。HITL 确认、跨会话记忆、Checkpoint 恢复**尚未用框架落地** |
> | **LLM/Embedding** | LangChain ModelAdapter / init_chat_model | **`langchain_openai.ChatOpenAI` + `OpenAIEmbeddings`**，经 OpenAI 兼容协议接 GLM |
> | **依赖** | — | `pyproject.toml` 装了 `langgraph` 但源码**零 import**（预留，未启用）|
>
> **结论**：MVP 的 AI 能力（撰写流式、审查 Rubric 评分、RAG 检索注入）均已用 LangChain 实现，功能完整；LangGraph 带来的 Checkpoint 断点恢复 / HITL 暂停 / 跨会话 Store 记忆等「框架红利」暂缺，如需引入后续可作为增强项。本文档涉及 LlamaIndex/LangGraph 的具体描述（尤其第 4.2 技术选型表、第 5 章 AI 编排、第 10 章 RAG 架构、附录 A 决策记录）请结合本说明阅读。

---

## 1. 产品定位与边界

### 1.1 一句话定位

**「天工」是把技术灵感变成规范专利交底书的 AI Agent**：从一个模糊的灵感出发，AI 逐章节引导撰写技术交底书、用确定性评估管线稳定地审查评分，并将每一件专利沉淀为可检索、可复用的知识库——让每一次撰写都比上一次更聪明。

> **MVP 聚焦**：打透"灵感 → 完整交底书 → 稳定审查评分"这一段，并建立知识库与记忆基础设施，让交底书写一份、审一次都稳定可复现。

> **核心质量目标**：审查评分**跨对话稳定可复现**——同一份交底书无论何时、在哪个新对话里审查，评分都应一致（不漂移）。这是天工区别于通用 agent 的关键。

### 1.2 目标用户

- **MVP**: 个人发明人 / 工程师 / 研究员（有技术灵感，不擅长把灵感整理成规范的交底书）

### 1.3 「是」什么（MVP 范围内）

- 单人使用的 Web 应用（登录后进入个人工作台）
- 从「灵感描述」到「结构化交底书草稿」的端到端引导
- 每份交底书可在线富文本编辑、多版本保存、导出 Word/Markdown
- **交底书元信息**管理：发明人、申请人、单位、联系方式、日期、关键词（作为导出抬头的来源）
- **模板模块**：用户上传 Word 样本，系统异步解析为可复用的格式模板（章节结构 + 样式 + 编号），创建项目时套用
- AI 在每个章节提供三种能力：**引导提问、内容生成、段落重写**
- 支持「AI 引导」与「纯手写」两条路径——用户可跳过对话直接在编辑器撰写（详见 2.2.2）

### 1.4 「不是」什么（MVP 明确排除）

| 排除项 | 说明 |
|---|---|
| 真实专利检索 | 留接口（`SearchService` 抽象 + `prior_art_refs` 字段），后续集成 |
| 法律状态判断 / 新颖性评估 | 属专业服务，不做 |
| 正式专利申请文件撰写 | 产出物是**交底书**（给代理人的技术输入），非法律文件 |
| 移动端 | 桌面 Web 优先 |
| 多语言 | MVP 仅中文 |
| AI 图像理解（多模态） | MVP 的 LLM 仅用文本能力。附图章节中，用户上传图片仅做存储展示，并用文字描述图的内容，AI 基于描述 + 上下文润色图注（详见 9.5） |
| AI 绘图 / 附图绘制 | 不提供绘制工具，不生成图，仅支持上传 |

### 1.5 成功标准（MVP）

1. 一个完全不懂专利写作的用户，能用天工在 **1~2 小时内**产出一份「代理人看了不摇头」的交底书
2. 交底书覆盖标准章节（由模板定义；系统默认模板含：发明名称、技术领域、背景技术、发明目的/技术问题、技术方案、有益效果、附图说明、具体实施方式）
3. 用户可上传自有 Word 模板，系统解析后可套用其结构与样式
4. 用户可随时中断、回来继续，不丢失上下文
5. **写完的交底书自动沉淀进个人知识库；撰写新交底书时，AI 能检索并参考相似的历史案例（基础 RAG）**

### 1.6 全生命周期与知识库愿景

天工陪伴发明人把技术灵感整理成规范的专利交底书，并将其沉淀为可检索、可复用的知识库。**MVP 聚焦阶段①（交底书撰写）与阶段②（归档+知识库）**，架构从开始就为知识沉淀设计，避免后续推倒重来。

#### 生命周期阶段

```
灵感
  │
  ▼
┌─────────────────────────────────────────────────┐
│ 阶段① 交底书撰写        ← MVP 实现               │
│  AI 引导 + 模板 + 富文本，产出结构化交底书        │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ 阶段② 归档 + 知识库     ← 持续沉淀（MVP 已起步）  │
│  · 案件归档（交底书全过程）                       │
│  · 自动抽取知识：技术方案、写作模式               │
│  · 向量化索引，支持语义检索                       │
└──────────────────────┬──────────────────────────┘
                       ▼
              回流：知识库反哺新一轮撰写
```

#### 「记忆」的三层含义（明确区分）

| 层 | 是什么 | MVP 落地 | 后续 |
|---|---|---|---|
| **知识库 (Knowledge Base)** | 沉淀的历史案例/文档，可语义检索（RAG） | ✅ 交底书向量化入库 + 写新交底书时检索相似案例 | 扩展到申请文件、答复策略 |
| **Agent 记忆 (Memory)** | agent 跨会话的用户画像/偏好 | ❌ MVP 不做 | 记住写作风格、技术领域、术语习惯、事务所偏好 |
| **长期文档归档** | 案件全生命周期的文件版本化存储 | 🟡 部分（附件 + 版本快照） | 完整案件归档 |

#### MVP 的边界（再次明确）

- **实现**：阶段① 完整 + 阶段② 的知识库基础（交底书向量化 + RAG 检索）
- **架构预留**：Project 的 `stage` 字段（MVP 固定 `disclosure`）、知识库的数据结构（可扩展到任意文档类型）、RAG 检索层（可扩展到任意检索源）
- **不做**：agent 长期偏好记忆

---

## 2. 功能模块

### 2.1 模块总览

```
┌─────────────────────────────────────────────────────┐
│  第一层：入口与组织                                   │
│  ├─ 用户认证（注册/登录/登出）                        │
│  ├─ 工作台（项目列表）                                │
│  └─ 项目（一份交底书）                                │
├─────────────────────────────────────────────────────┤
│  第二层：模板模块（核心，可复用）                      │
│  ├─ 上传 Word → 异步解析                              │
│  ├─ 模板管理（列表/预览/重命名/删除/设默认）          │
│  └─ 创建项目时选择模板                                │
├─────────────────────────────────────────────────────┤
│  第三层：核心创作流程（产品心脏）                      │
│  ├─ 章节大纲导航（进度可视化）                        │
│  ├─ 严格顺序推进（完成当前章节解锁下一章节）          │
│  ├─ AI 引导对话（每章节独立）                         │
│  └─ AI 生成章节草稿                                   │
├─────────────────────────────────────────────────────┤
│  第四层：编辑与产出                                   │
│  ├─ 富文本编辑器（Tiptap）                            │
│  ├─ 段落 AI 重写（选中→重写/扩写/精简/纠错）          │
│  ├─ 跨章节上下文（AI 写后文能引用前文）               │
│  ├─ 章节版本快照                                      │
│  ├─ 全篇预览                                          │
│  └─ 导出（Word/Markdown，套用模板样式）               │
└─────────────────────────────────────────────────────┘
```

### 2.2 核心创作流程

#### 2.2.1 章节结构：模板驱动

- 章节结构**不再硬编码固定 8 阶段**，而是由所选模板决定
- 系统内置一个**默认标准模板**，含经典 8 章节：发明名称、技术领域、背景技术、发明目的/技术问题、技术方案、有益效果、附图说明、具体实施方式
- 用户上传的自定义模板可有任意章节结构

#### 2.2.2 推进规则：严格顺序

- 章节按模板定义的顺序线性推进
- **完成当前章节才能解锁下一章节**（章节 `status` 从 `empty` → `drafting` → `confirmed`）
- `confirmed` 的判定**与是否经过 AI 无关**：只要内容非空且用户主动点「确认完成」即可。这样支持两条路径：
  - **AI 引导路径**：`empty` → 进入对话（`drafting`）→ 生成草稿 → 用户确认（`confirmed`）
  - **纯手写路径**：`empty` → 用户直接在编辑器写（`drafting`）→ 用户确认（`confirmed`）
- 已确认的章节**可以随时返回修改**。MVP 简化：返回修改不强制级联重置后续章节状态（避免复杂的级联逻辑），用户自行判断是否需要重新审视后续内容。返回修改会重新进入 `drafting`，改完重新确认

#### 2.2.3 单章节内的交互单元

每个章节是一个统一的交互单元，包含：
- **左侧大纲**：所有章节列表，当前章节高亮，已完成章节打勾
- **中间编辑器**：当前章节的富文本内容，**防抖自动保存**（详见 13.4）
- **右侧 AI 对话**：本章节独立的对话流（可折叠/跳过，对应纯手写路径）
- **底部操作**：「生成本章草稿」「确认完成进入下一章」

---

## 3. 数据模型

### 3.1 实体关系

```
User (1) ──── (N) Project ──── (1) Template
       │            │
       │            ├──── (N) Section ──── (N) Message
       │            │                  └── (N) SectionVersion
       │            └──── (N) Attachment
       │
       └──── (N) Template ──── (1) ParseJob
                    │
                    └── (embedded) TemplateSection[]
```

### 3.2 实体定义

#### User（用户）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| email | str unique | 登录邮箱 |
| password_hash | str | bcrypt |
| name | str | 显示名 |
| role | enum | **角色**：`user`(普通用户) / `admin`(系统运维管理员)。MVP 仅这两种；预留 `org_admin`(企业管理员, P2+) |
| status | enum | `active` / `disabled`(被封禁) |
| org_id | UUID FK nullable | **所属组织**（预留，MVP 为 null；P2+ 企业版启用） |
| is_superuser | bool | 初始部署时的首个超管标记（命令行创建，非注册） |
| created_at | datetime | |
| last_login_at | datetime | |

> **首个管理员如何产生**：系统部署后，通过**命令行脚本** `python -m app.scripts.create_admin` 创建第一个 `admin` 用户（不开放注册管理员）。避免"谁能成为管理员"的安全漏洞。

#### Template（模板）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK nullable | null 表示系统内置模板 |
| name | str | 模板名 |
| source_filename | str nullable | 上传来源文件名（内置模板为 null） |
| structure | JSONB | 章节树（TemplateSection 数组） |
| styles | JSONB | 样式定义（各级标题/正文的字体字号等） |
| numbering | JSONB | 编号规则（如 1. / 1.1 / 1.1.1） |
| is_default | bool | 用户默认模板 |
| is_system | bool | 系统内置（不可删） |
| created_at | datetime | |

**TemplateSection（嵌入 structure 内的数组元素）**
```
{
  "id": "...",
  "order": 1,
  "key": "name" | "field" | "background" | "problem" 
       | "solution" | "effect" | "drawings" | "embodiment" 
       | "custom",
  "title": "发明名称",
  "level": 1
}
```
- `key` 用于匹配 AI Prompt 策略；`custom` 表示用户自定义章节，用通用 Prompt 策略

#### ParseJob（模板解析任务）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| template_id | UUID FK nullable | 解析成功后关联 |
| source_path | str | 上传文件存储路径 |
| status | enum | pending / processing / completed / failed |
| error_message | text nullable | |
| created_at | datetime | |
| completed_at | datetime nullable | |

#### Project（项目/案件）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| template_id | UUID FK | 基于哪个模板（创建时快照，详见 9.7） |
| title | str | 项目名 |
| stage | enum | **生命周期阶段**：disclosure(MVP) / application / examination / archive。MVP 固定 disclosure，为全生命周期预留 |
| status | enum | draft / in_progress / completed / archived |
| current_section_order | int | 当前章节序号 |
| progress_pct | int 0-100 | |
| metadata | JSONB nullable | 交底书抬头元信息（见下表） |
| prior_art_refs | JSONB nullable | 检索结果预留（MVP 不用） |
| archived_at | datetime nullable | 归档时间（进入知识库的时间戳） |
| created_at | datetime | |
| updated_at | datetime | |

**Project.metadata 结构**（导出抬头的来源，创建项目时可选填，随时可改）
```
{
  "inventors": ["张三"],          // 发明人
  "applicant": "XX 科技有限公司",  // 申请人
  "organization": "研发部",        // 所属单位/部门
  "contact": "zhang@xx.com",      // 联系方式
  "keywords": ["关键词1"],         // 关键词
  "category": "G06F",              // 分类号（可选）
  "disclosure_date": "2026-07-13"  // 撰写日期
}
```

#### Section（章节）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| template_section_id | str | 关联 TemplateSection.id |
| order | int | 在项目中的顺序 |
| key | str | 继承自模板，匹配 Prompt 策略 |
| title | str | 章节标题 |
| content | JSONB | Tiptap doc JSON |
| summary | text nullable | AI 生成的章节摘要（供跨章节上下文用） |
| status | enum | empty / drafting / confirmed |
| created_at | datetime | |
| updated_at | datetime | |

#### Message（对话消息）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| section_id | UUID FK | |
| role | enum | user / assistant |
| content | text | |
| metadata | JSONB nullable | 生成参数、token 用量等 |
| created_at | datetime | |

#### SectionVersion（章节版本快照）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| section_id | UUID FK | |
| content | JSONB | 快照内容 |
| summary | text nullable | |
| created_by | enum | auto（确认时自动）/ manual（用户手动） |
| note | str nullable | |
| created_at | datetime | |

#### Attachment（附件/附图）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| section_id | UUID FK nullable | |
| filename | str | |
| storage_path | str | |
| mime_type | str | |
| size | int | |
| uploaded_at | datetime | |

#### KnowledgeChunk（知识库分块 + 向量）
> 支撑基础 RAG。交底书归档（或用户手动触发）时，把内容分块并向量化存储。新交底书撰写时语义检索相似片段。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | 归属用户（检索时按用户隔离） |
| source_type | enum | **来源类型**：disclosure(交底书) / application(申请文件,后续) / response(答复,后续) / custom(用户上传,后续)。MVP 仅 disclosure |
| source_id | UUID FK | 来源实体 ID（MVP 为 Project.id；后续可为申请文件/答复的 ID） |
| source_section_key | str nullable | 来源章节 key（如 "solution"），便于检索结果定位 |
| chunk_index | int | 该来源内的分块序号 |
| content | text | 分块文本 |
| embedding | vector(N) | pgvector 向量（维度由 embedding 模型决定，如 1024/1536） |
| metadata | JSONB nullable | 附加元信息（如发明名称摘要、技术领域标签） |
| created_at | datetime | |

**设计要点**：
- 一个 Project 归档后产生多个 KnowledgeChunk（按章节或固定长度分块）
- `source_type` + `source_id` 让知识库可扩展到任意文档类型，不绑死交底书
- 向量检索用 pgvector 的 `<=>`（余弦）或 `<->`（L2）算子，配合 GIN/IVFFlat 索引
- 检索结果通过 `source_id` 反查回 Project，展示"参考自《XX 交底书》的技术方案章节"

#### ReviewRubric（审查评分标准，覆盖式配置）
> 支撑审查引擎（第 6 章）。系统内置默认 Rubric，用户可整体覆盖。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK nullable | null 表示系统默认 |
| project_id | UUID FK nullable | null 表示用户级；非 null 表示项目级覆盖 |
| scope | enum | system / user / project |
| name | str | Rubric 名称 |
| criteria | JSONB | 维度定义（见 6.4 结构：dimensions/weight/scoring_guide/deductions） |
| is_customized | bool | 是否被用户改过（用于"恢复默认"判断） |
| parent_id | UUID FK nullable | 覆盖关系链（user 覆盖 system，project 覆盖 user） |
| created_at | datetime | |
| updated_at | datetime | |

**覆盖解析顺序**：审查时按 `project 级 → user 级 → system 级` 查找，取第一个命中。

#### ReviewRecord（审查记录，支撑跨会话记忆）
> 每次审查的完整结果，并写入 LangGraph Store 供跨会话加载（6.7）。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK | |
| user_id | UUID FK | |
| rubric_snapshot_id | UUID FK | 本次审查所用的 Rubric 快照（可追溯，保复现） |
| round | int | 第几轮审查（同项目递增） |
| total_score | int | 加权总分 |
| previous_score | int nullable | 上一轮总分（趋势对比） |
| dimension_scores | JSONB | 各维度分数+证据+建议+run_scores（见 6.5） |
| resolved_issues | JSONB | 本轮解决的旧问题 |
| remaining_issues | JSONB | 本轮遗留问题 |
| created_at | datetime | |

**关键**：`rubric_snapshot_id` 保证可复现——同一份交底书 + 同一 Rubric 快照，无论何时审查，结果一致。

#### AgentSkill（agent 技能，增量式配置）
> 支撑自定义能力（7.4）。技能是可挂载的"插件"，控制 agent 能做什么。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK nullable | null 表示系统内置技能定义 |
| skill_key | str | 技能标识（rag_search / rubric_review / ...） |
| name | str | 显示名 |
| description | str | 技能说明 |
| enabled | bool | 该用户是否启用（默认 true） |
| config | JSONB nullable | 技能配置（如 rag_search 的 top_k、rubric_review 的 run_count） |
| is_builtin | bool | 系统内置 / 用户自定义 |
| created_at | datetime | |

**注意**：MVP 的 `is_builtin=false`（用户自定义技能）只存配置不实现运行时；架构预留。

#### SystemSetting（系统设置，管理员维护）
> 存全局策略开关与全局 LLM/embedding 配置。键值对结构，便于扩展。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| key | str unique | 设置键（如 `llm_global_enabled` / `llm_global_config` / `embedding_global_config` / `llm_per_user_limit`） |
| value | JSONB | 设置值（结构随 key 而异） |
| updated_by | UUID FK | 最后修改的管理员 |
| updated_at | datetime | |

**MVP 关键键**：
- `llm_global_enabled` (bool)：是否向用户提供全局 LLM key。`false` = 强制自定义配置，用户必须自配 key 才能用
- `llm_global_config` (JSON)：全局 LLM 配置（base_url / api_key / model / provider），管理员在后台填
- `embedding_global_config` (JSON)：全局 embedding 配置（同上）
- `llm_per_user_limit` (JSON)：按用户限流（如每日 token 上限）

#### UserLLMConfig（用户自有 LLM 配置，自定义配置）
> 用户自带的 LLM key 与配置。每个用户一份，可覆盖全局。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK unique | 一人一份 |
| provider | str | Provider 标识（如 `zhipu` / `openai` / `deepseek` / `custom`） |
| base_url | str | OpenAI 兼容 API 地址（如 `https://open.bigmodel.cn/api/paas/v4`） |
| api_key_encrypted | str | **加密存储**的 API key（AES，密钥来自系统 secret） |
| model | str | 默认模型名（如 `glm-5.2`） |
| embedding_model | str nullable | Embedding 模型名（可独立配置） |
| is_active | bool | 是否启用（用户可临时禁用） |
| created_at | datetime | |
| updated_at | datetime | |

**关键安全**：`api_key_encrypted` 必须加密存储，不明文落库（详见 8.4 LLM Key 安全）。

### 3.3 关键设计决策

1. **富文本存 JSON 不存 HTML**：选 Tiptap（基于 ProseMirror），JSON 结构化，便于 AI 读写、diff、版本管理
2. **对话按 Section 隔离**：每章节独立对话历史，互不污染；但 AI 生成时可读取其他已确认 Section 的 `summary` 作为上下文
3. **版本粒度到 Section**：确认章节或手动触发时打快照，不做全篇版本（太重）
4. **模板结构嵌入存储**：TemplateSection 作为 Template.structure 的 JSONB 数组，不单独建表（章节数少、读为主、避免过度规范化）
5. **检索接口预留**：`prior_art_refs` 字段 + `SearchService` 抽象层，结构在，MVP 不实现
6. **模板与项目解耦（创建时快照）**：项目创建时把模板的 `structure` 复制到各 Section，之后**模板的修改/删除不影响已有项目**。这保证历史项目稳定，也简化数据关系（项目不依赖模板存在）
7. **Project.metadata 而非独立实体**：交底书抬头信息用 JSONB 字段而非独立表——这些信息是「可选填、低频改、整体读写」的，独立实体过度规范化
8. **富文本自动保存**：前端防抖（约 2 秒）触发 `PUT /sections/{id}/content`；后端用 `updated_at` 做乐观锁，请求带 `If-Match`，冲突返回 409；多 tab 场景 MVP 接受 last-write-wins（详见 13.4）
9. **知识库与业务库同库（pgvector）**：KnowledgeChunk 与业务数据共存在 PostgreSQL，避免引入独立向量数据库的运维负担；MVP 数据量下 pgvector 性能足够
10. **分块而非整篇向量化**：交底书按章节分块（每章一个或多个 chunk），检索粒度细、召回精准；`source_type + source_id` 让知识库可扩展到后续的申请文件/答复
11. **归档触发向量化**：交底书完成（status=completed）后，用户点「归档」或自动触发，将各章节内容分块、调 embedding API 向量化、写入 KnowledgeChunk。归档后 Project.status=archived
12. **LLM 配置三级解析优先级**（详见 8.4）：用户启用自有配置(`UserLLMConfig.is_active=true`) → 全局配置(`llm_global_enabled=true`) → 无可用配置(报错引导)。用户自配可覆盖全局；全局关闭则强制用户自配
13. **API key 加密存储**：UserLLMConfig.api_key 与 SystemSetting 里的全局 key 均 AES 加密落库，不明文；运行时解密注入 ModelAdapter，不记日志

---

## 4. 系统架构与技术选型

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│  浏览器 (Next.js 前端)                               │
│  ├─ 页面路由 (App Router)                            │
│  ├─ Tiptap 富文本编辑器                              │
│  ├─ AI 对话面板（SSE 流式渲染）                      │
│  ├─ 模板管理 / 审查报告 / Rubric 配置界面            │
│  ├─ 知识库参考展示（RAG 来源标注）                   │
│  └─ 状态管理 (Zustand + TanStack Query)             │
└────────────────────┬────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│  后端 (FastAPI 单体)                                 │
│  ├─ API 层 (路由/校验/鉴权)                          │
│  ├─ 业务层 (用户/项目/模板/章节/版本/导出/归档)      │
│  ├─ Agent 编排层 (LangGraph)                         │
│  │   ├─ 撰写 Graph（章节状态机 + Checkpoint + HITL） │
│  │   ├─ 审查 Graph（确定性评估管线，第 8 章）        │
│  │   └─ Store（跨会话记忆：审查记录/修改历史）       │
│  ├─ RAG 层 (LangChain Embedding + pgvector：检索/注入) │
│  ├─ 自定义层 (Rubric 配置/知识库扩充/技能挂载)       │
│  ├─ 模板解析层 (Word 解析/异步任务)                  │
│  └─ 基础设施层 (DB/存储/ModelAdapter)               │
└───┬──────────┬──────────────┬───────────┬───────────┘
    │          │              │           │
┌───▼──────┐ ┌▼────────┐ ┌───▼────────┐ ┌─▼──────────┐
│Postgres +│ │文件存储 │ │LLM/Embed   │ │LangSmith   │
│pgvector +│ │本地/对象│ │GLM-5.2 +   │ │(可选追踪)  │
│Graph表   │ └─────────┘ │embedding   │ └────────────┘
│(业务+向量│              │(LangChain  │
│+Checkpoint│              │ ModelAdapter)│
│+Store)   │              └─────────────┘
└──────────┘
```

### 4.2 技术选型

> **v1.3 关键变更**：引入双 Agent 框架。编排/状态机/记忆由 **LangGraph** 接管（取代手搓），RAG 检索由 **LlamaIndex** 接管（取代手搓 Retriever）。详见第 5 章。
>
> ⚠️ **v1.5.1 校正**：上述双框架规划在落地中调整——实际编排用 LangChain 手搓（见 5 章）、RAG 用 LangChain Embedding + pgvector（见 10 章）。下表「实际选型」列为 MVP 真实使用的库；原 LlamaIndex/LangGraph 相关行保留为「设计选型」并标注差异。

| 层 | 实际选型（MVP 已落地） | 设计选型（v1.3，部分未落地） | 理由 |
|---|---|---|---|
| 前端框架 | Next.js 14+ (App Router) + TypeScript | 同 | 全栈能力、SSR、生态成熟 |
| UI 组件 | shadcn/ui + Tailwind CSS | 同 | 可定制、不锁框架 |
| 富文本 | Tiptap v2 | 同 | JSON 结构化、AI 友好 |
| 状态管理 | Zustand（UI）+ TanStack Query（服务端） | 同 | 轻量、分工清晰 |
| AI 流式 | SSE (Server-Sent Events) | 同 | 单向流足够、自动重连 |
| 后端框架 | FastAPI + Python 3.11+ | 同 | 异步、类型友好、AI 生态最佳 |
| **Agent 编排** | **LangChain `ChatOpenAI` + 手搓编排器**（`app/ai/orchestrator.py`） | ~~LangGraph StateGraph + Checkpoint + Store + HITL~~ | ⚠️ 未用 LangGraph，编排为手搓 generator 流式；Checkpoint/HITL/Store 框架红利暂缺（详见顶部「实现现状」） |
| **RAG 检索** | **LangChain `OpenAIEmbeddings` + pgvector 直连** | ~~LlamaIndex~~ | ⚠️ 弃用 LlamaIndex：其 `OpenAIEmbedding` 不支持国产 embedding 模型名（GOTCHAS E3） |
| LLM/Embedding 抽象 | **LangChain `ChatOpenAI` / `OpenAIEmbeddings`**（OpenAI 兼容协议接 GLM） | 同 | 经 OpenAI 兼容协议，可切换 Provider |
| ORM | SQLAlchemy 2.0 + Alembic | 同 | Python ORM 事实标准 |
| 数据库 | PostgreSQL + **pgvector 扩展** | 同 | JSONB 支持好；pgvector 作向量存储后端（直接 SQLAlchemy 操作） |
| 持久化（计划） | — | ~~LangGraph PostgresSaver（Checkpoint + Store）~~ | ⚠️ 未落地；模板解析恢复见 13.3，Agent 执行恢复暂未用框架 |
| 鉴权 | JWT (access + refresh token) | 同 | 无状态 |
| LLM | GLM-5.2（经 `langchain_openai.ChatOpenAI` 接入） | 同 | 国产模型友好；原生支持 |
| Embedding | 智谱 embedding API（经 `langchain_openai.OpenAIEmbeddings`） | 同 | 与 LLM 同厂商，中文效果好 |
| Word 解析 | python-docx + lxml 底层访问 | 同 | 读样式/章节可靠；**自动编号需自写解析器**（详见 9.6）。LlamaParse 作为后续增强选项 |
| Word 导出 | python-docx | 同 | 套用模板样式（详见 13.5 导出渲染器） |
| PDF 导出 | 浏览器打印（MVP）/ weasyprint（后续） | 同 | MVP 简化 |
| Markdown→Tiptap | markdown-it + 自定义映射 | 同 | AI 输出转换 |
| 异步任务 | 模板解析用 BackgroundTasks + 启动恢复扫描 | ~~Agent 执行/审查用 LangGraph（Durable Execution）~~ | ⚠️ Agent 执行未用 LangGraph，无断点恢复；模板解析恢复见 13.3 |
| 校验 | Pydantic v2 | 同 | FastAPI 原生 |
| 配置 | pydantic-settings + .env | 同 | 标准 |
| 测试 | pytest + Vitest | 同 | 对应规范 |
| 日志 | loguru + LangSmith（Agent 追踪，可选） | 同 | 结构化日志 + Agent 可观测 |
| 部署 | docker-compose (web + api + postgres) | 同 | 一键起 |

### 4.3 项目目录结构

```
TianGong/
├── apps/
│   ├── web/                    # Next.js 前端
│   │   ├── app/                # App Router
│   │   │   ├── (auth)/         # 登录注册
│   │   │   ├── (dashboard)/    # 工作台
│   │   │   ├── projects/[id]/  # 项目编辑
│   │   │   └── templates/      # 模板管理
│   │   ├── components/
│   │   ├── lib/
│   │   ├── hooks/
│   │   └── package.json
│   └── api/                    # FastAPI 后端
│       ├── app/
│       │   ├── api/            # 路由 v1
│       │   │   └── v1/
│       │   │       ├── auth.py
│       │   │       ├── projects.py
│       │   │       ├── templates.py
│       │   │       ├── sections.py
│       │   │       └── ai.py
│       │   ├── core/           # 配置/鉴权/异常
│       │   ├── models/         # SQLAlchemy 模型
│       │   ├── schemas/        # Pydantic 模型
│       │   ├── services/       # 业务逻辑
│       │   │   ├── project_service.py
│       │   │   ├── template_service.py
│       │   │   ├── parse_service.py
│       │   │   ├── export_service.py
│       │   │   ├── archive_service.py   # 归档到知识库
│       │   │   ├── rubric_service.py    # Rubric 覆盖解析
│       │   │   └── skill_service.py     # 技能挂载
│       │   ├── agents/         # ⚠️ LangGraph 编排（v1.3 设计，未落地）
│       │   │   └── # 实际编排见 ai/orchestrator.py（手搓）
│       │   ├── ai/             # AI 引擎（实际实现）
│       │   │   ├── orchestrator.py      # ⭐ 编排器（引导对话/生成草稿/重写，流式）
│       │   │   ├── llm_client.py        # LangChain ChatOpenAI 接入
│       │   │   ├── context_assembler.py # 五层上下文装配（含知识库层）
│       │   │   ├── section_prompts.py   # 章节 Prompt 注册表
│       │   │   ├── rubric_prompts.py    # 审查评分 Prompt（Rubric 驱动）
│       │   │   └── markdown_to_tiptap.py
│       │   ├── rag/            # 知识库与 RAG（基于 LangChain + pgvector）
│       │   │   ├── embedding.py         # LangChain OpenAIEmbeddings
│       │   │   ├── chunker.py           # 分块器
│       │   │   ├── archiver.py          # 归档入库
│       │   │   └── retriever.py         # pgvector 余弦检索
│       │   └── main.py
│       ├── tests/
│       ├── alembic/
│       └── pyproject.toml
├── docs/                       # 设计文档
├── scripts/
├── docker-compose.yml
├── .gitignore
└── README.md
```

---

## 5. AI 编排引擎（核心）

### 5.1 设计原则

> AI 编排 = **LangGraph 状态图** + 上下文装配 + 流式生成 + 结构化输出

v1.3 起，AI 编排从手搓服务改为**基于 LangGraph 的状态图**。所有 AI 流程（撰写、审查、重写）建模为 LangGraph 的 `StateGraph`，天然获得：
- **Checkpoint**：状态持久化，服务重启自动恢复（取代手搓的 10.3 恢复机制）
- **Store**：跨会话长期记忆（审查记录、修改历史——这是跨对话评分稳定的关键）
- **HITL（Human-in-the-Loop）**：用户确认章节、确认审查意见的暂停/恢复
- **Durable Execution**：任何节点中断都能从断点续跑

### 5.2 引擎分层

```
┌─────────────────────────────────────────────┐
│  API 层 (FastAPI 路由，SSE 流式)             │
│  /sections/{id}/chat | /generate | /rewrite │
│  /projects/{id}/review                      │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  LangGraph 编排层（核心）                    │
│  ├─ WritingGraph   撰写状态图（5.3）         │
│  │   章节推进 = StateGraph 节点流转          │
│  ├─ ReviewGraph    审查状态图（第 8 章）     │
│  │   确定性评估管线                           │
│  ├─ Checkpointer   PostgresSaver（状态落库） │
│  ├─ Store          跨会话记忆（审查记录/偏好）│
│  └─ HITL           interrupt()/resume()      │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  Prompt 引擎 (PromptBuilder)                 │
│  ├─ SystemPromptBuilder (角色/规范/格式)      │
│  ├─ ContextAssembler (装配五层上下文)        │
│  └─ SectionPromptRegistry (章节 Prompt)     │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  RAG 检索层 (LangChain Embedding + pgvector) │
│  └─ 检索/注入（重排后续）                    │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  模型抽象 (LangChain)                        │
│  ├─ ChatOpenAI(base_url=智谱, model=glm-5.2)│
│  └─ OpenAIEmbeddings (智谱 embedding-3)      │
└─────────────────────────────────────────────┘
```

### 5.3 撰写状态图（WritingGraph）

撰写流程建模为一个 LangGraph `StateGraph`，章节顺序推进即节点流转：

```
                    ┌──────────────┐
         ┌─────────▶│  节点: 加载   │ 加载 Section + 上下文装配
         │          │  章节 (load)  │ (五层上下文，7.4)
         │          └──────┬───────┘
         │                 ▼
         │          ┌──────────────┐
         │          │ 节点: AI 对话 │ ChatNode
         │          │   (chat)     │ 用户提问→AI 流式回复
         │          └──────┬───────┘
         │                 ▼
         │          ┌──────────────┐
         │          │节点:生成草稿 │ GenerateNode
         │          │ (generate)   │ Markdown→Tiptap 入库
         │          └──────┬───────┘
         │                 ▼
         │          ┌──────────────┐
         │          │ HITL: 用户   │ interrupt()
         │   ◀──────│  确认章节    │ 等待用户点"确认"
         │          └──────┬───────┘
         │            确认 │ 修改(回到 chat)
         │                 ▼
         │          ┌──────────────┐
         │          │节点:确认归档 │ ConfirmNode
         │          │(confirm)     │ summary生成+存Store
         │          └──────┬───────┘
         │                 ▼
         │          ┌──────────────┐
         └──────────│条件:还有下一 │ 有→下一章 load
                    │  章吗?       │ 无→END(进入审查)
                    └──────────────┘
```

**LangGraph 带来的关键能力**：
- **State**：图状态 = `{section_id, chapter_index, content, dialogue_history, summary, ...}`，自动 Checkpoint
- **HITL**：确认章节用 `interrupt()`，用户点确认后 `Command(resume=...)` 继续——天然实现"用户确认才能进下一章"
- **恢复**：服务重启后，图从最近 Checkpoint 续跑（取代手搓 10.3）
- **Store**：已确认章节的 summary 写入 Store，跨会话可读（支持中断后新对话续写）

### 5.4 上下文装配（ContextAssembler）

AI 写每一章时，上下文分五层（含知识库层，详见第 10 章）：

```
[系统层]     角色 + 输出规范 + 格式约束
[知识库层] ⭐ 检索到的相似历史案例片段（top-K，带来源标注）
[项目层]     已确认章节的 summary（不是全文，控制 token）
[章节层]     当前章节的 key 对应的专属指引
[对话层]     本章节历史对话
```

- **知识库层**：检索用户历史案例（LangChain Embedding + pgvector），token 预算独立（详见 10.4）；用户可见来源标注
- **项目层做摘要而非全文**：已确认章节内容可能很长，注入全文会爆 token。确认章节时由 AI 生成 `summary`，注入摘要即可
- **严格顺序的红利**：前面的章节已确认，其 summary 是可靠的上下文

### 5.5 章节 Prompt 注册表（SectionPromptRegistry）

每个章节 `key` 对应一个 Prompt 包，定义：目标、引导问题、输出格式、完成判定。

```python
SECTION_PROMPTS = {
    "name": SectionPrompt(
        goal="提炼清晰、准确的发明名称",
        guide_questions=[
            "这个发明最核心的功能是什么？",
            "它应用在什么领域？",
            "它是产品、方法，还是两者结合？"
        ],
        output_format="名称应为：<技术领域>+<核心特征>+<类型>",
        completion_criteria="名称 ≤25字，包含技术领域和核心特征"
    ),
    "solution": SectionPrompt(
        goal="完整描述解决技术问题的技术方案",
        guide_questions=[
            "方案的整体结构/流程是怎样的？",
            "有哪些关键组件/步骤？它们如何配合？",
            "有没有替代实现方式？"
        ],
        output_format="技术方案应包含：整体架构 + 关键要素 + 工作原理",
        completion_criteria="至少覆盖结构、流程、关键要素三个维度"
    ),
    # field / background / problem / effect / drawings / embodiment ...
    "custom": SectionPrompt(  # 用户自定义章节的通用策略
        goal="根据章节标题引导用户撰写内容",
        guide_questions=[
            "这部分您想表达的核心信息是什么？",
            "有没有需要特别强调的关键点或数据？",
            "是否需要配合图示或示例说明？"
        ],
        output_format="结构清晰的段落/列表",
        completion_criteria="内容与标题相关，无空白"
    )
}
```

这套注册表是天工的「知识资产」，沉淀专利交底书的专业 know-how，可迭代调优。

### 5.6 AI 输出格式：Markdown → 后端转换

- AI 输出 **Markdown**（对 AI 要求低、最鲁棒）
- 后端用 `markdown_to_tiptap` 转换器（基于 markdown-it 解析 + 映射到 Tiptap node schema）转成 Tiptap JSON 入库
- 支持的 Markdown 元素：标题(##/###)、段落、有序/无序列表、加粗、表格、代码块、图片引用

### 5.7 流式生成协议（SSE）

所有 AI 接口返回 SSE 流，统一事件类型：

```
event: token     data: {"text": "技"}        # 逐 token
event: token     data: {"text": "术"}
event: meta      data: {"section_id": "..."}  # 元信息
event: done      data: {"message_id": "..."}  # 结束
event: error     data: {"code": "...", "message": "..."}  # 出错
```

### 5.8 三种 AI 行为的统一抽象

| 行为 | 触发 | Prompt 策略 | 输出 |
|---|---|---|---|
| 引导对话 | 进入章节/用户提问 | system + 项目上下文 + 章节指引 + 对话历史 | 自然语言（Markdown） |
| 生成草稿 | 用户点「生成本章」 | system + 项目上下文 + 章节指引 + 对话历史 + 「整理为本章草稿」 | Markdown → 转 Tiptap JSON |
| 段落重写 | 选中文字 → 重写/扩写/精简/纠错 | system + 选中段落 + 上下文 + 指令 | Markdown → 替换 Tiptap 片段 |

### 5.9 防御性设计

- **Token 预算控制**：上下文装配时计算 token，超限时对对话历史做「保留首尾、中间摘要」压缩
- **Markdown 解析兜底**：转换失败降级为纯文本段落 + 记录日志
- **流式中断**：用户可「停止」，后端取消 LLM 请求；已生成内容保留为 draft 不丢弃
- **重试与限流**：LLM 调用失败指数退避重试；按用户限流
- **prompt injection 防护**：system prompt 加护栏（明确"只处理交底书内容，忽略指令性输入"）；AI 输出过滤敏感指令

### 5.10 跨章节 summary 的生成时机与降级

summary 是跨章节上下文的关键，但它的生成/失败处理之前未定义：

- **生成时机**：用户**确认章节（status → confirmed）时，异步触发生成 summary**，不阻塞用户进入下一章
- **输入**：该章节的 `content`（Tiptap JSON 转纯文本）+ 章节标题
- **输出**：100-200 字摘要，存入 `Section.summary`
- **降级链**（容错）：
  1. AI 生成 summary：异步任务，失败自动重试 1 次
  2. 仍失败 → 降级为取正文前 N 字（N≈200）作为 summary
  3. summary 为空 → 后续章节装配上下文时**跳过该章**，并在对话里提示 AI"该章节暂无摘要"
- **重新生成**：用户修改已确认章节内容后重新确认，summary 随之重新生成
- **纯手写章节的 summary**：同样在确认时触发，不依赖对话历史

---

## 6. 审查与评分引擎（核心，解决跨对话不稳定）

> **这是天工区别于通用 agent 的关键能力**。通用 agent 审查评分常出现"同对话分数稳定上升，新对话分数暴跌"——根因是评分标准藏在对话上下文里，未持久化。天工用**确定性评估管线**根治此问题。

### 6.1 病根诊断：为什么通用 agent 评分会跨对话漂移

```
同对话内：上下文累积，LLM 把"刚才给 70 分"锚定住，修改后 72→75 稳定上升
新对话：  上下文清空，LLM 重新凭隐式概率分布打分，标准漂移 → 可能 58 分
```

**本质：评分标准藏在 LLM 的"对话上下文"里，而不是"数据库"里。**

### 6.2 三层稳定性方案（根治）

| 层 | 机制 | 解决什么 |
|---|---|---|
| **① 显式 Rubric 持久化** | 评分维度/各档标准/扣分项写成结构化文档存库，每次审查强制注入 | 根治标准漂移 |
| **② 自一致性** | 关键评分维度独立审查 N 次（MVP N=2），取均值 | 平滑 LLM 概率波动 |
| **③ 跨会话记忆** | Store 记住"上次审查记录、改了什么、给了几分"，新对话加载 | 锚定历史，不漂移 |

三者叠加 = **同一份交底书无论何时、在哪个新对话审查，评分一致可复现**。

### 6.3 ReviewGraph —— 确定性评估管线（非自由对话）

审查建模为 LangGraph 的 `ReviewGraph`，是**确定性管线**而非自由对话——这是稳定性的根本保证：

```
┌──────────────────────────────────────────────┐
│ 节点1: 加载 (load)                            │
│  · 读交底书所有 Section 内容                  │
│  · 加载 ReviewRubric（系统默认 + 用户覆盖）   │
│  · 加载 Store 历史审查记忆（上次记录+修改点） │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ 节点2: 逐维度评分 (score) —— Rubric 驱动      │
│  for each 维度 in Rubric:                    │
│    · 构造评分 Prompt（注入该维度标准+证据要求）│
│    · 调 LLM（结构化输出：分数+证据+建议）     │
│    · 自一致性：关键维度跑 N 次，取均值        │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ 节点3: 汇总 (aggregate)                       │
│  · 加权计算总分                              │
│  · 生成结构化审查报告                         │
│  · 与上次审查对比（分数变化、是否解决旧问题）  │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ 节点4: 持久化 (persist)                       │
│  · 写 ReviewRecord 到数据库                   │
│  · 写审查摘要到 Store（供下次跨会话加载）      │
│  · Checkpoint                                │
└──────────────────────┬───────────────────────┘
                       ▼
┌──────────────────────────────────────────────┐
│ HITL: 用户查看报告 → 修改交底书 → 可再次审查  │
│  （再次审查应显示分数稳定上升）                │
└──────────────────────────────────────────────┘
```

**关键设计：评分不是"问 AI 觉得几分"，而是"给 AI 一份明确标准，让它逐条核对并给出证据"**。这把主观判断变成了可审计的结构化输出。

### 6.4 ReviewRubric 结构（覆盖式配置）

系统内置一份精心设计的默认 Rubric，用户可整体覆盖。结构：

```json
{
  "version": "1.0",
  "dimensions": [
    {
      "key": "novelty",
      "name": "新颖性表述",
      "weight": 0.20,
      "scoring_guide": {
        "90-100": "明确指出与现有技术的区别，有具体对比",
        "70-89":  "提到区别但对比不充分",
        "50-69":  "未明确区别，需代理人推断",
        "0-49":   "完全未提及新颖性"
      },
      "deductions": [
        {"code": "D01", "desc": "未引用任何现有技术", "points": -10}
      ],
      "applies_to_sections": ["background", "problem", "solution"]
    },
    {
      "key": "solution_clarity",
      "name": "技术方案清晰度",
      "weight": 0.25,
      "scoring_guide": { ... },
      "applies_to_sections": ["solution", "embodiment"]
    }
    // ... completeness / effect_support / feasibility / writing_quality
  ]
}
```

- `weight`：各维度权重，总和为 1
- `scoring_guide`：各分数档的明确标准（注入 Prompt，约束 AI 打分）
- `deductions`：明确扣分项（确定性规则，不靠 AI 主观）
- `applies_to_sections`：该维度只评哪些章节

### 6.5 审查报告输出

```json
{
  "review_id": "...",
  "project_id": "...",
  "round": 3,
  "total_score": 78,
  "previous_score": 72,
  "trend": "+6",
  "dimensions": [
    {
      "key": "novelty",
      "name": "新颖性表述",
      "score": 85,
      "run_scores": [84, 86],      // 自一致性 N 次原始分
      "evidence": "技术方案章节第3段明确对比了XX专利...",
      "suggestion": "建议在背景技术补充与YY方案的差异",
      "applies_to": ["solution"]
    }
  ],
  "resolved_issues": ["D01 已解决：本次引用了现有技术"],
  "remaining_issues": ["技术方案缺替代实施方式"],
  "rubric_snapshot_id": "..."      // 本次审查用的 Rubric 版本（可追溯）
}
```

- **trend**：与上次对比，让用户看到改进是否有效
- **run_scores**：自一致性原始分数，透明可审计
- **rubric_snapshot_id**：每次审查快照所用 Rubric，确保可复现

### 6.6 稳定性验证（测试要求）

审查引擎必须通过稳定性测试才算交付：
- **复现性测试**：同一份交底书 + 同一 Rubric，新对话审查 N 次，分数标准差 ≤ 3 分
- **改进单调性**：用户按建议修改后，分数应稳定上升（不回落）
- **Rubric 一致性**：改变 Rubric，分数相应变化；不改变 Rubric，分数稳定

### 6.7 审查的记忆语义（Store）

- **写入**：每次审查后，ReviewRecord 摘要写入 LangGraph Store，namespace = `(user_id, project_id)`
- **读取**：新对话启动审查时，从 Store 加载上一轮的分数、未解决问题、Rubric 版本
- **锚定 Prompt**：注入"上一轮审查得分 72，未解决问题：[X, Y]"，让本次审查在历史锚点上推进，而非从零重判

---

## 7. 自定义能力（三套配置语义）

> 用户诉求："不同用户的知识库、技能等都可以自定义"。关键约束：**审查标准是覆盖式，其他是增量式**。

### 7.1 三套自定义的语义区分

| 可自定义项 | 语义 | 类比 | 数据模型 |
|---|---|---|---|
| **审查 Rubric** | 覆盖式（用户配置后整体替换系统默认） | 像"换一套评分标准" | `ReviewRubric`，每个 user/project 一份完整配置 |
| **知识库内容** | 增量（不断添加文档扩充） | 像"往书架加书" | 已有 `KnowledgeChunk`，`source_type` 扩展 `user_upload` |
| **agent 技能/工具** | 增量（启用/禁用/新增技能） | 像"给 agent 装插件" | 新增 `AgentSkill`，技能是可挂载的"插件" |

### 7.2 审查 Rubric 自定义（覆盖式）

- 系统内置默认 Rubric（见 6.4），用户开箱即用
- 用户可在「审查设置」页编辑：增删维度、调整权重、修改评分标准、定义扣分项
- 保存后**整体覆盖**该用户的默认 Rubric（保留系统默认可一键恢复）
- 支持按 project 级覆盖（某项目用特殊标准）
- 历史版本保留，审查记录关联所用 Rubric 快照（可追溯）

### 7.3 知识库自定义（增量式）

- 用户在「知识库」页上传文档（交底书/专利 PDF/技术资料/Word）
- 系统分块 → 向量化 → 写入 KnowledgeChunk（`source_type=user_upload`）
- 用户知识库 = 系统自动归档的交底书 + 用户手动上传的文档，**累积扩充**
- 可管理：删除某文档（级联删其 chunk）、查看来源、禁用某文档（不参与检索但不删）
- 审查与撰写时，RAG 检索覆盖用户全部知识库

### 7.4 agent 技能自定义（增量式）

agent 技能是可挂载的"插件"，定义 agent 能做什么额外的事。MVP 内置技能：

| 技能 key | 名称 | 说明 |
|---|---|---|
| `rag_search` | 知识库检索 | 撰写/审查时检索用户知识库（默认启用） |
| `rubric_review` | Rubric 审查 | 按 Rubric 逐维度评分（默认启用） |
| `consistency_check` | 自一致性校验 | 关键评分多次取均值（默认启用） |
| `quality_report` | 质量报告 | 生成结构化审查报告（默认启用） |
| `prior_art_hint` | 现有技术提示 | 撰写背景技术时提示检索方向（MVP 占位，检索在 P1） |

- 用户可在「技能」页启用/禁用内置技能、调整其 config
- **增量扩展**：架构预留用户自定义技能（`AgentSkill.is_builtin=false`，config 含工具定义），MVP 不实现自定义工具的运行时，但数据模型预留
- 禁用的技能不参与 agent 编排（LangGraph 节点按 enabled 列表装配）

---

## 8. 角色与权限（横切关注点）

> 管理员角色定位为 **C 系统运维管理员**（MVP），数据模型预留 A 平台运营 / B 企业管理员的演进路径。

### 8.1 角色定义（MVP）

| 角色 | role 值 | 谁能成为 | MVP 能力边界 |
|---|---|---|---|
| **普通用户** | `user` | 自行注册 | 管理自己的全部资源（项目/模板/知识库/Rubric/技能） |
| **系统管理员** | `admin` | 仅命令行创建（非注册） | 维护全局资源 + 运营用户 + 管控 AI 成本质量（见 8.2） |

> 预留角色（P2+，MVP 不实现）：`org_admin`（企业管理员，管本组织成员/知识库/统一标准）。

### 8.2 系统管理员能力域（MVP 范围）

管理员管的是**"跨用户共享的、全局的、或需要被约束的"资源**，不碰用户私人内容。

| 能力域 | 具体能力 | 说明 |
|---|---|---|
| **① 全局内容维护** | 系统默认模板 / 系统默认审查 Rubric / 内置技能定义的增删改 + 版本管理 | 这些是所有用户共享的"地基"，必须有人能维护（否则改一次要动数据库） |
| **② AI 配置管控** | LLM/embedding 的 Provider、模型、API key、token 配额、按用户限流阈值 | 控成本、切模型、防滥用的唯一入口 |
| **③ 用户运营** | 用户列表（邮箱/注册时间/角色/状态/用量统计）、封禁/解禁、重置密码 | 不含查看用户私人项目 |
| **④ 监控运维** | 系统日志查看、LLM/embedding 调用统计（用量/耗时/失败率）、异常告警、数据备份 | 部署后排查问题的刚需 |
| **⑤ 审计** | 管理员自身操作日志（谁在何时改了什么全局配置） | 防止管理员权限滥用，可追溯 |

### 8.3 数据可见性红线（合规核心）

**用户私人的项目、审查记录、对话、知识库内容，管理员默认不可见。**

| 数据 | 管理员可见性 | 说明 |
|---|---|---|
| 用户的项目/章节内容 | ❌ 不可见 | 专利是敏感商业数据，强制隔离 |
| 用户的审查记录/对话 | ❌ 不可见 | 同上 |
| 用户的知识库文档内容 | ❌ 不可见 | 用户上传的私有资料 |
| **用户的用量统计**（token 数、项目数、存储量） | ✅ 仅聚合数字 | 用于计费/限流/容量规划，不含内容 |
| 系统默认模板/Rubric/技能 | ✅ 可见可改 | 全局共享资源 |
| 系统日志（含错误堆栈，可能含用户数据片段） | ⚠️ 脱敏可见 | 日志里的用户内容需脱敏处理 |
| LLM 调用的 prompt/completion 内容 | ❌ 不可见 | 即使为排查问题，也只看元数据（耗时/token/状态），不看内容 |

**"经授权临时查看"机制（P1，MVP 不做）**：用户主动求助时，可生成一次性授权码，管理员凭码在限时内查看该用户指定项目的只读视图，全程记审计日志。MVP 阶段排查问题靠日志元数据 + 用户主动提供信息。

### 8.4 LLM Key 管理与 Provider 解析

> 解决"LLM 成本与控制权归谁"的问题。支持管理员全局 key + 用户自带 key（自定义配置）的灵活组合。

#### 8.4.1 三级 Provider 解析优先级

每次发起 LLM/embedding 调用时，按以下优先级解析可用配置：

```
① 用户自有配置（UserLLMConfig.is_active=true）
   └─ 命中 → 用用户的 key（用户自付，管理员不承担成本）
② 全局配置（SystemSetting.llm_global_enabled=true）
   └─ 命中 → 用全局 key（管理员/平台承担成本）
③ 都没有 → 报错引导
   └─ 提示"管理员未提供全局 key，请在设置页配置你自己的 LLM key"
```

**关键语义**：
- 用户自配 key **始终优先**于全局 key（即使用户自配时全局也开着）——这样用户想用自己的额度/模型时随时可以
- 全局开关 `llm_global_enabled=false` 时，**跳过第②步**，强制走第①步或报错——管理员可强制自定义配置
- admin 角色始终用全局配置（8.2② 管理员不自带 key）

#### 8.4.2 管理员的 LLM 管理能力

| 能力 | 说明 |
|---|---|
| 配置全局 key | 填 base_url / api_key / model / embedding_model（SystemSetting.llm_global_config） |
| 全局开关 | `llm_global_enabled`：true=平台买单（用户可覆盖）/ false=强制用户自付 |
| 按用户限流 | `llm_per_user_limit`：使用全局 key 的用户，每日 token 上限（防滥用） |
| 测试连通性 | 配置后可"测试连接"，验证 key 有效 |

#### 8.4.3 用户的 LLM 管理能力

| 能力 | 说明 |
|---|---|
| 查看当前生效配置 | 显示"当前使用：全局配置 / 你的配置"，透明 |
| 配置自有 key | 填 provider / base_url / api_key / model（任意 OpenAI 兼容） |
| 测试连通性 | 配置后可"测试连接" |
| 启用/禁用 | `is_active` 开关，临时切回全局 |

**当 `llm_global_enabled=false` 且用户未配 key**：用户进入系统时强制引导到"LLM 配置"页，未配置则无法使用 AI 功能（撰写/审查都不可用，但能浏览已有项目）。

#### 8.4.4 Provider 灵活性

用户/管理员可填任意 OpenAI 兼容 Provider：
- 智谱 GLM：`base_url=https://open.bigmodel.cn/api/paas/v4`，`model=glm-5.2`
- OpenAI：`base_url=https://api.openai.com/v1`，`model=gpt-4o`
- DeepSeek：`base_url=https://api.deepseek.com`，`model=deepseek-chat`
- 本地：`base_url=http://localhost:11434/v1`（Ollama/vLLM）
- 自定义：任意兼容端点

统一经 LangChain `init_chat_model` / ModelAdapter 接入，无需为每个 Provider 写适配代码。

#### 8.4.5 LLM Key 安全

- **加密存储**：`UserLLMConfig.api_key_encrypted` 与 `SystemSetting` 里的全局 key 均 **AES 加密**落库，密钥来自系统 secret（`.env` 的 `ENCRYPTION_KEY`）
- **不明文返回**：API 永远不返回完整 key，只返回掩码（如 `sk-****abcd`）
- **不记日志**：LLM 调用时 key 解密注入 ModelAdapter，绝不写入日志/异常堆栈
- **限流防滥用**：用全局 key 的用户受 `llm_per_user_limit` 约束；自配 key 的用户不限流（自付成本）
- **管理员审计**：管理员查看用户列表时只看到"是否自配 key"（布尔），看不到 key 内容（8.3 红线）

### 8.5 权限实现

- **RBAC 基础**：FastAPI 依赖注入 `get_current_user` 已有（13.1），新增 `require_admin` 依赖——校验 `user.role == "admin"`
- **管理 API 前缀**：所有管理员接口统一 `/api/v1/admin/*`，路由级强制 `require_admin`
- **资源级隔离复用 13.1**：管理员访问全局资源（`is_system=true` 的模板/Rubric）时不按 user_id 过滤；访问用户列表时只返回聚合信息
- **审计中间件**：`/api/v1/admin/*` 的所有写操作自动记审计日志（admin_id, action, target, before, after, timestamp）

### 8.6 管理后台形态（MVP）

MVP 不做花哨的管理后台 UI，只做**最简功能页**：
- `/admin` 入口（仅 admin 角色可见）
- 子页：全局模板管理 / 全局 Rubric 管理 / 技能管理 / 用户列表 / **LLM 配置（含全局开关）/ 日志监控**
- 复用普通用户的组件（模板编辑器、Rubric 编辑器），只是操作的是 `is_system=true` 的全局资源

---

## 9. 模板模块（核心模块）

### 9.1 流程

```
上传 Word (.docx)
   │
   ▼
创建 ParseJob (status=pending) + 文件落盘
   │
   ▼ 异步任务 (BackgroundTasks，详见 13.3 恢复机制)
   ├─ SectionStructureExtractor  章节结构（Heading 样式优先）
   ├─ StyleExtractor             样式（含继承解析 + eastAsia 字体）
   ├─ NumberingResolver          编号规则（numbering.xml 计数器 + 正则兜底）
   ├─ 结构化存为 Template (structure + styles + numbering)
   └─ ParseJob status=completed
   │
   ▼
模板出现在「我的模板」列表
   │
   ▼
创建项目时可选此模板 → 复制模板 structure 到项目 Section（之后解耦，详见 9.7）
```

### 9.2 模板管理

- 列表页：展示用户的所有模板 + 系统默认模板
- 操作：预览（章节结构 + 样式预览）、重命名、删除、设为默认
- 系统默认模板不可删除

### 9.3 模板在 AI 中的作用

- AI 生成内容时参考模板的**章节标题**（作为上下文）
- 章节通过 `key` 匹配 Prompt 策略；用户自定义章节（`key=custom`）用通用策略
- 导出时套用模板的**完整样式**（字体/编号/标题层级）

### 9.4 解析容错

- Word 文档格式千差万别，解析需容错
- 无法识别章节层级时，降级为「按段落顺序、所有章节平级」
- 样式提取失败时，用默认样式兜底
- 解析失败时，ParseJob 记录错误信息，前端提示用户「解析失败，请检查文档格式或使用默认模板」

### 9.5 附图章节的多模态边界（重要约束）

MVP 的 LLM **仅用文本能力，不引入多模态（视觉）**。「附图说明」章节的处理方式：

1. 用户在「附图说明」章节**上传图片**（仅存储 + 在编辑器中展示，LLM 不读图）
2. 用户**用一两句话文字描述每张图**的内容（如"图 1 是本发明装置的整体结构示意图"）
3. AI 基于这些**文字描述 + 已完成的技术方案上下文**，润色生成规范的图注（统一格式、补充图序号）

这样既能辅助产出规范图注，又把多模态的复杂度（vision API、图片计费、并非所有兼容接口都支持）挡在 MVP 之外。后续若需 AI 真正"看图说话"，可在 LLMClient 扩展 `vision_chat` 方法，不影响现有架构。

### 9.6 编号解析技术方案（已知技术风险点）

> ⚠️ **这是 MVP 工程量最大、不确定性最高的子模块**。python-docx 无法直接读出 Word 自动编号的实际文本（这是公认的硬限制），需自建解析器。

#### 9.6.1 问题本质

Word 的自动编号（1. / 1.1 / 1.1.1）是**渲染时由 Word 计算**的，document.xml 里每个段落只存一个引用（`numId` + `ilvl`），真实编号数字从未写进 XML。python-docx 不做渲染计数，所以 `paragraph.text` 永远不含编号前缀。

#### 9.6.2 三层提取策略（按可靠性优先级）

**第一层：Heading 样式名识别章节结构（最可靠，主路径）**
- 用 `paragraph.style.name` 判断（`"Heading 1"` / `"Heading 2"` / ...）
- 这是 python-docx 最可靠的能力，**专利交底书的章节几乎都是 Heading 样式驱动的**
- 章节层级 = Heading 数字；章节标题 = 段落文本
- 这一层保证"章节结构"99% 能正确提取，不依赖编号

**第二层：NumberingResolver 解析自动编号（尽力而为，增强）**
- 通过 `doc.part.numbering_part.element` 拿到 numbering.xml（python-docx 暴露了 lxml 底层）
- 自实现计数器逻辑：
  - 解析 `abstractNum` 的 `lvl / lvlText / numFmt / start`
  - 段落遍历时维护 `(numId, ilvl)` 计数器并自增
  - 处理多级层级回溯（"1.1.1"的各段依赖父级计数）
  - 处理 `lvlOverride / startOverride`（列表重启）
  - 处理 Heading 绑定（`w:lvl/w:pStyle` 把 Heading 映射到 numbering level）
- 把 `lvlText` 模板（`%1.%2.`）与计数器组合成最终编号文本
- 预估代码量：300-500 行，需配套单元测试

**第三层：正则兜底（覆盖手敲编号，容错）**
- 现实中很多用户**手动敲"1.1"文本**而非用自动编号
- 当 `numPr` 缺失但段落文本以 `\d+(\.\d+)*[\.\、]` 开头时，回退到文本匹配提取编号
- 与第二层互为补充

#### 9.6.3 样式提取的继承陷阱

字体/字号/加粗读取需处理 Word 的**四级继承**（直接格式 > 段落样式 > base_style 链 > docDefaults）：
- `run.font.size` 返回 `None` 表示"继承"，必须自己沿 `style.base_style` 回溯直到非 None，最终落到 docDefaults
- 中文字体需读 `rPr/rFonts@w:eastAsia`（python-docx 的 `font.name` 只覆盖默认通道，中文交底书常见坑）

需自写一个 `StyleInheritanceResolver`。

#### 9.6.4 编号解析的定位与降级

- 编号解析是 **best-effort**，不保证 100% 还原
- 即使编号提取失败，**章节结构（来自第一层 Heading）依然可靠**——章节在，只是编号格式可能退化为默认
- 解析失败不阻断模板创建，只在 ParseJob.metadata 记录 warnings

#### 9.6.5 升级口（若复杂度超预期）

若实践中遇到大量复杂多级大纲编号 + 列表混用、自写解析器维护成本过高，可升级到 **Aspose.Words for Python**（商业库，唯一能真正计算渲染编号，约 $1,199 起）。LLMClient 与解析层解耦，替换不影响其他模块。

### 9.7 模板变更对已有项目的影响

- **项目创建时快照模板结构**：把 Template.structure 的章节信息复制到各 Section
- 之后**模板与项目解耦**：
  - 模板被修改 → **不影响**已有项目
  - 模板被删除 → **不影响**已有项目（项目 Section 已自包含 title/key/order）
- 这样保证历史项目稳定，也简化数据关系（项目不依赖模板存在）
- 仅项目**创建时刻**读模板，创建后 Template 变更只在"新建项目"时体现

---

## 10. 知识库与 RAG 架构（MVP 实现基础 RAG，基于 LangChain Embedding + pgvector）

这是天工作为 **Agent 系统**的核心基础设施——让每一次撰写都为下一次积累知识。MVP 实现基础 RAG：交底书归档 → 向量化入库 → 新交底书撰写时语义检索相似案例。

### 10.1 整体流程

```
┌─────────────── 入库（写时） ─────────────────┐
│                                               │
│  交底书完成 (status=completed)                │
│       │                                       │
│       ▼ 用户点「归档」或自动触发              │
│  归档服务 (ArchiveService)                    │
│   ├─ 按章节分块 (Chunker)                     │
│   │   每章 → 1~N 个 chunk（按 token 上限切）  │
│   ├─ 调 EmbeddingClient 向量化                │
│   └─ 写入 KnowledgeChunk (含 embedding)       │
│       │                                       │
│       ▼ Project.status = archived             │
│       archived_at = now                       │
└───────────────────────────────────────────────┘

┌─────────────── 检索（读时） ─────────────────┐
│                                               │
│  用户在写新交底书的某章节                      │
│       │                                       │
│       ▼ AI 装配上下文时                       │
│  RetrieverService                             │
│   ├─ 把「当前章节 key + 已完成章节 summary」  │
│   │  组成查询文本                             │
│   ├─ 调 EmbeddingClient 得查询向量            │
│   ├─ pgvector 余弦相似检索 top-K              │
│   │  WHERE user_id = 当前用户                 │
│   └─ 返回 KnowledgeChunk 列表 + 来源信息      │
│       │                                       │
│       ▼ 注入 AI 上下文的「知识库层」          │
│  [知识库层] 相似案例参考：                     │
│   · 《XX装置》技术方案：……（相似度 0.87）     │
│   · 《YY方法》背景技术：……（相似度 0.82）     │
└───────────────────────────────────────────────┘
```

### 10.2 分层架构

```
┌─────────────────────────────────────────────┐
│  RetrieverService (检索服务)                 │
│  └─ 组查询文本 → 检索 → 返回 top-K 结果      │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  Chunker (分块器)                            │
│  └─ 文档/章节 → 分块（带重叠，保上下文）      │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  EmbeddingClient (向量化抽象)                │
│  ├─ GLMEmbeddingClient (默认，智谱 API)      │
│  └─ 统一 embed(text) -> vector               │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  VectorStore (向量存储抽象)                  │
│  └─ PgVectorStore (默认，pgvector)           │
│     · upsert(chunks) / search(query_vec, k)  │
└─────────────────────────────────────────────┘
```

### 10.3 分块策略 (Chunker)

- **按章节分块**：交底书的章节天然是语义边界，优先按 Section 分块
- **超长章节二次切分**：单章超过 token 上限（如 512）时，按段落切分，**带 10-15% 重叠**保留上下文衔接
- **chunk 元信息**：每个 chunk 记录 `source_id`(Project) + `source_section_key`(章节) + `chunk_index`，检索结果可精确定位来源
- **短章节合并**：单章过短（如"发明名称"）不单独成块，并入相邻章节或作为元信息

### 10.4 RAG 注入 AI 上下文（更新 5.3 上下文装配）

原 5.3 节的上下文是四层，现在新增**第五层「知识库层」**：

```
[系统层]   角色 + 输出规范 + 格式约束
[知识库层] ⭐ 检索到的相似历史案例片段（top-K，带来源标注）  ← 新增
[项目层]   已确认章节的 summary
[章节层]   当前章节的 key 对应的专属指引
[对话层]   本章节历史对话
```

- **触发时机**：进入新章节、用户提问、用户点"生成本章草稿"时，异步检索并注入
- **token 预算**：知识库层有独立 token 预算（如 top-3，每个 chunk ≤ 300 token），与项目层/对话层共享总预算
- **来源标注**：注入时明确标注"以下参考自历史案例《XX》"，AI 生成时可引用，避免幻觉
- **用户可见**：前端在 AI 对话区展示"参考了 N 条历史案例"的提示，可展开查看

### 10.5 归档与去重

- **归档时机**：交底书 status=completed 后，用户点「归档到知识库」；或项目长期未编辑时提示归档
- **幂等**：重复归档同一 Project，先删除该 source_id 的旧 chunk，再重新生成（避免重复向量）
- **更新**：用户修改已归档交底书 → 提示"内容已变更，是否更新知识库" → 重新分块向量化
- **删除**：删除归档项目时，级联删除其 KnowledgeChunk

### 10.6 检索质量与降级

- **相似度阈值**：低于阈值（如 0.7）的结果不注入，避免噪音
- **空结果降级**：用户刚注册、知识库为空时，不注入知识库层，AI 正常工作（只是没有历史参考）
- **混合检索（后续）**：MVP 用纯向量检索；后续可加关键词检索（tsvector）+ 重排序（rerank）提升召回

### 10.7 隐私与隔离

- **用户隔离**：检索强制 `WHERE user_id = current_user`，A 看不到 B 的知识库

### 10.8 agent 记忆（Memory）——MVP 不做，架构预留

明确区分：MVP 的"知识"是**历史案例的客观内容**（RAG），不是**用户偏好的主观画像**（Memory）。后者预留扩展点：

```
未来 UserMemory（预留，MVP 不建表）
  id, user_id, memory_type(writing_style/tech_domain/terminology/preference),
  content, confidence, created_at, updated_at
```
- 由 agent 在交互中自动抽取（"用户偏好简洁表述""用户技术领域是芯片设计"）
- 注入 system prompt 影响生成风格
- MVP 不实现，但 EmbeddingClient/VectorStore 的抽象使其可平滑加入

---

## 11. MVP 范围与验收

### 11.1 P0（MVP 必须交付）

| # | 功能 | 验收标准 |
|---|---|---|
| 1 | 用户注册/登录（邮箱+密码） | 注册、登录、登出，会话保持；密码 bcrypt |
| 2 | 资源级授权校验 | 越权访问他人资源返回 404（13.1） |
| 3 | 项目管理（增删改查） | 新建/打开/重命名/删除项目（硬删除级联）；Project.stage=disclosure |
| 4 | 交底书元信息 | 发明人/申请人/单位/日期/关键词可填写与编辑（3.2 metadata） |
| 5 | 模板上传与异步解析 | 上传 Word → 异步解析（章节结构可靠 + 样式 + 编号尽力）→ 列表可见（9.6） |
| 6 | 异步任务恢复 | 服务重启后卡住/失败的解析任务自动重入队（13.3） |
| 7 | 模板管理 | 列表、预览、重命名、删除、设默认 |
| 8 | 创建项目选模板 | 可选系统默认或自有模板，按模板快照生成章节（9.7） |
| 9 | 章节大纲与严格顺序 | 进度可视化，完成当前解锁下一，可返回修改；支持纯手写路径（2.2.2） |
| 10 | AI 引导对话 | 每章节 AI 主动提问、回答、流式输出 |
| 11 | AI 生成章节草稿 | 一键生成，Markdown→Tiptap 入库 |
| 12 | 富文本编辑器 | Tiptap，基础格式 + 选中重写/扩写/精简 |
| 13 | 富文本自动保存 | 防抖 2s 保存 + 乐观锁 409 处理（13.4） |
| 14 | 跨章节上下文 | AI 写后文引用前文 summary；确认章节异步生成 summary，失败降级（5.9） |
| 15 | 附图章节 | 上传图片 + 文字描述，AI 基于描述润色图注（9.5） |
| 16 | 章节版本快照 | 确认章节时自动存版本，可查看/回滚 |
| 17 | 全篇预览 | 合并所有章节（含抬头元信息），只读预览 |
| 18 | 导出 Word/Markdown | Tiptap→docx 套用模板样式 + 抬头（13.5） |
| 19 | 流式中断与心跳 | 用户可停止；SSE 心跳保活；断线内容保留为草稿（13.8） |
| 20 | **交底书归档** | 完成后归档：分块 → 向量化 → 写入 KnowledgeChunk；Project.status=archived（10.1/10.5） |
| 21 | **知识库 RAG 检索** | 写新交底书时，检索用户历史案例 top-K 注入 AI 上下文；用户隔离；空库降级（10.4/10.6/10.7） |
| 22 | **审查与评分（Rubric 驱动）** | 系统默认 Rubric 逐维度评分，输出结构化报告（6.3/6.4/6.5） |
| 23 | **评分跨对话稳定** | 同一交底书+Rubric，新对话审查 N 次标准差 ≤ 3 分；含自一致性与 Store 记忆（6.2/6.6/6.7） |
| 24 | **Rubric 自定义（覆盖式）** | 用户可编辑维度/权重/标准，覆盖系统默认；审查记录关联 Rubric 快照（7.2/6.4） |
| 25 | **知识库自定义（增量）** | 用户可上传文档扩充知识库；可管理/删除（7.3） |
| 26 | **技能自定义（增量）** | 用户可启用/禁用内置技能（rag/review/consistency 等）（7.4） |
| 27 | **管理员：全局内容维护** | admin 可管理系统默认模板/Rubric/内置技能（8.2①） |
| 28 | **管理员：全局 LLM 配置** | admin 可配全局 key（base_url/api_key/model）+ 全局开关 + 按用户限流 + 测试连通性（8.4.2） |
| 28a | **用户：自定义配置自配** | 用户可填任意 OpenAI 兼容 Provider 的 key 覆盖全局；可测试连通性；可启用/禁用（8.4.3） |
| 28b | **Provider 三级解析** | 用户自配 > 全局 > 报错引导；全局关闭时强制自定义配置（8.4.1） |
| 28c | **Key 加密存储** | api_key AES 加密落库；API 不返回明文；不记日志（8.4.5） |
| 28d | **无可用配置引导** | 全局关闭且用户未配 key 时，强制引导到配置页，未配置不可用 AI（8.4.3） |
| 29 | **管理员：用户运营** | admin 可看用户列表（聚合）、封禁/解禁、重置密码；**不可见用户私人数据**（8.2③/8.3） |
| 30 | **管理员：监控运维** | admin 可看日志、LLM 调用统计；审计管理员自身操作（8.2④⑤） |
| 31 | **首个管理员创建** | 命令行脚本创建首个 admin，不开放注册管理员（8.1） |

### 11.2 P1（后续迭代）

**阶段① 增强**：
- 专利检索（接口已预留）
- PDF 导出
- 全篇质量检查报告
- 灵感补全（Tab 补全）
- agent 记忆（写作偏好/技术领域画像，7.8）

**知识库增强**：
- 混合检索（向量 + 关键词 + rerank）

### 11.4 非功能要求

- **性能**：AI 首 token < 2s；普通 API < 300ms；向量检索 < 200ms
- **安全**：密码 bcrypt；JWT httpOnly cookie；ORM 参数化防注入；详见第 13 章（资源级授权、文件上传安全、删除语义等）
- **可观测**：loguru 结构化日志；LLM/embedding 调用记录用量与耗时
- **可部署**：docker-compose 一键起

---

## 12. 实施阶段（概览，详细计划在 writing-plans 阶段细化）

```
阶段 0: 工程脚手架（仓库结构、docker-compose、pgvector、LangGraph、lint、CI）
阶段 1: 用户与项目基础（认证、项目 CRUD、Project.stage）            
阶段 2: 模板模块（上传、异步解析、管理、默认模板种子）             
阶段 3: 富文本编辑器 + 章节数据模型                                
阶段 4: 撰写状态图（LangGraph WritingGraph：节点/Checkpoint/HITL/SSE）
阶段 5: 章节引导对话 + 生成草稿 + 严格顺序状态机                   
阶段 6: 段落重写 + 跨章节上下文摘要                                
阶段 7: 版本快照 + 全篇预览                                       
阶段 8: 导出（Word/Markdown，套用模板样式）                        
阶段 9: 知识库与 RAG（LlamaIndex：索引/检索/重排/归档/注入）       
阶段 10: 审查引擎（ReviewGraph + Rubric + 自一致性 + Store 记忆）   
阶段 11: 自定义能力（Rubric 覆盖配置/知识库扩充/技能挂载）          
阶段 12: 管理员后台（全局内容维护/AI 配置/用户运营/监控审计）       
阶段 13: 稳定性验证（跨对话复现性测试）+ 打磨与联调（E2E）          
```

> ℹ️ **实际落地说明**：MVP 按 `docs/superpowers/plans/archive/` 下的计划 1–7b 拆分实施，全部已完成（见 README 进度表）。其中：
> - 阶段 4「撰写状态图」实际用 **LangChain + 手搓编排器**（`app/ai/orchestrator.py`）实现，未用 LangGraph StateGraph/Checkpoint/HITL
> - 阶段 9「知识库 RAG」实际用 **LangChain Embedding + pgvector**，未用 LlamaIndex（GOTCHAS E3）
> - 阶段 10「审查引擎」用 `services/review_service.py` 确定性管线实现，未用 ReviewGraph 框架

---

## 13. 工程细节与安全

本节集中定义之前散落/遗漏的工程决策，避免实现时临时拍脑袋。

### 13.1 资源级授权校验（安全，必须）

**问题**：仅靠 JWT 登录不够。若用户 A 构造 `/api/v1/sections/{B的section_id}/chat`，越权操作他人数据。

**方案**：
- 所有资源级 API（project / section / message / template / attachment）**必须校验资源归属**
- 通过 FastAPI 依赖注入：`get_current_user` 解析 JWT 拿 user_id，再校验 `resource.user_id == current_user.id`
- 不符则返回 **404（而非 403）**——避免通过状态码探测他人资源是否存在
- 系统内置模板（`is_system=true`）所有登录用户可读，但不可改删

### 13.2 文件上传安全

- **类型校验**：上传的 .docx 必须校验 MIME 类型 + 文件头魔数（PK\x03\x04），不轻信扩展名
- **大小限制**：单文件上限（如 10MB），防止大文件耗尽资源
- **zip 炸弹防护**：解压前检查压缩比，超阈值（如 100:1）拒绝
- **存储路径**：用 UUID 生成存储名，**绝不使用用户提供的文件名**作为路径，防路径遍历
- **图片上传**：同样校验类型（png/jpg/jpeg/gif）、大小、魔数

### 13.3 异步任务与状态恢复机制

**两类异步，两种恢复**：

**① 模板解析任务（BackgroundTasks）**
- 问题：FastAPI BackgroundTasks 是进程内的，服务重启/崩溃时正在执行的解析任务会丢失，ParseJob 永远停在 pending/processing
- 方案：ParseJob 已有 status 字段；应用启动时执行**恢复扫描**，找 `processing`（异常中断）或卡 `pending` 超阈值（10 分钟）的任务重新入队；幂等设计
- MVP 用此机制，无需 Celery

**② Agent 执行状态（撰写/审查）—— v1.3 起由 LangGraph 接管**
- LangGraph 的 **Checkpoint + PostgresSaver** 自动把图状态（当前章节、对话历史、审查进度）落库
- 服务重启后，图从最近 Checkpoint **自动续跑**（Durable Execution）
- 这取代了 v1.2 手搓的恢复逻辑，且更强——任何节点中断都能从断点恢复，不止解析任务
- HITL 暂停（等用户确认章节/审查意见）也是靠 Checkpoint：`interrupt()` 后状态持久化，用户回来 `resume` 继续

### 13.4 富文本自动保存策略

- **触发**：前端编辑器内容变化后**防抖 2 秒**触发保存；失焦/离开页面强制保存
- **接口**：`PUT /api/v1/sections/{id}/content`，请求体带 `content`（Tiptap JSON）+ `updated_at`（当前已知版本）
- **乐观锁**：后端比对请求的 `updated_at` 与数据库当前值：
  - 一致 → 更新成功，返回新的 `updated_at`
  - 不一致 → 返回 **409 Conflict**，附服务端当前内容
- **多 tab 冲突**：MVP 接受 last-write-wins，但通过 409 让前端有机会提示"内容已被另一处修改"。前端可展示冲突让用户选择保留哪个版本
- **保存指示**：编辑器顶部显示"保存中/已保存/保存失败"状态

### 13.5 导出渲染器（Tiptap JSON → docx）

**问题**：导出链路 `Tiptap JSON → docx 套模板样式`需要一个渲染器，之前未设计。

**映射表**（Tiptap node → docx 元素 + 模板样式查找）：

| Tiptap node | docx 元素 | 样式应用 |
|---|---|---|
| heading (level 1) | Paragraph | 应用 Template.styles 中 "Heading 1" 样式 |
| heading (level 2) | Paragraph | 应用 "Heading 2" 样式 |
| paragraph | Paragraph | 应用 "Normal" / 正文样式 |
| bulletList / listItem | Paragraph + List | 应用编号规则（numbering） |
| orderedList / listItem | Paragraph + List | 应用编号规则 |
| bold / italic mark | Run.bold / .italic | 直接格式 |
| table | Table | docx 原生表格 |
| image | Inline shape | 从 storage_path 读取嵌入 |
| codeBlock | Paragraph（等宽字体） | 等宽字体样式 |

**渲染流程**：
1. 读取项目的 Section 列表（按 order 排序）
2. 套用 Project 关联的模板 styles（创建时快照，非实时读 Template——已解耦）
3. 先写抬头（Project.metadata：发明人、申请人、日期等）
4. 逐章节渲染：标题（Heading 样式）→ 内容（遍历 Tiptap JSON 映射）
5. 生成 .docx 返回下载

**单独测试**：导出渲染器需配套单元测试（给定 Tiptap JSON → 校验生成的 docx 结构），因为这是产出物的最后一道关。

### 13.6 删除语义

- **项目删除**：硬删除项目 + 级联删除其下 section / message / version / attachment（MVP 不做软删除，避免软删数据累积）；附件文件一并删除
- **模板删除**：硬删除（系统模板除外）；**不影响已基于它创建的项目**（项目已解耦，见 9.7）
- **版本快照**：随 section 删除而删除；不做版本数量上限（MVP 简化）
- **删除前确认**：前端二次确认，删除不可恢复

### 13.7 项目 completed 判定

- 所有 section 的 status 均为 `confirmed` 时，前端提示"交底书已完成，可导出"
- **不自动**转为 completed 状态（避免用户还在微调时被锁死）
- 用户手动点"标记完成"或"导出"时，project.status 置为 completed
- completed 状态的项目仍可返回修改（改后 section 回到 drafting，project 可选回退到 in_progress）

### 13.8 SSE 连接管理

- **超时**：单次 AI 流式请求最长 120s，超时后端主动关闭并发 error 事件
- **心跳**：流式期间每 15s 发一个 `event: ping`，防止代理/防火墙断开空闲连接
- **断线**：前端检测 SSE 连接断开后**不自动重连**（AI 生成是非幂等的，重连可能重复扣费）；提示用户"连接断开，已生成内容已保存为草稿，可重新生成"
- **客户端取消**：用户点"停止"→ 前端关闭 SSE → 后端检测连接关闭后取消 LLM 请求

### 13.9 测试策略

- **后端**：pytest，分层
  - services 层：业务逻辑单元测试（mock repo）
  - ai 层：mock LLMClient（固定响应），测试 Prompt 装配与 Markdown→Tiptap 转换
  - api 层：FastAPI TestClient 集成测试（含鉴权、越权 404 校验）
  - 解析层：用真实 .docx 样本测试 SectionStructureExtractor / NumberingResolver / StyleInheritanceResolver
  - 覆盖率目标：核心模块（ai / services / parse）≥ 80%
- **前端**：Vitest 单元测试组件逻辑 + Playwright E2E 覆盖关键路径（登录→建项目→写一章→导出）
- **关键路径 E2E**：上传 Word 生成模板 → 建项目 → AI 对话生成一章 → 编辑 → 导出 Word

---

## 附录 A：决策记录

| 决策点 | 选择 | 理由 |
|---|---|---|
| MVP 切入点 | 个人创作 | 验证核心价值，风险最低 |
| 交互范式 | 混合模式（引导对话 + 编辑器 + 段落重写） | 体验最好 |
| 检索 | 留接口不实现 | 聚焦核心价值 |
| 技术栈 | Python(FastAPI) + Next.js | AI 生态最佳 |
| 富文本 | Tiptap + JSON | 结构化、AI 友好 |
| 数据库 | PostgreSQL | JSONB 支持 |
| LLM | GLM-5.2（OpenAI 兼容抽象） | 国产友好、可切换 |
| AI 输出 | Markdown → 后端转 Tiptap | 最鲁棒 |
| 章节结构 | 模板驱动（非固定 8 阶段） | 支持自定义模板 |
| 章节顺序 | 严格顺序 | 保证质量、简化状态机 |
| 模板模块 | MVP 完整包含（含样式导出） | 用户明确要求 |
| 附图章节 | 文字描述驱动，不引入多模态 | MVP 控制复杂度（9.5） |
| 交底书元信息 | Project.metadata JSONB 字段 | 可选填、低频改、避免过度规范化 |
| confirmed 判定 | 内容非空 + 用户主动确认，与 AI 无关 | 支持纯手写路径 |
| 模板与项目关系 | 创建时快照，之后解耦 | 历史项目稳定 |
| 资源越权返回码 | 404 而非 403 | 防资源探测 |
| 多 tab 冲突 | last-write-wins + 409 提示 | MVP 简化 |
| 删除语义 | 硬删除 + 级联（不做软删除） | MVP 简化 |
| 异步任务 | BackgroundTasks + 启动恢复扫描 | 无需 Celery，MVP 足够 |
| 产品愿景 | 全生命周期 Agent（交底书→协作→答复→归档） | 陪伴专利全过程，非单纯写作工具（1.6） |
| MVP 扩展策略 | 功能不扩，架构预留记忆 | 保住聚焦，避免返工 |
| 知识库落地 | MVP 做基础 RAG（交底书归档+检索注入） | 让每份交底书沉淀为知识 |
| 向量存储 | pgvector（业务库同库） | 无需独立向量库，运维简单 |
| Embedding | 智谱 embedding API（OpenAI 兼容） | 与 LLM 同厂商，中文好 |
| Agent 记忆 | MVP 不做，架构预留（UserMemory） | 主观画像复杂度高，后续迭代 |
| 案件主线 | Project 预留 stage 字段（MVP=disclosure） | 平滑升级到全生命周期 |
| Agent 框架 | 设计：LangGraph（编排）+ LlamaIndex（RAG）；实际：**LangChain（编排手搓 + Embedding）+ pgvector**（v1.5.1 校正，详见顶部「实现现状」+ GOTCHAS E3）| 功能达成，框架红利（Checkpoint/Store）暂缺，后续可引入 |
| 审查功能 | MVP P0（非后续迭代） | 跨对话稳定是核心质量目标，须尽早验证 |
| 评分机制 | Rubric 驱动 + 自一致性 | 根治标准漂移 + 平滑概率波动 |
| Rubric 来源 | 系统默认 + 用户覆盖 | 开箱即用 + 可定制 |
| 自定义语义 | Rubric 覆盖式 / 知识库·技能增量式 | 区分配置类型，数据模型分别处理 |
| 管理员定位 | C 系统运维 | MVP 不做组织/计费，避免臆造需求 |
| 数据可见性红线 | 用户私人数据管理员默认不可见 | 专利是敏感商业数据，强制隔离 |
| 首个管理员产生 | 命令行脚本创建，非注册 | 避免"谁能成为管理员"的安全漏洞 |
| LLM key 策略 | 管理员全局开关 + 用户可覆盖（自定义配置） | 灵活的成本归属：平台买单或用户自付 |
| 用户自带 Provider | 任意 OpenAI 兼容（base_url+key+model） | 契合现有抽象，不绑死厂商 |
| Key 解析优先级 | 用户自配 > 全局 > 报错 | 用户自配始终优先，成本可控 |
| Key 安全 | AES 加密落库，不明文返回/不记日志 | API key 是敏感凭证 |

## 附录 B：待后续明确（不影响 MVP 启动）

- LLM 具体 API key 与配额（部署时配置）
- 文件存储方案（MVP 本地，后续对象存储）
- 前端主题/视觉风格（进入实现时定）

## 附录 C：已知技术风险与缓解

| 风险 | 等级 | 缓解措施 |
|---|---|---|
| Word 自动编号解析（python-docx 硬限制） | 🔴 高 | 三层策略（Heading 优先 + NumberingResolver + 正则兜底）；章节结构不依赖编号；详见 9.6 |
| Word 样式继承解析（None 陷阱、eastAsia 字体） | 🟡 中 | 自写 StyleInheritanceResolver，配套测试 |
| Markdown→Tiptap 转换边界（复杂表格/嵌套） | 🟡 中 | 降级为纯文本兜底 + 日志；渐进支持 |
| AI 输出偏离指令（不输出 Markdown） | 🟡 中 | system prompt 强约束 + 后处理清洗 |
| LLM 流式中途失败 | 🟡 中 | 已生成内容保留为 draft，提示重试 |
| 大文档 token 超限 | 🟢 低 | summary 机制 + 对话历史压缩 |
| 多 tab 并发编辑覆盖 | 🟢 低 | 乐观锁 409 提示，MVP 接受 LWW |
| RAG 检索召回噪音（不相关案例误导 AI） | 🟡 中 | 相似度阈值过滤 + 来源标注让 AI 可识别 + 用户可见可关闭 |
| pgvector 规模化性能（数据量大后检索变慢） | 🟢 低 | MVP 数据量小；后续可加 IVFFlat/HNSW 索引或迁独立向量库 |
| embedding API 费用/限流 | 🟢 低 | 仅归档时批量调用；按用户限流；缓存向量 |
| 归档与编辑冲突（归档后用户又改了） | 🟡 中 | 提示"内容已变更，是否更新知识库"；幂等重生成（10.5） |
| 框架学习曲线（LangGraph 未启用 / LlamaIndex 已弃用） | 🟢 已缓解 | MVP 实际仅用 LangChain，学习成本可控；如后续启用 LangGraph 需投入学习 |
| 框架版本锁定 / Breaking Change | 🟢 低 | LangChain 1.0 LTS 承诺；锁版本。LlamaIndex 已弃用（GOTCHAS E3）|
| 审查稳定性测试不达标（标准差 > 3） | 🔴 高 | 调整 Rubric 精度、增加自一致性 N、缩小评分范围；必要时降级为"通过/复核/不通过"三档 |
| Rubric 过严或过松（用户感受差） | 🟡 中 | 系统默认 Rubric 经调优；用户可覆盖；审查报告给证据可解释 |
| Store 记忆膨胀（审查记录累积） | 🟢 低 | namespace 按 (user, project) 隔离；定期归档旧记录 |
| 管理员权限滥用（越权看用户数据） | 🟡 中 | 数据可见性红线（8.3）+ 审计日志（8.2⑤）+ 管理接口仅 /admin/* 路由 + require_admin 强制校验 |
| 管理后台被普通用户访问 | 🟢 低 | 路由级 require_admin 依赖；前端 /admin 入口按 role 条件渲染 |
| 用户 LLM key 泄露 | 🟡 中 | AES 加密落库；API 掩码返回；不记日志/堆栈；ENCRYPTION_KEY 部署期严格保管 |
| 用户填入无效 key 导致功能不可用 | 🟡 中 | 配置后强制"测试连通性"；失败给清晰错误（401/网络/模型名错误） |
| 全局 key 被滥用（用户刷额度） | 🟡 中 | llm_per_user_limit 按用户限流；监控异常用量；必要时关闭全局强制自定义配置 |
