# 天工 TianGong — 混合编辑器架构：Tiptap 撰写 + ONLYOFFICE 审查/批注/导出

> 日期：2026-07-15（修订：从纯 Tiptap 自建方案改为混合方案）
> 目标：AI 撰写保留 Tiptap 流式体验，审查/协作批注/导出引入 ONLYOFFICE Document Server 获得产品级批注、修订模式（接受/拒绝）、Word/PDF 保真导出。
> 关联：[MVP 设计文档](./2026-07-13-tiangong-mvp-design.md) P1 增强扩展。

---

## 1. 背景与决策

### 1.1 问题

P0 完成后两个瓶颈：
1. 审查结果与编辑脱节——独立 /review 页，无法定位、无法一键应用建议
2. 编辑器体验粗糙——无 Office 风格、无批注、无协作

### 1.2 为什么选混合方案（而非纯自建或全量迁移）

调研了三条路：

| 方案 | 批注/修订 | Office 视觉 | AI 流式生成 | 导出保真 | 与现有代码兼容 | 许可证 |
|---|---|---|---|---|---|---|
| 纯 Tiptap 自建 | 🔴 anchor 定位硬伤 | 🔴 CSS 分页冲突 | ✅ 保留 | 🔴 需手动扩展 | ✅ | ✅ MIT |
| 全量 ONLYOFFICE | ✅ 开箱即用 | ✅ 真 Word 引擎 | ❌ 流式断裂 | ✅ 原生 | 🔴 数据层重写 | ⚠️ AGPL |
| **混合方案** | ✅ ONLYOFFICE 原生 | ✅ ONLYOFFICE 原生 | ✅ Tiptap 保留 | ✅ ONLYOFFICE 原生 | 🟡 需转换层 | ⚠️ AGPL |

混合方案的核心取舍：**AI 撰写阶段用 Tiptap（保流式），审查/协作/导出阶段转 docx 用 ONLYOFFICE**。代价是两套编辑器 + Tiptap↔docx 转换。

### 1.3 AGPL 许可证处理

ONLYOFFICE Docs Community Edition 是 AGPL v.3。天工是私有项目（README 明确标注"私有项目"），当前阶段仅小团队内部使用，不对外提供 SaaS 服务——AGPL 的网络 copyleft 条款暂不触发。若未来商业化对外服务，需购买商业许可。**在 spec 中记录此约束，部署时不公开 ONLYOFFICE 实例的网络入口**。

---

## 2. 双阶段架构

```
┌─ 阶段一：AI 撰写（Tiptap）──────────────────────────┐
│                                                       │
│  Tiptap 编辑器（现有，增强 Office 样式）               │
│  ├─ AI 流式生成草稿（astream_generate → 逐 token）     │
│  ├─ AI 引导对话（astream_chat）                        │
│  ├─ 富文本编辑 + 防抖保存（Plan 9 乐观锁）              │
│  └─ Section.content = Tiptap JSON（不变）              │
│                                                       │
│  撰写完成 → 用户点「进入审查模式」                      │
│  → 后端: Tiptap JSON → 转 docx（python-docx 生成）     │
│  → 存为审查版本 docx                                   │
└───────────────────────┬───────────────────────────────┘
                        ▼
┌─ 阶段二：审查/协作/导出（ONLYOFFICE）─────────────────┐
│                                                       │
│  ONLYOFFICE Document Editor（iframe 嵌入）             │
│  ├─ Word 风格编辑 + 标尺 + 真分页（原生）               │
│  ├─ 批注（代理人/AI 添加，锚定精确到字符）              │
│  ├─ 修订模式（建议修改 → owner 接受/拒绝）              │
│  ├─ 协作（注册用户 + 分享链接访客）                     │
│  ├─ 导出 Word/PDF（原生保真）                          │
│  └─ 保存回调 → 后端接收 docx                           │
│                                                       │
│  owner 接受修订 → ONLYOFFICE 保存 docx                 │
│  → 后端: docx → 转回 Tiptap JSON → 存回 Section.content│
│  → 回到阶段一继续 AI 撰写                              │
└───────────────────────────────────────────────────────┘
```

### 2.1 为什么能解决之前列的 8 个盲点

| 盲点 | 解决方式 |
|---|---|
| ① anchor_text 定位失败 | ✅ ONLYOFFICE 批注锚定在 OOXML 位置，精确到字符，不靠文本搜索 |
| ② CSS column 分页冲突 | ✅ ONLYOFFICE 是真 Word 分页引擎 |
| ③ 导出渲染器不支持新格式 | ✅ ONLYOFFICE 原生导出，格式 100% 保真 |
| ④ 批注不污染原文 | ✅ 批注/修订是 OOXML 独立层，与正文分离 |
| ⑤ 接受批注的乐观锁冲突 | ✅ ONLYOFFICE 内部管理修订状态，保存回调串行化 |
| ⑥ 重新审查旧批注处理 | ✅ ONLYOFFICE 批注有 resolved 状态，重新打开文档旧批注保留 |
| ⑦ 标尺与导出不一致 | ✅ 标尺即真实页边距，导出一致 |
| ⑧ 代理人"实时"非实时 | ✅ ONLYOFFICE 原生支持实时协作（多人同时编辑） |

---

## 3. Tiptap → docx 转换层

这是混合方案的关键接点。现有 `export_service.py` 已有 `_render_tiptap_to_docx`（Tiptap JSON → python-docx），**复用并增强它**作为转换层。

### 3.1 正向转换：Tiptap JSON → docx（进入审查模式）

现有 `_render_tiptap_to_docx` 已支持 paragraph/heading/list/image。需扩展支持 Plan 9/10 新增的 marks（如果 Office 样式工具栏加了字体/颜色等）。实际上混合方案下 Tiptap 编辑器**不需要加 Office 样式工具栏**——因为审查阶段用 ONLYOFFICE，Tiptap 只管 AI 撰写，保持简洁即可。

转换流程：
```
用户点「进入审查模式」
  → 后端: 遍历项目所有章节 → _render_tiptap_to_docx 拼成完整 docx
  → 存到文件系统（uploads/review/{project_id}/{version}.docx）
  → 返回 ONLYOFFICE 编辑器配置（含文件 URL + callbackUrl）
  → 前端: 加载 ONLYOFFICE iframe
```

### 3.2 逆向转换：docx → Tiptap JSON（审查后回写）

这是**有损转换**——docx 里的复杂格式（嵌套表格、文本框、艺术字）无法 1:1 转回 Tiptap JSON。但专利交底书内容以段落+标题+列表+图片为主，这些 Tiptap JSON 能完整表达。

逆向转换用现有的 `parsing/docx_parser.py`（模板解析已建好的 Word 解析器）：
```
ONLYOFFICE 保存回调 → 后端收到 docx
  → docx_parser.parse_docx → 提取结构（章节/段落/标题/列表/图片）
  → 转为 Tiptap JSON（复用 markdown_to_tiptap 的节点构造逻辑）
  → 存回各 Section.content
```

### 3.3 转换损耗的取舍

- **简单格式（段落/标题/列表/图片/加粗/斜体）**：双向无损
- **复杂格式（表格/文本框/分栏）**：正向可生成，逆向降级为纯文本
- **批注/修订**：不转回 Tiptap JSON——它们留在 docx 审查版本里，Tiptap JSON 只存正文

专利交底书 99% 是简单格式，这个损耗可接受。

---

## 4. ONLYOFFICE 集成

### 4.1 部署

docker-compose 增加 ONLYOFFICE Document Server 服务：

```yaml
onlyoffice:
  image: onlyoffice/documentserver:latest
  environment:
    - JWT_ENABLED=true
    - JWT_SECRET=${ONLYOFFICE_JWT_SECRET}
  ports:
    - "8080:80"
  volumes:
    - onlyoffice_data:/var/www/onlyoffice/Data
```

### 4.2 后端集成（FastAPI 作为 Document Manager）

ONLYOFFICE 的集成模式：FastAPI 充当"文档管理服务"，ONLYOFFICE Document Server 充当"编辑服务"。

**加载文档**：
1. FastAPI 生成编辑器配置（JSON）：文档 URL、用户信息、权限、callbackUrl
2. 用 JWT_SECRET 签名配置
3. 前端用 `DocsAPI.DocEditor` 初始化 iframe，传入签名配置

**保存回调**：
1. ONLYOFFICE 编辑后通过 `callbackUrl` POST 到 FastAPI
2. FastAPI 下载更新后的 docx → 触发逆向转换 → 存回 Section.content
3. 返回 `{"error": 0}` 确认

**关键文件**（新建）：
- `apps/api/app/services/onlyoffice_service.py` — 配置生成 + JWT 签名 + 回调处理
- `apps/api/app/api/onlyoffice.py` — `/onlyoffice/config/{project_id}`（返回编辑器配置）、`/onlyoffice/callback`（保存回调）
- `apps/api/app/core/config.py` — 加 `onlyoffice_url`、`onlyoffice_jwt_secret`

### 4.3 文件存储

审查阶段的 docx 存文件系统（复用 Plan 10 的 upload_dir 配置）：
- 路径：`uploads/review/{project_id}/{timestamp}.docx`
- 每次进入审查模式生成新版本（不覆盖旧的）
- ONLYOFFICE 通过 FastAPI 提供的 URL 读取/写回 docx

---

## 5. 审查引擎增强

### 5.1 一致性检查 + 问题定位（不变）

模块①的逻辑与之前设计相同——单次 LLM 一致性检查 + 问题分级。但**输出方式变化**：

- 之前：生成 Annotation 记录 → 前端 Tiptap Decoration 高亮
- 现在：**AI 审查结果通过 ONLYOFFICE API 添加为文档批注**

ONLYOFFICE 提供 API 向文档注入批注（通过 connector API 或在生成 docx 时写入 OOXML 批注层）。AI 审查的每个 issue → 转为 ONLYOFFICE 批注（含 anchor 位置 + 描述 + 建议修改）。

### 5.2 审查流程

```
用户在 ONLYOFFICE 审查视图点「执行 AI 审查」
  → 后端 run_review:
      ① 从 docx 提取文本（python-docx 读段落）
      ② Rubric 评分 + 一致性检查 + 问题分级
      ③ 生成审查结果
  → 后端: 审查结果 → ONLYOFFICE 批注 API 注入文档
      或: 审查结果写入 docx 的 OOXML 批注层 → 重新加载文档
  → ONLYOFFICE 显示批注（AI 批注 + 代理人批注混合）
  → owner 逐条接受/拒绝修订
  → 保存 → 回调 → 逆向转 Tiptap JSON
```

---

## 6. 协作批注

### 6.1 权限模型

| 角色 | 阶段一（Tiptap 撰写） | 阶段二（ONLYOFFICE 审查） |
|---|---|---|
| owner | ✅ 全部 | ✅ 全部（编辑 + 接受/拒绝修订 + 管理批注） |
| reviewer（注册代理人） | ❌ 不可见 | ✅ 只读 + 批注 + 建议修改（修订模式） |
| guest（分享链接访客） | ❌ 不可见 | ✅ 只读 + 批注 |

### 6.2 协作者管理

新增 `ProjectMember` 实体：
- `project_id` FK + `user_id` FK + `role`（reviewer）
- owner 通过邮箱添加代理人

新增 `ShareLink` 实体：
- `project_id` FK + `token`（UUID）+ `expires_at` + `permissions`（read/comment）
- owner 生成链接，访客通过 `/shared/{token}` 进入 ONLYOFFICE 只读+批注模式

### 6.3 批注来源标注

ONLYOFFICE 原生批注显示作者名。AI 审查批注作者标为"AI 审查助手"，代理人批注显示代理人姓名。owner 在侧栏可看到每条批注的来源。

### 6.4 批注不污染原文

ONLYOFFICE 的批注和修订是 OOXML 的独立层（`w:comments` / `w:ins` / `w:del`），与正文（`w:body`）分离。逆向转 Tiptap JSON 时**只提取正文**，批注/修订留在 docx 审查版本里不转回。这天然实现了"批注不污染原始版本"。

---

## 7. 前端架构

### 7.1 两套编辑器视图

| 视图 | 路由 | 编辑器 | 用途 |
|---|---|---|---|
| 撰写视图 | `/projects/{id}` | Tiptap（现有，增强） | AI 流式生成 + 富文本编辑 |
| 审查视图 | `/projects/{id}/review-doc` | ONLYOFFICE iframe | 批注 + 修订 + 协作 + 导出 |

切换：撰写页顶栏「进入审查模式」按钮 → 调后端转换 → 跳转审查视图。审查页顶栏「返回撰写」→ 调后端逆向转换 → 跳回撰写视图。

### 7.2 Tiptap 撰写视图增强

保持现有 Tiptap 编辑器，**不做 Office 样式改造**（Office 体验由 ONLYOFFICE 承担）。仅做：
- 保持 Plan 9 的防抖保存 + 乐观锁
- 保持 Plan 10 的附图上传
- AI 面板 + 章节大纲不变
- 顶栏加「进入审查模式」入口

### 7.3 ONLYOFFICE 审查视图

- 全屏 ONLYOFFICE iframe（Word 风格 + 标尺 + 分页 + 批注侧栏）
- 顶栏：项目标题 + 「执行 AI 审查」按钮 + 「导出 Word/PDF」按钮 + 「返回撰写」按钮 + 协作者管理入口
- ONLYOFFICE 原生批注侧栏（右侧）

### 7.4 分享链接页面

`/shared/{token}` → ONLYOFFICE 只读模式 + 批注权限。不显示 Tiptap 撰写视图，不显示其他项目。

---

## 8. 涉及文件

### 后端

| 文件 | 改动 |
|---|---|
| `services/onlyoffice_service.py`（新） | 配置生成 + JWT + 回调 + 文件管理 |
| `api/onlyoffice.py`（新）+ router | 编辑器配置端点 + 回调端点 |
| `services/export_service.py` | 增强 `_render_tiptap_to_docx`（确保审查转换完整） |
| `parsing/docx_parser.py` | 增强：docx → Tiptap JSON 逆向转换（复用现有解析 + 节点构造） |
| `services/review_service.py` | 文本提取改为从 docx 读；审查结果注入 ONLYOFFICE 批注 |
| `models/project_member.py`（新）+ 迁移 | 协作者实体 |
| `models/share_link.py`（新）+ 迁移 | 分享链接实体 |
| `services/share_service.py`（新） | 协作者 + 分享链接 + token 鉴权 |
| `api/share.py`（新）+ router | 分享/协作者 API |
| `deps.py` | `get_shared_project`（token 鉴权） |
| `core/config.py` | onlyoffice_url / onlyoffice_jwt_secret |
| `docker-compose.yml` | ONLYOFFICE Document Server 服务 |

### 前端

| 文件 | 改动 |
|---|---|
| `app/(app)/projects/[id]/review-doc/page.tsx`（新） | ONLYOFFICE iframe 审查视图 |
| `app/shared/[token]/page.tsx`（新） | 分享链接访客页面 |
| `components/onlyoffice-editor.tsx`（新） | DocsAPI.DocEditor 封装 |
| `components/share-dialog.tsx`（新） | 协作者管理 + 分享链接生成 |
| `app/(app)/projects/[id]/page.tsx` | 顶栏加「进入审查模式」按钮 |
| `lib/api.ts` | onlyoffice config + share API 方法 |
| `package.json` | 无需新 Tiptap 扩展（Office 样式由 ONLYOFFICE 承担） |

### 删除/废弃

| 文件 | 处理 |
|---|---|
| `editor/office-toolbar.tsx` | 不需要（原计划的 Tiptap Office 工具栏取消） |
| `editor/ruler.tsx` | 不需要（ONLYOFFICE 原生标尺） |
| `editor/a4-page.tsx` | 不需要（ONLYOFFICE 原生 A4） |
| `editor/comment-mark.ts` | 不需要（ONLYOFFICE 原生批注） |
| `components/annotation-sidebar.tsx` | 不需要（ONLYOFFICE 原生批注侧栏） |

---

## 9. 数据流

### 9.1 撰写 → 审查

```
owner 在 Tiptap 编辑器撰写完成
  → 点「进入审查模式」
  → POST /projects/{id}/review-doc/enter
  → 后端: 遍历章节 → _render_tiptap_to_docx → 存 review/{project_id}/{ts}.docx
  → 返回 ONLYOFFICE 配置（文件 URL + callbackUrl + JWT）
  → 前端跳转 /projects/{id}/review-doc → 加载 ONLYOFFICE iframe
```

### 9.2 AI 审查

```
owner 在审查视图点「执行 AI 审查」
  → POST /projects/{id}/review
  → 后端: 从 docx 提取文本 → Rubric 评分 + 一致性检查 + 分级
  → 审查结果注入 docx 批注层（OOXML w:comments）
  → 重新加载 ONLYOFFICE 文档
  → 批注显示在 ONLYOFFICE 侧栏（AI 批注 + 代理人批注）
```

### 9.3 接受/拒绝修订

```
owner 在 ONLYOFFICE 内逐条接受/拒绝修订（原生 UI）
  → owner 点「保存」→ ONLYOFFICE callback → POST /onlyoffice/callback
  → 后端: 下载更新后 docx → 逆向转换 docx → Tiptap JSON → 存回 Section.content
  → 返回 {"error": 0}
```

### 9.4 代理人协作

```
owner 添加代理人（邮箱）或生成分享链接
  → 代理人登录/打开链接 → 进入 /projects/{id}/review-doc 或 /shared/{token}
  → ONLYOFFICE 只读模式 + 批注权限
  → 代理人添加批注/建议修改 → ONLYOFFICE 保存 → 回调
  → owner 看到新批注 → 接受/拒绝
```

### 9.5 导出

```
owner 在审查视图点「导出 Word」或「导出 PDF」
  → ONLYOFFICE 原生导出（格式保真）
  → 直接下载
```

---

## 10. 取舍

- **两套编辑器**：Tiptap（撰写）+ ONLYOFFICE（审查），体验有切换感。但各司其职，每套在其场景下都是最优。
- **Tiptap↔docx 转换有损**：简单格式无损，复杂格式降级。专利交底书 99% 是简单格式，可接受。
- **AGPL 许可证**：小团队内部使用不触发；商业化需购买商业许可。部署时 ONLYOFFICE 不公开网络入口。
- **AI 审查批注注入**：通过写 OOXML 批注层实现（不是 ONLYOFFICE 实时 API），需要重新加载文档才能看到 AI 批注。可接受（审查不是实时交互）。
- **不做 Tiptap Office 样式**：原计划的工具栏/标尺/A4/分页全部取消——Office 体验完全由 ONLYOFFICE 承担，避免重复造轮子。
- **旧 /review 页保留**：作为历史审查记录的只读查看（ReviewRecord 列表），新的批注式审查在 /review-doc 页面。
- **实时协作**：ONLYOFFICE 原生支持多人同时编辑——这是额外收益，原设计没敢做。

---

## 11. 非目标

- Tiptap 编辑器的 Office 样式改造（工具栏/标尺/A4/分页）——由 ONLYOFFICE 承担
- 自建批注系统（CommentMark/Decoration/annotation-sidebar）——由 ONLYOFFICE 承担
- Tiptap Pro 付费扩展
- docx 复杂格式的无损逆向转换（表格/文本框/分栏降级为纯文本）
- 审查批注转回 Tiptap JSON（批注留在 docx，不进 Section.content）
- 手动在 Tiptap 撰写阶段添加批注（批注只在 ONLYOFFICE 审查阶段）
