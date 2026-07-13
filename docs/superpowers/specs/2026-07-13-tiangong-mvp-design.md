# 天工 (TianGong) — MVP 设计文档

> AI 驱动的专利交底书撰写智能体
> 从技术交底到专利申请文件，巧夺天工。

- **文档版本**: v1.0
- **创建日期**: 2026-07-13
- **状态**: 待评审
- **作者**: tl.m + ZCode

---

## 1. 产品定位与边界

### 1.1 一句话定位

**「天工」是个人发明人的 AI 专利交底书撰写陪伴助手**：从一个模糊的灵感出发，通过结构化对话引导 + 富文本编辑 + 可套用的格式模板，产出一份结构完整、逻辑清晰、可直接交给专利代理人的技术交底书。

### 1.2 目标用户

- **MVP**: 个人发明人 / 工程师 / 研究员（有技术灵感，不擅长把灵感整理成规范的交底书）
- **长期愿景**: 混合平台（个人 + 研发团队 + 代理机构），平台化是后续演进方向

### 1.3 「是」什么（MVP 范围内）

- 单人使用的 Web 应用（登录后进入个人工作台）
- 从「灵感描述」到「结构化交底书草稿」的端到端引导
- 每份交底书可在线富文本编辑、多版本保存、导出 Word/PDF/Markdown
- **模板模块**：用户上传 Word 样本，系统异步解析为可复用的格式模板（章节结构 + 样式 + 编号），创建项目时套用
- AI 在每个章节提供三种能力：**引导提问、内容生成、段落重写**

### 1.4 「不是」什么（MVP 明确排除）

| 排除项 | 说明 |
|---|---|
| 真实专利检索 | 留接口（`SearchService` 抽象 + `prior_art_refs` 字段），后续集成 |
| 法律状态判断 / 新颖性评估 | 属专业服务，不做 |
| 多人协作 / 团队 / 审批 | 平台化阶段再加 |
| 正式专利申请文件撰写 | 产出物是**交底书**（给代理人的技术输入），非法律文件 |
| 移动端 | 桌面 Web 优先 |
| 多语言 | MVP 仅中文 |

### 1.5 成功标准（MVP）

1. 一个完全不懂专利写作的用户，能用天工在 **1~2 小时内**产出一份「代理人看了不摇头」的交底书
2. 交底书覆盖标准章节（由模板定义；系统默认模板含：发明名称、技术领域、背景技术、发明目的/技术问题、技术方案、有益效果、附图说明、具体实施方式）
3. 用户可上传自有 Word 模板，系统解析后可套用其结构与样式
4. 用户可随时中断、回来继续，不丢失上下文

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
- 已确认的章节**可以随时返回修改**。MVP 简化：返回修改不强制级联重置后续章节状态（避免复杂的级联逻辑），用户自行判断是否需要重新审视后续内容

#### 2.2.3 单章节内的交互单元

每个章节是一个统一的交互单元，包含：
- **左侧大纲**：所有章节列表，当前章节高亮，已完成章节打勾
- **中间编辑器**：当前章节的富文本内容
- **右侧 AI 对话**：本章节独立的对话流
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
| created_at | datetime | |
| last_login_at | datetime | |

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

#### Project（项目/交底书）
| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| template_id | UUID FK | 基于哪个模板 |
| title | str | 项目名 |
| status | enum | draft / in_progress / completed |
| current_section_order | int | 当前章节序号 |
| progress_pct | int 0-100 | |
| prior_art_refs | JSONB nullable | 检索结果预留（MVP 不用） |
| created_at | datetime | |
| updated_at | datetime | |

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

### 3.3 关键设计决策

1. **富文本存 JSON 不存 HTML**：选 Tiptap（基于 ProseMirror），JSON 结构化，便于 AI 读写、diff、版本管理
2. **对话按 Section 隔离**：每章节独立对话历史，互不污染；但 AI 生成时可读取其他已确认 Section 的 `summary` 作为上下文
3. **版本粒度到 Section**：确认章节或手动触发时打快照，不做全篇版本（太重）
4. **模板结构嵌入存储**：TemplateSection 作为 Template.structure 的 JSONB 数组，不单独建表（章节数少、读为主、避免过度规范化）
5. **检索接口预留**：`prior_art_refs` 字段 + `SearchService` 抽象层，结构在，MVP 不实现

---

## 4. 系统架构与技术选型

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│  浏览器 (Next.js 前端)                               │
│  ├─ 页面路由 (App Router)                            │
│  ├─ Tiptap 富文本编辑器                              │
│  ├─ AI 对话面板（SSE 流式渲染）                      │
│  ├─ 模板管理界面                                     │
│  └─ 状态管理 (Zustand + TanStack Query)             │
└────────────────────┬────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│  后端 (FastAPI 单体)                                 │
│  ├─ API 层 (路由/校验/鉴权)                          │
│  ├─ 业务层 (用户/项目/模板/章节/版本/导出)           │
│  ├─ AI 编排层 (LLMClient/Prompt/流式)                │
│  ├─ 模板解析层 (Word 解析/异步任务)                  │
│  └─ 基础设施层 (DB/存储/LLM Client)                  │
└───┬──────────┬──────────────┬───────────┬───────────┘
    │          │              │           │
┌───▼───┐ ┌───▼────┐ ┌──────▼─────┐ ┌───▼──────┐
│Postgres│ │文件存储│ │  LLM API   │ │异步任务  │
│        │ │本地/对象│ │GLM-5.2默认 │ │Background│
└────────┘ └────────┘ └────────────┘ └──────────┘
```

### 4.2 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 前端框架 | Next.js 14+ (App Router) + TypeScript | 全栈能力、SSR、生态成熟 |
| UI 组件 | shadcn/ui + Tailwind CSS | 可定制、不锁框架 |
| 富文本 | Tiptap v2 | JSON 结构化、AI 友好 |
| 状态管理 | Zustand（UI）+ TanStack Query（服务端） | 轻量、分工清晰 |
| AI 流式 | SSE (Server-Sent Events) | 单向流足够、自动重连 |
| 后端框架 | FastAPI + Python 3.11+ | 异步、类型友好、AI 生态最佳 |
| ORM | SQLAlchemy 2.0 + Alembic | Python ORM 事实标准 |
| 数据库 | PostgreSQL | JSONB 支持好、成熟 |
| 鉴权 | JWT (access + refresh token) | 无状态 |
| LLM 接入 | OpenAI 兼容协议，默认 GLM-5.2 | 国产模型友好、避免锁定 |
| Word 解析 | python-docx | 读取章节/样式/编号 |
| Word 导出 | python-docx | 套用模板样式 |
| PDF 导出 | 浏览器打印 / 后续 weasyprint | MVP 简化 |
| Markdown→Tiptap | markdown-it + 自定义映射 | AI 输出转换 |
| 异步任务 | FastAPI BackgroundTasks（MVP）/ Celery（后续） | 解析模板 |
| 校验 | Pydantic v2 | FastAPI 原生 |
| 配置 | pydantic-settings + .env | 标准 |
| 测试 | pytest + Vitest | 对应规范 |
| 日志 | loguru | 结构化日志 |
| 部署 | docker-compose (web + api + postgres) | 一键起 |

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
│       │   │   └── export_service.py
│       │   ├── ai/             # AI 编排引擎（核心）
│       │   │   ├── llm_client.py
│       │   │   ├── prompt_builder.py
│       │   │   ├── context_assembler.py
│       │   │   ├── stage_prompts.py
│       │   │   ├── orchestrator.py
│       │   │   └── markdown_to_tiptap.py
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

> AI 编排 = Prompt 模板 + 上下文装配 + 流式生成 + 结构化输出

所有 AI 功能（引导提问、内容生成、段落重写）走同一套机制，只是 Prompt 和上下文不同。

### 5.2 引擎分层

```
┌─────────────────────────────────────────────┐
│  API 层 (SSE 流式接口)                       │
│  POST /api/v1/sections/{id}/chat             │
│  POST /api/v1/sections/{id}/generate         │
│  POST /api/v1/sections/{id}/rewrite          │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  编排服务层 (Orchestrator)                   │
│  ├─ ChatService     引导对话                  │
│  ├─ GenerateService 生成章节草稿              │
│  └─ RewriteService  段落重写                  │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  Prompt 引擎 (PromptBuilder)                 │
│  ├─ SystemPromptBuilder (角色/规范/格式)      │
│  ├─ ContextAssembler (装配跨章节上下文)       │
│  └─ StagePromptRegistry (章节 Prompt 模板)   │
└──────────────────┬──────────────────────────┘
┌──────────────────▼──────────────────────────┐
│  LLM 抽象层 (LLMClient)                      │
│  ├─ GLMClient (默认，OpenAI 兼容)            │
│  └─ LLMResponse (统一响应结构)               │
└─────────────────────────────────────────────┘
```

### 5.3 上下文装配（ContextAssembler）

AI 写每一章时，上下文分四层：

```
[系统层]   角色 + 输出规范 + 格式约束
[项目层]   已确认章节的 summary（不是全文，控制 token）
[章节层]   当前章节的 key 对应的专属指引
[对话层]   本章节历史对话
```

- **项目层做摘要而非全文**：已确认章节内容可能很长，注入全文会爆 token。确认章节时由 AI 生成 `summary`，注入摘要即可
- **严格顺序的红利**：前面的章节已确认，其 summary 是可靠的上下文

### 5.4 章节 Prompt 注册表（StagePromptRegistry）

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

### 5.5 AI 输出格式：Markdown → 后端转换

- AI 输出 **Markdown**（对 AI 要求低、最鲁棒）
- 后端用 `markdown_to_tiptap` 转换器（基于 markdown-it 解析 + 映射到 Tiptap node schema）转成 Tiptap JSON 入库
- 支持的 Markdown 元素：标题(##/###)、段落、有序/无序列表、加粗、表格、代码块、图片引用

### 5.6 流式生成协议（SSE）

所有 AI 接口返回 SSE 流，统一事件类型：

```
event: token     data: {"text": "技"}        # 逐 token
event: token     data: {"text": "术"}
event: meta      data: {"section_id": "..."}  # 元信息
event: done      data: {"message_id": "..."}  # 结束
event: error     data: {"code": "...", "message": "..."}  # 出错
```

### 5.7 三种 AI 行为的统一抽象

| 行为 | 触发 | Prompt 策略 | 输出 |
|---|---|---|---|
| 引导对话 | 进入章节/用户提问 | system + 项目上下文 + 章节指引 + 对话历史 | 自然语言（Markdown） |
| 生成草稿 | 用户点「生成本章」 | system + 项目上下文 + 章节指引 + 对话历史 + 「整理为本章草稿」 | Markdown → 转 Tiptap JSON |
| 段落重写 | 选中文字 → 重写/扩写/精简/纠错 | system + 选中段落 + 上下文 + 指令 | Markdown → 替换 Tiptap 片段 |

### 5.8 防御性设计

- **Token 预算控制**：上下文装配时计算 token，超限时对对话历史做「保留首尾、中间摘要」压缩
- **Markdown 解析兜底**：转换失败降级为纯文本段落 + 记录日志
- **流式中断**：用户可「停止」，后端取消 LLM 请求
- **重试与限流**：LLM 调用失败指数退避重试；按用户限流

---

## 6. 模板模块（核心模块）

### 6.1 流程

```
上传 Word (.docx)
   │
   ▼
创建 ParseJob (status=pending)
   │
   ▼ 异步任务 (BackgroundTasks)
   ├─ python-docx 解析文档
   │   ├─ 提取章节：遍历段落，按 Heading 样式/大纲级别识别章节层级
   │   ├─ 提取样式：各级标题字体/字号/加粗/颜色、正文样式
   │   └─ 提取编号：多级列表编号规则
   ├─ 结构化存为 Template (structure + styles + numbering)
   └─ ParseJob status=completed
   │
   ▼
模板出现在「我的模板」列表
   │
   ▼
创建项目时可选此模板 → 项目章节 = 模板章节
```

### 6.2 模板管理

- 列表页：展示用户的所有模板 + 系统默认模板
- 操作：预览（章节结构 + 样式预览）、重命名、删除、设为默认
- 系统默认模板不可删除

### 6.3 模板在 AI 中的作用

- AI 生成内容时参考模板的**章节标题**（作为上下文）
- 章节通过 `key` 匹配 Prompt 策略；用户自定义章节（`key=custom`）用通用策略
- 导出时套用模板的**完整样式**（字体/编号/标题层级）

### 6.4 解析容错

- Word 文档格式千差万别，解析需容错
- 无法识别章节层级时，降级为「按段落顺序、所有章节平级」
- 样式提取失败时，用默认样式兜底
- 解析失败时，ParseJob 记录错误信息，前端提示用户「解析失败，请检查文档格式或使用默认模板」

---

## 7. MVP 范围与验收

### 7.1 P0（MVP 必须交付）

| # | 功能 | 验收标准 |
|---|---|---|
| 1 | 用户注册/登录（邮箱+密码） | 注册、登录、登出，会话保持 |
| 2 | 项目管理（增删改查） | 新建/打开/重命名/删除项目 |
| 3 | 模板上传与异步解析 | 上传 Word → 解析为模板 → 列表可见 |
| 4 | 模板管理 | 列表、预览、重命名、删除、设默认 |
| 5 | 创建项目选模板 | 可选系统默认或自有模板，按模板生成章节 |
| 6 | 章节大纲与严格顺序 | 进度可视化，完成当前解锁下一，可返回修改 |
| 7 | AI 引导对话 | 每章节 AI 主动提问、回答、流式输出 |
| 8 | AI 生成章节草稿 | 一键生成，Markdown→Tiptap 入库 |
| 9 | 富文本编辑器 | Tiptap，基础格式 + 选中重写/扩写/精简 |
| 10 | 跨章节上下文 | AI 写后文引用前文 summary |
| 11 | 章节版本快照 | 确认章节时自动存版本，可查看/回滚 |
| 12 | 全篇预览 | 合并所有章节，只读预览 |
| 13 | 导出 Word/Markdown | 套用模板样式 |

### 7.2 P1（后续迭代）

- 专利检索（接口已预留）
- PDF 导出
- 全篇质量检查报告
- 灵感补全（Tab 补全）

### 7.3 P2+（平台化阶段）

- 多人协作 / 团队 / 权限 / 审批
- 代理机构批量处理
- 模板市场 / 知识库
- 移动端

### 7.4 非功能要求

- **性能**：AI 首 token < 2s；普通 API < 300ms
- **安全**：密码 bcrypt；JWT httpOnly cookie；ORM 参数化防注入
- **可观测**：loguru 结构化日志；LLM 调用记录用量与耗时
- **可部署**：docker-compose 一键起

---

## 8. 实施阶段（概览，详细计划在 writing-plans 阶段细化）

```
阶段 0: 工程脚手架（仓库结构、docker-compose、lint、CI）       
阶段 1: 用户与项目基础（认证、项目 CRUD）                          
阶段 2: 模板模块（上传、异步解析、管理、默认模板种子）             
阶段 3: 富文本编辑器 + 章节数据模型                                
阶段 4: AI 编排引擎核心（LLMClient、Prompt、流式 SSE）            
阶段 5: 章节引导对话 + 生成草稿 + 严格顺序状态机                   
阶段 6: 段落重写 + 跨章节上下文摘要                                
阶段 7: 版本快照 + 全篇预览                                       
阶段 8: 导出（Word/Markdown，套用模板样式）                        
阶段 9: 打磨与联调（错误处理、空状态、加载态、E2E）               
```

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

## 附录 B：待后续明确（不影响 MVP 启动）

- LLM 具体 API key 与配额（部署时配置）
- 文件存储方案（MVP 本地，后续对象存储）
- 前端主题/视觉风格（进入实现时定）
