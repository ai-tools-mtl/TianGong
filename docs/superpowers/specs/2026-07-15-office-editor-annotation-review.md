# 天工 TianGong — 混合编辑器架构：Tiptap 撰写 + Collabora 审查/批注/导出

> 日期：2026-07-15（修订：最终方案，引擎从 ONLYOFFICE 改为 Collabora Online）
> 目标：AI 撰写保留 Tiptap 流式体验，审查/协作批注/导出引入 Collabora Online 获得产品级批注、修订模式（接受/拒绝）、Word/PDF 保真导出。
> 关联：[MVP 设计文档](./2026-07-13-tiangong-mvp-design.md) P1 增强扩展。

---

## 1. 背景与决策

### 1.1 问题

P0 完成后两个瓶颈：
1. 审查结果与编辑脱节——独立 /review 页，无法定位、无法一键应用建议
2. 编辑器体验粗糙——无 Office 风格、无批注、无协作

### 1.2 方案选择过程

调研了四条路：

| 方案 | 批注/修订 | Office 视觉 | AI 流式 | 导出保真 | 兼容现有代码 | 许可证 |
|---|---|---|---|---|---|---|
| 纯 Tiptap 自建 | 🔴 anchor 定位硬伤 | 🔴 CSS 分页冲突 | ✅ | 🔴 需手动扩展 | ✅ | ✅ MIT |
| 全量迁移 Office 引擎 | ✅ 开箱即用 | ✅ 真引擎 | ❌ 流式断裂 | ✅ 原生 | 🔴 数据层重写 | ⚠️ 见下 |
| **混合方案** | ✅ 引擎原生 | ✅ 引擎原生 | ✅ Tiptap 保留 | ✅ 原生 | 🟡 需转换层 | 见下 |
| Markdown 类（HedgeDoc） | ✅ 评论 | ❌ 非 Office | ✅ | ❌ 无 docx | 🟡 | AGPL |

混合方案的核心：**AI 撰写阶段用 Tiptap（保流式），审查/协作/导出阶段转 docx 用 Office 引擎**。

### 1.3 为什么选 Collabora Online 而非 ONLYOFFICE

两个引擎都能满足需求（docx 批注 + 修订 + 导出保真），关键差异在许可证：

| 维度 | Collabora Online | ONLYOFFICE |
|---|---|---|
| 许可证 | **MPL 2.0** ✅ | AGPL v.3 ⚠️ |
| 网络 copyleft | **无**（MPL 是文件级，不触发） | **有**（SaaS 使用要求整个后端开源） |
| 商业化风险 | **无** | 需购买商业许可 |
| 底座 | LibreOffice (LOKit) | 自研 JS 引擎 |
| 集成协议 | WOPI（开放标准） | JS API + callback |
| UI 可定制性 | ✅ CSS 主题 + 工具栏配置 + embedded 模式 | 🟡 较封闭 |
| 性能 | 🟡 服务端 tile 渲染，稍慢 | ✅ 客户端渲染，快 |
| docx 保真 | ✅ 好（LibreOffice 引擎） | ✅ 略优（默认格式即 docx） |

**选 Collabora 的三个理由**：
1. **MPL 许可证无商业风险**——天工是私有项目，未来可能商业化。AGPL 的网络 copyleft 是地雷，MPL 完全没有这个问题。
2. **UI 可渐进打磨**——Collabora 支持 CSS 主题定制、工具栏配置、embedded 嵌入模式。可以先用默认 UI 跑起来，再逐步定制到天工风格。ONLYOFFICE 的 JS 混淆，定制能力弱。
3. **WOPI 是开放标准**——微软定义的 Web Application Open Platform Interface，文档完善，有 [Mattermost 插件](https://github.com/CollaboraOnline/collabora-mattermost)、[Symfony bundle](https://www.youtube.com/watch?v=6FA7kdGi2rs) 等参考实现。不绑定特定厂商生态。

性能差异（Collabora 稍慢）对专利交底书这种中小型文档可接受，且可通过调 tile 大小、预渲染等手段逐步优化。

---

## 2. 双阶段架构

```
┌─ 阶段一：AI 撰写（Tiptap）──────────────────────────┐
│                                                       │
│  Tiptap 编辑器（现有，保持简洁）                       │
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
┌─ 阶段二：审查/协作/导出（Collabora Online）───────────┐
│                                                       │
│  Collabora Online Editor（iframe 嵌入）                │
│  ├─ Word 风格编辑 + 标尺 + 真分页（LibreOffice 引擎）   │
│  ├─ 批注（代理人/AI 添加，OOXML 精确锚定）              │
│  ├─ 修订模式（建议修改 → owner 接受/拒绝）              │
│  ├─ 协作（注册用户 + 分享链接访客）                     │
│  ├─ 导出 Word/PDF（LibreOffice 原生保真）              │
│  └─ WOPI 保存回调 → 后端接收 docx                      │
│                                                       │
│  owner 接受修订 → Collabora 保存 docx                   │
│  → 后端: docx → 转回 Tiptap JSON → 存回 Section.content│
│  → 回到阶段一继续 AI 撰写                              │
└───────────────────────────────────────────────────────┘
```

### 2.1 解决的盲点

| 盲点 | 解决方式 |
|---|---|
| ① anchor_text 定位失败 | ✅ Collabora 批注锚定在 OOXML 位置，精确到字符 |
| ② CSS column 分页冲突 | ✅ LibreOffice 真 Word 分页引擎 |
| ③ 导出渲染器不支持新格式 | ✅ Collabora 原生导出 docx/pdf，格式保真 |
| ④ 批注不污染原文 | ✅ 批注/修订是 OOXML 独立层，与正文分离 |
| ⑤ 接受批注的乐观锁冲突 | ✅ Collabora 内部管理修订状态，WOPI 保存串行化 |
| ⑥ 重新审查旧批注处理 | ✅ Collabora 批注有 resolved 状态，旧批注保留 |
| ⑦ 标尺与导出不一致 | ✅ 标尺即真实页边距，导出一致 |
| ⑧ 代理人"实时"非实时 | ✅ Collabora 原生支持实时协作 |

---

## 3. Tiptap → docx 转换层

混合方案的关键接点。复用并增强现有 `export_service.py` 的 `_render_tiptap_to_docx`。

### 3.1 正向转换：Tiptap JSON → docx（进入审查模式）

现有 `_render_tiptap_to_docx` 支持 paragraph/heading/list/image。需确保覆盖 Tiptap 的所有节点类型。转换流程：

```
用户点「进入审查模式」
  → 后端: 遍历项目所有章节 → _render_tiptap_to_docx 拼成完整 docx
  → 存到文件系统（uploads/review/{project_id}/{version}.docx）
  → 返回 WOPI src URL
  → 前端: 加载 Collabora iframe（传 WOPI src + access_token）
```

### 3.2 逆向转换：docx → Tiptap JSON（审查后回写）

有损转换——复杂格式（嵌套表格、文本框、艺术字）无法 1:1 转回 Tiptap JSON。但专利交底书以段落+标题+列表+图片为主，这些能完整表达。

逆向转换复用现有 `parsing/docx_parser.py`（模板解析已建好的 Word 解析器）：
```
Collabora WOPI 保存 → 后端收到 docx
  → docx_parser.parse_docx → 提取结构（章节/段落/标题/列表/图片）
  → 转为 Tiptap JSON（复用 markdown_to_tiptap 的节点构造逻辑）
  → 存回各 Section.content
```

### 3.3 转换损耗取舍

- **简单格式（段落/标题/列表/图片/加粗/斜体）**：双向无损
- **复杂格式（表格/文本框/分栏）**：正向可生成，逆向降级为纯文本
- **批注/修订**：不转回 Tiptap JSON——留在 docx 审查版本里，Tiptap JSON 只存正文

专利交底书 99% 是简单格式，损耗可接受。

---

## 4. Collabora Online 集成（WOPI 协议）

### 4.1 WOPI 协议概述

WOPI（Web Application Open Platform Interface）是微软定义的开放标准：
- **WOPI Host**（天工 FastAPI 后端）：管理文件存储、权限、提供文件读写端点
- **WOPI Client**（Collabora Online）：编辑器，通过 WOPI 协议从 Host 获取文件、保存回文件

### 4.2 部署

docker-compose 增加 Collabora Online 服务：

```yaml
collabora:
  image: collabora/code:latest
  environment:
    - aliasgroup1=https://collabora.example.com:9980
    - extra_params=--o:ssl.enable=false --o:ssl.termination=true
    # 允许的 WOPI host（天工后端域名）
    - aliasgroup1_host=https://tiangong.example.com
  ports:
    - "9980:9980"
  cap_add:
    - MKNOD
  volumes:
    - collabora_data:/data
```

Collabora 通过 `aliasgroup` 配置允许哪些 WOPI host 连接——这是访问控制的第一层。

### 4.3 后端 WOPI Host 实现

FastAPI 实现 WOPI 协议端点：

| WOPI 端点 | 方法 | 说明 |
|---|---|---|
| `/wopi/files/{file_id}` | GET | 获取文件元信息（size、name、version） |
| `/wopi/files/{file_id}/contents` | GET | 下载文件内容（docx 二进制） |
| `/wopi/files/{file_id}/contents` | POST | 保存文件内容（Collabora 编辑后回传） |
| `/wopi/files/{file_id}` | POST | 文件操作（锁/解锁/版本管理） |

**鉴权**：每个 WOPI 请求带 `access_token`（JWT），FastAPI 验证 token 后确认用户对文件的权限。

**关键文件**（新建）：
- `apps/api/app/services/collabora_service.py` — WOPI token 生成 + 文件管理 + 转换触发
- `apps/api/app/api/wopi.py`（新）+ router — WOPI 协议端点
- `apps/api/app/core/config.py` — 加 `collabora_url`、`collabora_wopi_domain`

### 4.4 前端加载 Collabora

```typescript
// 前端通过 Collabora 的 JS API 加载编辑器
const src = `${COLLABORA_URL}/browser/dist/cool.html?WOPISrc=${encodeURIComponent(wopiSrc)}&access_token=${token}`
// iframe 嵌入
<iframe src={src} allow="clipboard-read; clipboard-write" />
```

### 4.5 文件存储

审查阶段的 docx 存文件系统（复用 Plan 10 的 upload_dir 配置）：
- 路径：`uploads/review/{project_id}/{timestamp}.docx`
- 每次进入审查模式生成新版本（不覆盖旧的）
- Collabora 通过 WOPI `/contents` 端点读写

---

## 5. 审查引擎增强

### 5.1 一致性检查 + 问题定位

模块①逻辑不变——单次 LLM 一致性检查 + 问题分级。输出方式变化：

- AI 审查结果 → 写入 docx 的 OOXML 批注层（`w:comments`）→ 重新加载 Collabora 文档
- 或通过 Collabora 的 postMessage API 注入批注（如果支持）

### 5.2 审查流程

```
owner 在 Collabora 审查视图点「执行 AI 审查」
  → POST /projects/{id}/review
  → 后端: 从 docx 提取文本（python-docx 读段落）
  → Rubric 评分 + 一致性检查 + 问题分级
  → 审查结果写入 docx 批注层（OOXML w:comments）
  → Collabora 重新加载文档 → 批注显示在侧栏
  → owner 逐条接受/拒绝修订（Collabora 原生 UI）
  → 保存 → WOPI 回调 → 逆向转 Tiptap JSON
```

---

## 6. 协作批注

### 6.1 权限模型

| 角色 | 阶段一（Tiptap 撰写） | 阶段二（Collabora 审查） |
|---|---|---|
| owner | ✅ 全部 | ✅ 全部（编辑 + 接受/拒绝修订 + 管理批注） |
| reviewer（注册代理人） | ❌ 不可见 | ✅ 只读 + 批注 + 建议修改（修订模式） |
| guest（分享链接访客） | ❌ 不可见 | ✅ 只读 + 批注 |

### 6.2 协作者管理

新增 `ProjectMember` 实体：`project_id` + `user_id` + `role`（reviewer）。owner 通过邮箱添加代理人。

新增 `ShareLink` 实体：`project_id` + `token`（UUID）+ `expires_at` + `permissions`（read/comment）。owner 生成链接，访客通过 `/shared/{token}` 进入 Collabora 只读+批注模式。

### 6.3 批注不污染原文

Collabora 的批注和修订是 OOXML 独立层（`w:comments` / `w:ins` / `w:del`），与正文（`w:body`）分离。逆向转 Tiptap JSON 时**只提取正文**，批注/修订留在 docx 审查版本里。天然实现"批注不污染原始版本"。

### 6.4 Collabora UI 渐进定制

- **初始阶段**：用 Collabora 默认 UI（功能完整，视觉偏 LibreOffice 风格）
- **后续打磨**：
  - CSS 主题覆盖（配色与天工统一）
  - 工具栏配置（隐藏不需要的按钮，只留专利相关功能）
  - embedded 模式（隐藏 Collabora 顶栏，用天工自己的顶栏包裹）
  - 性能调优（tile 大小、预渲染范围）

---

## 7. 前端架构

### 7.1 两套编辑器视图

| 视图 | 路由 | 编辑器 | 用途 |
|---|---|---|---|
| 撰写视图 | `/projects/{id}` | Tiptap（现有，保持） | AI 流式生成 + 富文本编辑 |
| 审查视图 | `/projects/{id}/review-doc` | Collabora iframe | 批注 + 修订 + 协作 + 导出 |

切换：撰写页顶栏「进入审查模式」→ 后端转换 → 跳审查视图。审查页顶栏「返回撰写」→ 后端逆向转换 → 跳回撰写视图。

### 7.2 Tiptap 撰写视图

保持现有 Tiptap 编辑器，**不做 Office 样式改造**（Office 体验由 Collabora 承担）。保持 Plan 9 防抖保存 + Plan 10 附图上传 + AI 面板。顶栏加「进入审查模式」入口。

### 7.3 Collabora 审查视图

- 全屏 Collabora iframe（Word 风格 + 标尺 + 分页 + 批注侧栏）
- 顶栏：项目标题 + 「执行 AI 审查」+ 「导出 Word/PDF」+ 「返回撰写」+ 协作者管理
- Collabora 原生批注侧栏（右侧）

### 7.4 分享链接页面

`/shared/{token}` → Collabora 只读模式 + 批注权限。

---

## 8. 涉及文件

### 后端

| 文件 | 改动 |
|---|---|
| `services/collabora_service.py`（新） | WOPI token 生成 + 文件管理 + 转换触发 |
| `api/wopi.py`（新）+ router | WOPI 协议端点（files/contents/operations） |
| `services/export_service.py` | 确保 `_render_tiptap_to_docx` 覆盖所有节点 |
| `parsing/docx_parser.py` | 增强：docx → Tiptap JSON 逆向转换 |
| `services/review_service.py` | 文本提取改从 docx 读；审查结果写入 OOXML 批注层 |
| `models/project_member.py`（新）+ 迁移 | 协作者实体 |
| `models/share_link.py`（新）+ 迁移 | 分享链接实体 |
| `services/share_service.py`（新） | 协作者 + 分享链接 + token 鉴权 |
| `api/share.py`（新）+ router | 分享/协作者 API |
| `deps.py` | `get_shared_project`（token 鉴权） |
| `core/config.py` | collabora_url / collabora_wopi_domain |
| `docker-compose.yml` | Collabora Online 服务 |

### 前端

| 文件 | 改动 |
|---|---|
| `app/(app)/projects/[id]/review-doc/page.tsx`（新） | Collabora iframe 审查视图 |
| `app/shared/[token]/page.tsx`（新） | 分享链接访客页面 |
| `components/collabora-editor.tsx`（新） | Collabora iframe 封装 |
| `components/share-dialog.tsx`（新） | 协作者管理 + 分享链接生成 |
| `app/(app)/projects/[id]/page.tsx` | 顶栏加「进入审查模式」按钮 |
| `lib/api.ts` | collabora/share API 方法 |

### 不再需要（相比纯 Tiptap 自建方案）

| 文件 | 原因 |
|---|---|
| `editor/office-toolbar.tsx` | Collabora 原生工具栏 |
| `editor/ruler.tsx` | Collabora 原生标尺 |
| `editor/a4-page.tsx` | Collabora 原生 A4 分页 |
| `editor/comment-mark.ts` | Collabora 原生批注 |
| `components/annotation-sidebar.tsx` | Collabora 原生批注侧栏 |

---

## 9. 数据流

### 9.1 撰写 → 审查

```
owner 在 Tiptap 撰写完成 → 点「进入审查模式」
  → POST /projects/{id}/review-doc/enter
  → 后端: 章节遍历 → _render_tiptap_to_docx → 存 review/{project_id}/{ts}.docx
  → 生成 WOPI access_token（JWT，含 file_id + user_id + permissions）
  → 返回 WOPISrc URL + token
  → 前端跳转 /projects/{id}/review-doc → 加载 Collabora iframe
```

### 9.2 Collabora 读写文件（WOPI）

```
Collabora iframe 加载 → 向 /wopi/files/{file_id} GET 元信息
  → 向 /wopi/files/{file_id}/contents GET 下载 docx
  → 用户编辑（批注/修订）
  → 保存 → POST /wopi/files/{file_id}/contents（docx 二进制）
  → FastAPI 接收 docx → 存文件
```

### 9.3 AI 审查

```
owner 点「执行 AI 审查」
  → POST /projects/{id}/review
  → 后端: 从 docx 提取文本 → Rubric 评分 + 一致性检查 + 分级
  → 审查结果写入 docx OOXML 批注层（w:comments）
  → Collabora 重新加载文档 → 批注显示在侧栏
```

### 9.4 返回撰写

```
owner 点「返回撰写」
  → POST /projects/{id}/review-doc/exit
  → 后端: 读取最新 docx → 逆向转换 docx → Tiptap JSON → 存回 Section.content
  → 前端跳回 /projects/{id}（Tiptap 编辑器加载最新内容）
```

### 9.5 导出

```
owner 点「导出 Word/PDF」
  → Collabora 原生导出（LibreOffice 引擎保真）
  → 直接下载
```

### 9.6 代理人协作

```
owner 添加代理人（邮箱）或生成分享链接
  → 代理人登录/打开链接 → /projects/{id}/review-doc 或 /shared/{token}
  → Collabora 只读模式 + 批注权限（WOPI token 限定 permissions）
  → 代理人添加批注/建议修改 → Collabora 保存 → WOPI 回调
  → owner 看到新批注 → 接受/拒绝
```

---

## 10. 取舍

- **两套编辑器**：Tiptap（撰写）+ Collabora（审查），各司其职。切换有转换开销。
- **Tiptap↔docx 转换有损**：简单格式无损，复杂格式降级。专利交底书 99% 简单格式。
- **MPL 许可证无风险**：Collabora MPL 2.0，不触发网络 copyleft，可闭源商业化。
- **性能渐进优化**：Collabora 默认稍慢，可通过 tile 配置/预渲染逐步优化。
- **UI 渐进定制**：先跑默认 UI，再逐步 CSS 主题/工具栏配置/embedded 模式打磨。
- **AI 审查批注注入**：通过写 OOXML 批注层实现，需重新加载文档。可接受（审查非实时交互）。
- **实时协作是额外收益**：Collabora 原生支持多人同时编辑，原设计没敢做。

---

## 11. 非目标

- Tiptap 编辑器的 Office 样式改造——由 Collabora 承担
- 自建批注系统（CommentMark/Decoration/annotation-sidebar）——由 Collabora 承担
- docx 复杂格式的无损逆向转换（表格/文本框/分栏降级为纯文本）
- 审查批注转回 Tiptap JSON（批注留在 docx，不进 Section.content）
- 手动在 Tiptap 撰写阶段添加批注（批注只在 Collabora 审查阶段）
- Collabora 深度 UI 定制（MVP 用默认 UI，后续迭代打磨）
