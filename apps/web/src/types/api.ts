// 与后端 schemas 对齐

export interface User {
  id: string
  username: string
  email?: string | null
  name: string
  role: string
}

export interface Project {
  id: string
  title: string
  stage: string
  status: string
  progress_pct: number
  metadata: Record<string, unknown> | null
  archived_at: string | null
  tags: string[]
  created_at: string
  updated_at: string
}

export interface ProjectCreate {
  title: string
  template_id?: string | null
  metadata?: Record<string, unknown> | null
}

export interface ProjectUpdate {
  title?: string
  metadata?: Record<string, unknown> | null
}

export interface ApiError {
  code: string
  message: string
}

export interface RegisterRequest {
  username: string
  email?: string
  password: string
  name: string
  // 内部产品化:凭邀请码注册
  invite_code: string
}

export interface LoginRequest {
  username: string
  password: string
}

// ── 邀请码(内部产品化)──

export interface InviteCode {
  id: string
  code: string
  max_uses: number
  used_count: number
  status: 'active' | 'exhausted' | 'revoked' | 'expired'
  expires_at: string | null
  revoked_at: string | null
  created_by_id: string | null
  created_at: string
}

export interface InviteCodeCreate {
  max_uses?: number
  expires_in_days?: number | null
}

export interface AdminCreateUserRequest {
  username: string
  email?: string
  password: string
  name: string
  role?: string
}

// ── 模板 ──

export interface TemplateSection {
  id: string
  order: number
  key: string
  title: string
  level: number
}

/** 模板状态机（refactor/admin-ia-phase3 切片 B）：draft/published/offline。 */
export type TemplateStatus = 'draft' | 'published' | 'offline'

export interface TemplateSummary {
  id: string
  name: string
  is_default: boolean
  is_system: boolean
  /** 模板状态（admin 上传默认 draft，普通用户视角只看到 published）。 */
  status: TemplateStatus
  section_count: number
}

export interface Template extends TemplateSummary {
  source_filename: string | null
  structure: TemplateSection[]
  styles: Record<string, unknown> | null
  numbering: Record<string, unknown> | null
  created_at: string
}

// ── 章节 ──

export interface Section {
  id: string
  project_id: string
  order: number
  key: string
  title: string
  content: Record<string, unknown> | null
  summary: string | null
  status: 'empty' | 'drafting' | 'confirmed'
  version: number
  created_at: string
  updated_at: string
}

// ── 版本 ──

export interface Version {
  id: string
  section_id: string
  content: Record<string, unknown> | null
  summary: string | null
  created_by: string
  note: string | null
  created_at: string
}

// ── 预览 ──

export interface PreviewSection {
  order: number
  key: string
  title: string
  content: Record<string, unknown> | null
  status: string
}

export interface ProjectPreview {
  title: string
  metadata: Record<string, unknown> | null
  sections: PreviewSection[]
}

// ── 审查 ──

export interface DimensionScore {
  key: string
  name: string
  weight: number
  score: number
  run_scores: number[]
  evidence: string
  suggestion: string
}

export interface ReviewRecord {
  id: string
  round: number
  total_score: number
  previous_score: number | null
  dimension_scores: DimensionScore[]
  resolved_issues: string[]
  remaining_issues: string[]
  created_at: string
}

export interface RubricCriterion {
  key: string
  name: string
  weight: number
  scoring_guide: Record<string, string>
}

export interface Rubric {
  id: string
  scope: string
  name: string
  criteria: RubricCriterion[]
  is_customized: boolean
}

// ── 附件 ──

export interface Attachment {
  id: string
  project_id: string
  section_id: string | null
  filename: string
  mime_type: string
  size: number
  created_at: string
}

// ── 管理 ──

export interface AdminUser {
  id: string
  username: string
  email?: string | null
  name: string
  role: string
  status: string
  project_count: number
  has_own_llm_key: boolean
  has_global_grant: boolean
  created_at: string
  // 后端 listUsers 补回（refactor/admin-ia-phase1），登录时由 auth_service 写入；可能为 null。
  last_login_at: string | null
}

/** GET /admin/users/{id} 返回。比 AdminUser 多 grant_detail（详情页授权区块用）。 */
export interface UserDetail extends AdminUser {
  /** 全局 Key 授权详情（granted_at/revoked_at/is_active）；无记录为 null。 */
  grant_detail: UserGrant | null
}

// ── 落地页聚合（refactor/admin-ia-phase1）──

/** GET /admin/users/recent-logins | /admin/users/recent-creations 列表项。 */
export interface RecentUser {
  id: string
  username: string
  email: string | null
  /** ISO 时间字符串：recent-logins 取 last_login_at，recent-creations 取 created_at。 */
  ts: string | null
}

/** GET /admin/stats/llm/health 返回；失败率超阈值时 status='warning'。 */
export interface LLMHealth {
  days: number
  total: number
  failed: number
  failure_rate: number
  status: 'ok' | 'warning'
}

/**
 * 全局 chat 单边配置的掩码回显形态。
 * GET /admin/llm-config 返回的 chat_config 子对象就是这个形状。
 * （embedding 已改走固定 bge-m3 微服务，不再有全局 embedding 配置。）
 */
export interface GlobalScopeConfig {
  base_url: string
  api_key_masked: string
  model: string
}

/**
 * GET /admin/llm-config 返回；admin 设置全局 LLM 配置。
 * 只管 chat（embedding 走固定 bge-m3 微服务，不可配）。
 */
export interface GlobalLLMSettings {
  llm_global_enabled: boolean
  chat_config: GlobalScopeConfig
}

// ── 全局 Key 授权（Task 2.2）──

/** GET /admin/users/{id}/global-llm-grant 返回；无记录时后端返回 {is_active: false}。 */
export interface UserGrant {
  granted_at: string | null
  revoked_at: string | null
  is_active: boolean
}

// ── 用户聚合统计（Task 3.1，仪表盘卡片）──

export interface UserStats {
  total: number
  active: number
  disabled: number
  new_7d: number
  new_30d: number
  granted_count: number
}

// ── LLM 调用统计（plan 13 + Task 0.5.2 token 用量）──

export interface LLMStatsByModel {
  model: string
  calls: number
  success: number
  failed: number
  avg_duration_ms: number | null
  prompt_tokens: number
  completion_tokens: number
}

export interface LLMStatsByUser {
  user_id: string | null
  email: string
  calls: number
  success: number
  failed: number
}

export interface LLMStats {
  days: number
  total_calls: number
  total_success: number
  total_failed: number
  avg_duration_ms: number | null
  total_prompt_tokens: number
  total_completion_tokens: number
  by_model: LLMStatsByModel[]
  by_user: LLMStatsByUser[]
}

// ── 审计日志（plan 13）──

export interface AuditLogItem {
  id: string
  actor_id: string | null
  actor_username: string
  action: string
  target_type: string
  target_id: string | null
  detail: Record<string, unknown> | null
  created_at: string | null
}

export interface AuditLogPage {
  total: number
  page: number
  size: number
  items: AuditLogItem[]
}

// ── 用户自定义配置（embedding 已改走固定微服务，只剩 chat）──

/** GET /settings/llm 列表项 / POST、PUT 返回的单条 chat 配置（key 掩码）。 */
export interface UserLLMConfig {
  id: string
  name: string
  provider: string
  base_url: string
  api_key_masked: string
  model: string
}

/** POST /settings/llm 新增请求体。 */
export interface UserLLMConfigCreate {
  name: string
  provider?: string
  base_url: string
  api_key: string
  model: string
}

/** PUT /settings/llm/{id} 修改请求体（全可选，api_key 留空则不变）。 */
export interface UserLLMConfigUpdate {
  name?: string
  provider?: string
  base_url?: string
  api_key?: string
  model?: string
}

/**
 * GET /settings/my-grant 返回；普通用户查自己的全局 Key 授权状态（选源器用）。
 * 与 admin 侧 UserGrant 同构；无记录时后端返回 {is_active: false}。
 */
export type MyGrant = UserGrant

// ── 解析任务 ──

export interface ParseJob {
  id: string
  status: string
  template_id: string | null
  error_message: string | null
}

// ── 标签 ──
export interface Tag {
  id: string
  name: string
  project_count: number
}

export interface TagCreate {
  name: string
}

export interface TagUpdate {
  name: string
}

export interface TagMerge {
  source_id: string
  target_id: string
}

export interface ProjectTag {
  id: string
  name: string
}

// ── 知识库(三域 + 审核流)──

export interface KnowledgeFile {
  id: string
  uploader_id: string
  scope: 'personal' | 'global'
  filename: string
  mime_type: string
  size: number
  source_type: string // external_pdf / external_docx / disclosure_export
  url?: string | null // 网页来源的原 URL(external_web 才有值)
  created_at: string
}

export interface KnowledgeReview {
  id: string
  submitter_id: string
  reviewer_id: string | null
  source_type: string // external / disclosure_export
  file_id: string
  filename: string | null // 联查 KnowledgeFile 得到(审核工作台展示用)
  status: 'pending' | 'approved' | 'rejected'
  review_comment: string | null
  created_at: string
  reviewed_at: string | null
}

// ── Diff（计划 16）──

/** diff-match-patch 操作：-1=删除 / 0=相等 / 1=插入（元组，可解构为 [op, text]） */
export type InlineDiffOp = [number, string]

export interface Hunk {
  id: string
  type: 'replace' | 'insert' | 'delete'
  inline?: InlineDiffOp[]
  text?: string
  original_para?: string
  modified_para?: string
}

export interface DiffResponse {
  hunks: Hunk[]
  /**
   * 仅 rewrite-diff 端点返回：选区首次出现被 ai_text 替换后的整章 markdown。
   * apply-diff 时前端必须把它作为 ai_text 回传——后端按 (original, ai_text) 重算
   * hunks，只有此 ai_full 与计算时一致，accepted_hunk_ids 才能对齐（spec §3.4）。
   */
  ai_full?: string | null
}

/** 选区重写 diff 请求体（POST /sections/{id}/rewrite-diff，纯计算不改库）。 */
export interface RewriteDiffRequest {
  selected_text: string
  ai_text: string
}

// ── 协作（计划 17）──

export interface Member {
  id: string
  project_id: string
  user_id: string
  email: string
  name: string
  role: string
  created_at: string
}

export interface ShareLink {
  id: string
  project_id: string
  token: string
  permissions: string
  expires_at: string | null
  created_by: string
  created_at: string
}

export interface ShareLinkCreate {
  permissions: 'comment' | 'readonly'
  expires_days?: number | null
}

export interface SharedInfo {
  title: string
  permissions: string
  project_id: string
  share_token: string
}

// ── AI 会话 ──

export interface Conversation {
  id: string
  title: string
  status: 'draft' | 'active'
  created_at: string
  updated_at: string
}

// ── Agent Skill（spec 合规，两档可见性）──
export type SkillScope = 'global' | 'personal'
export type SkillStatus = 'draft' | 'active'

export interface Skill {
  id: string
  name: string
  description: string
  scope: SkillScope
  owner_id: string | null
  status: SkillStatus
  minio_prefix: string
  created_at: string
  updated_at: string
}

export interface SkillDetail extends Skill {
  skill_md: string
}

export interface SkillCreate {
  name: string
  description: string
  skill_md: string
}

export interface SkillUpdate {
  description?: string
  skill_md?: string
  status?: SkillStatus
}

// ── LLM provider 模板（添加配置时选模板自动填；embedding 已无预设）──
export interface ProviderTemplate {
  id: string
  name: string
  base_url: string
  default_model: string
  models_endpoint: string
  docs_url: string | null
  note: string | null
}

// ── 测试连接结果（只测 chat；embedding 走固定服务，不再经此测）──
export interface TestConnectionResult {
  ok: boolean
  chat: {
    ok: boolean
    latency_ms: number | null
    sample: string | null
    error: string | null
  } | null
  embedding: null
  error: string | null
}

// ── 拉取模型列表结果 ──
export interface ListModelsResult {
  models: string[]
  truncated: boolean
  error: string | null
}

// ── 网页摄入(Firecrawl)──

// 网页摄入任务(对应后端 WebIngestionJob)
export interface WebIngestJob {
  id: string
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  status: 'pending' | 'running' | 'completed' | 'failed'
  max_pages: number
  pages_fetched: number
  pages_filtered: number
  file_ids: string[]
  error_message: string | null
  created_at: string
  completed_at: string | null
}

// POST /knowledge/ingest/web 的响应(联合类型)
export type WebIngestResult =
  | { kind: 'file'; file: KnowledgeFile }
  | { kind: 'job'; job: WebIngestJob }

// 网页摄入请求体
export interface WebIngestRequest {
  url: string
  mode: 'scrape' | 'crawl'
  scope: 'personal' | 'global'
  max_pages?: number
}

// Firecrawl 全局配置(GET /admin/console/firecrawl)
export interface FirecrawlSettings {
  enabled: boolean
  api_key_masked: string
  base_url: string
}

// Firecrawl 配置 PUT 请求体
export interface FirecrawlConfigPayload {
  enabled: boolean
  api_key: string
  base_url: string | null
}
