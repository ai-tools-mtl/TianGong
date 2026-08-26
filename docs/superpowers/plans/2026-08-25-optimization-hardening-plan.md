# 优化加固计划（内测前批次安排）

> 日期：2026-08-25。前置状态：设计文档计划项全部落地（README 开发进度）；两条架构边界
> （审查互斥 DB 锁 `8fb17ef`、附图引用完整性 `1cbf186`）已闭环，全量 1326 测试绿。
>
> **执行状态（2026-08-26）**：批次 1-6 已全部完成并原子提交——
> 批次 1 CI `ba981ce` / 批次 2 用量+余额告警 `4507f07` / 批次 3 备份演练 `1797e62` /
> 批次 4 E2E `95f38ab` / 批次 5 eval 基线 `bc4f935` / 批次 6 图号 V1 `4405674`。
> 实施偏差两处已就地记录：批次 4 用 Playwright page.route 替代 MSW（零侵入）；
> 批次 6 附图清单为前端编辑器插入而非服务端写内容（挂载中编辑器不回读服务端落库内容）。
> 批次 0（T2 dogfood 走查）留给用户人工执行。
>
> 本计划不新增产品功能主线，聚焦三类：**回归保障（安全网）→ 内测运营保障 → 质量纵深**。
> 排序原则：先人工抽检（可能产生新修复需求）、再安全网（保护后续开发）、再运营缺口、
> 最后纵深项。总量约 5-6 个工作日，批次间无硬依赖，可按内测节奏截断。

## 批次总览

| 批次 | 内容 | 预估 | 类型 |
|---|---|---|---|
| 0 | T2 修订管线 dogfood 抽检 | 0.5 天 | 人工走查 |
| 1 | CI（GitHub Actions） | 0.5 天 | 工程 |
| 2 | LLM 用量补差 + 余额告警 | 1-1.5 天 | 运营功能 |
| 3 | 备份恢复演练 + 定时化 | 0.5 天 | 运维 |
| 4 | 前端 E2E 冒烟（Playwright + MSW） | 1-1.5 天 | 工程 |
| 5 | 审查评分回归基线（eval 扩展） | 1 天 | 质量纵深 |
| 6 | 图号系统 V1（自动编号 + 删除连锁明示） | 1 天 | 产品纵深 |

---

## 批次 0：T2 修订管线 dogfood 抽检（先做，可能改写后续优先级）

**为什么先做**：T2 是「建议 → 确认卡片 → revise SSE → diff → apply」的核心闭环，
2026-08-17 合并后一直没有真人走查（记忆明确记着待做）。若抽检暴露问题，会产生新的
高优先修复项，应在其后排其他开发。

**走查清单**（每项记录：通过 / 问题截图 / 严重度）：
1. 审查报告 → 勾选建议 → 一键修订 → diff 审核通过后正文落点正确
2. 术语检查建议 → 同上（术语表优先级是否生效：术语表 > 沿用现状 > 最小改动）
3. 新颖性评估建议 → 同上
4. 跨页传递：`revision-store` 单值覆盖 + `?section=` 深链读后清参
5. 边界：不勾选任何建议直接发起；revise 中途断开（SSE 错误提示）
6. 连续文档视图模式下走一遍（激活章唯一可编辑与修订落点的交互）

**产出**：问题清单。无问题则关闭该记忆项；有问题按严重度插入本计划批次之间。

---

## 批次 1：CI（GitHub Actions）

**现状**：无 `.github/workflows/`，1326 个后端测试 + tsc 全靠手跑。

**范围**：单 workflow 两 job，PR 与 main push 触发。

### Job 1 后端（ubuntu-latest）
- service container：`pgvector/pgvector:pg16`（**不是**普通 postgres 镜像——迁移内
  `CREATE EXTENSION vector`，且普通镜像装不了扩展）。env `DATABASE_URL` 指向它。
  **必须起 postgres 的原因**（本地踩过）：startup 的 `await init_checkpointer(...)`
  在 postgres 不可达时会**挂起**（不是快速失败），`TIANGONG_TESTING=1` 只跳过预检
  不跳过 checkpointer——CI 不给 postgres 会整场卡死超时。
- 步骤：checkout → astral-sh/setup-uv（带 cache）→ `uv sync --extra dev` →
  `uv run pytest -q`（conftest 自设 TIANGONG_TESTING）。
- 不需要 minio（conftest 永久注入 `_FakeStorage` 单例）、不需要 nli/drawio/embedding
  （软依赖，测试全 mock）。

### Job 2 前端（ubuntu-latest）
- pnpm/action-setup + cache → `pnpm install` → `pnpm exec tsc --noEmit` → `pnpm build`。
- build 需 `NEXT_PUBLIC_API_URL`（build 期内联），给占位值 `http://localhost:8000` 即可。

**验收**：main 上一次绿跑；故意 push 一个失败测试验证会红（然后 revert）。

---

## 批次 2：LLM 用量补差 + 余额告警

**现状核实**（避免重做）：`stats_service.get_llm_stats` 已有——整段汇总（calls/
成功率/均时/prompt+completion tokens）、`by_model`（含 token）、`by_user`（**无 token
列**）；`get_llm_health` 已有失败率 ok/warning（阈值 5%）；前端 `/admin/console/stats`
已有明细页；recharts 2.15 已在依赖里。

**真实缺口三个**：① 按天时间序列（现聚合是整段汇总，看不出趋势）；② by_user 缺
token 数（内测期「谁在烧钱」定位不了）；③ 余额告警（DeepSeek 全局 key 欠费 = 未自配
用户集体不可用，且无任何预警）。

### 2a. 按天聚合 + per-user token
- `get_llm_stats` 加 `by_day: [{date, calls, failed, prompt_tokens, completion_tokens}]`；
  `by_user` 各行补 `prompt_tokens/completion_tokens`。
- 设计决策 D1：按天分组用 `func.date(LLMCallLog.created_at)`——SQLite 与 PG 均有
  `date()` 函数，避免 `date_trunc` 的 PG 专有性（G2 双方言约束）。写单测时两边语义
  各验证一次（SQLite 内存库跑真分组）。
- 前端 stats 页加 recharts 折线（近 N 天 token/调用双序列）+ by_user 表补 token 列。

### 2b. 余额告警
- 新 `app/services/llm_balance_service.py`：
  - `probe_balance(db)` → 读全局 chat 配置；provider 为 `deepseek` 时 GET
    `{base_url}/user/balance`（DeepSeek 专有端点，**需先 curl 验证响应结构**——
    计划假设返回 `{balance_infos: [...]}`，若不符以实测为准）；其他 provider 返回
    `{supported: False}`（OpenAI 系无公开余额端点，不硬造）。
  - 结果写 `SystemSetting llm_balance_status`（金额、货币、探测时间、supported、
    error）；读取端点供前端轮询。
- 阈值可配：`SystemSetting llm_balance_threshold`（默认 ¥10），admin console「LLM
  配置」页加输入框 + 「立即探测」按钮（手动触发起步）。
- 告警呈现：console 布局层（admin 区域共用壳）读 `llm_balance_status`，低于阈值渲染
  顶部横幅（红），欠费/探测失败渲染黄色横幅带 error 摘要。
- **去范围**：邮件/webhook 推送渠道、后台自动轮询（asyncio 定时任务涉及
  TIANGONG_TESTING 守卫与生命周期管理，内测期 admin 手动探测够用；后续要自动化再
  加，且必须带测试环境跳过守卫——本地 docker 卡死教训）。
- 测试：probe 的 mock httpx 单测（deepseek 命中 / 非 deepseek supported=False / 超时
  降级 error 不抛）；阈值比较纯函数；端点 admin-only 鉴权（普通用户 403）。

---

## 批次 3：备份恢复演练 + 定时化

- `apps/api/scripts/backup.sh`：`pg_dump`（postgres 容器 exec）+ `mc mirror`
  miniodata 卷 → 本地/挂载盘带日期目录，保留最近 N 份（N 可配，默认 7）。
- `apps/api/scripts/restore.sh`：从指定备份目录恢复 pg + minio（幂等提示）。
- 定时化：部署宿主 cron（deploy-internal.md 是 Linux 宿主 + docker），每天 03:00。
- **演练（本批次的验收）**：在测试环境用 backup.sh 产出的备份 + restore.sh 恢复到
  空卷，起服务验证登录/项目/附件图完整。演练步骤与结论回写 deploy-internal.md。
- 注意：备份脚本含 DB 凭据引用但**不硬编码**（读 `.env.production` / 环境变量），
  脚本本身可提交。

---

## 批次 4：前端 E2E 冒烟（Playwright + MSW）

**现状**：前端零自动化测试；后端 1326 个。改 figure-generate/editor 这类组件只能手测。

**方案决策 D2：MSW（mock service worker）而非起真后端**。理由：CI 里拉起完整后端
+ postgres + seed 数据成本高且脆（SSE mock 尤其麻烦）；冒烟目标是「改前端别把流程
改断」，契约正确性已由后端测试兜住。代价：后端契约变更 MSW 不会自动红——可接受，
写进计划的已知限制。

**范围**（一条主链路 + 关键交互）：
1. 登录 → 项目列表 → 新建项目 → 进编辑器
2. 编辑器输入文字 + 保存（mock sections PUT）
3. 审查页触发审查（mock SSE 流）→ 报告渲染
4. 导出按钮可达
5. 图集面板：figure-generate 渲染 + 删除二次确认流（409 → force，正好回归本次
   `1cbf186` 的前端行为）
6. 登出 → 未登录路由守卫跳转

**结构**：`apps/web/e2e/`，Playwright config + `pnpm e2e` script；MSW handler 集中
一处（`e2e/mocks/handlers.ts`）便于契约变更时单点维护。CI（批次 1 的 workflow）加
第三 job 或并入前端 job（playwright 官方 action 装浏览器，带 cache）。

**验收**：CI 绿；人为改坏一个路由能红。

---

## 批次 5：审查评分回归基线（eval 扩展）

**现状**：`app/eval/`（P2）只有 judge 区分度验证（`runner.py`：样本 × judge 看
good/bad 分差 ≥ 20），验证的是「指标有效」，不能防「改 prompt/rubric 后评分漂移」。

**范围**：
- `app/eval/review_baseline.py`：对固定样本集（2-3 篇标准交底书文本，`samples.py`
  扩充）跑**真实 review 评分管线**（复用 `run_review` 的 score 阶段，不落库），输出
  每维度分数与基线对比。
- 基线文件 `app/eval/baselines/review_baseline.json`（首跑生成，人工确认后提交）；
  偏差超阈值（默认每维度 ±15 分）输出告警行，exit code 非零。
- 触发：手动 `python -m app.eval.review_baseline`（调真 LLM 有成本，**不进 CI**）。
- 使用场景：改 rubric prompt / 换模型 / 调自一致性参数后跑一次，确认评分体系没漂。

**面试叙事价值**：补齐「怎么验证 AI 应用质量」的完整答案（judge 区分度 + 评分回归
基线 + 1326 单测三层）。

---

## 批次 6：图号系统 V1（自动编号 + 删除连锁明示）

**背景**：专利文档惯例是「图1/图2…编号 + 正文『如图1所示』引用」。当前插图没有编号
概念，用户手写图号，增删图后编号与正文引用全部漂移。08-25 的引用防护（`1cbf186`）
恰好是它的地基：`find_body_references` 已能权威回答「哪些章节引用了此图」，delete
已有 409+force 确认流，regenerate 原地覆写天然不动编号。

**V1 范围（~1 天，核心原则：编号自动管、正文自由文本不自动改写）**：
- `Figure` 加 `number` 列（迁移 + 存量按 `created_at` 顺序回填）：项目内连续编号，
  生成时分配；删除（force）后同一事务内对后续图重排前移，保证编号无空洞
  （《专利审查指南》要求图按顺序编号）。
- 插入正文自动带「图N」图注：前端 `onInsertImage` 时图片附随编号标注（alt 或
  图注段落）；图集缩略图显示编号徽标。
- 附图说明清单**按钮化**而非自动维护（设计决策 D3：不在用户可编辑内容里做隐式
  自动写入——用户手改过的段落被系统覆盖是最差体验）：图集面板提供「生成附图说明
  清单」按钮，按当前编号一键在 drawings 章节插入「图N：{描述}」清单段落，用户
  可随后自由编辑，重复点击替换上次生成的清单块（用可识别标记定位）。
- 删除确认流升级：现有 409/确认文案基础上明示「删除图N后，后续图号前移，正文中
  的『图K』文字引用需手动核对」——诚实告知，不做危险的自动改写。
- API：`Figure` 出参加 `number`；编号重排是服务端行为，前端无感。

**明确留待内测反馈（不在本批）**：
- V2：插图时在 img 节点埋 figure_id 机器标记（attrs），重排时精确联动正文图注
  （+1 天，中风险——涉及编辑器 schema）。
- V3：重排后正文「图N」引用修正建议走 T2 修订管线（AI 定位 + diff + 人工确认，
  +1 天）——复用已验证的人工审核闭环，不自动应用。

**测试**：编号分配/删除重排（含连续删除幂等、编号无空洞断言）service 单测；409
文案含图号与连锁提示；「附图说明清单」生成/重复生成替换逻辑单测；API 出参契约测试。

---

## 明确去范围（本计划不做）

| 项 | 原因 |
|---|---|
| 交底书→专利申请文件转换 | 行业价值大但工作量重，等内测用户反馈驱动 |
| 图号系统 V2/V3（img 机器标记联动 / T2 引用修正建议） | V1 已入批次 6；V2/V3 等内测反馈（见批次 6 末） |
| 余额告警的邮件/webhook 渠道与后台轮询 | 内测期手动探测 + 横幅够用，自动化涉及后台任务生命周期 |
| 多人协作编辑 | 架构级投入，非内测目标 |
| org_admin/org_id 平台化 | 08-11 已主动去范围，保留预留即可 |

## 批内注意事项（跨批次通用）

- **所有新增后台/启动期网络调用必须带 `TIANGONG_TESTING` 跳过守卫**（E 坑：本地
  docker 未起时 startup 网络等待会卡死整个测试套）。
- 测试沿用 SQLite 内存库 + `JSONB().with_variant(JSON, "sqlite")` 双方言约束（G2），
  SQL 聚合函数选型先查双方言支持（D1 的 `func.date` 已核）。
- 每批次独立成提交（原子规范），完成后更新 README「开发进度」与
  `docs/llm-usage.md`（批次 2 涉及新 LLM 相关调用点则同步）。
