// 与后端 schemas 对齐

export interface User {
  id: string
  email: string
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
  email: string
  password: string
  name: string
}

export interface LoginRequest {
  email: string
  password: string
}

// ── 模板 ──

export interface TemplateSection {
  id: string
  order: number
  key: string
  title: string
  level: number
}

export interface TemplateSummary {
  id: string
  name: string
  is_default: boolean
  is_system: boolean
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
  email: string
  name: string
  role: string
  status: string
  project_count: number
  has_own_llm_key: boolean
  created_at: string
}

export interface GlobalLLMSettings {
  llm_global_enabled: boolean
  global_config: { base_url: string; api_key_masked: string; model: string } | null
}

// ── LLM 调用统计（plan 13）──

export interface LLMStatsByModel {
  model: string
  calls: number
  success: number
  failed: number
  avg_duration_ms: number | null
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
  by_model: LLMStatsByModel[]
  by_user: LLMStatsByUser[]
}

// ── 审计日志（plan 13）──

export interface AuditLogItem {
  id: string
  actor_id: string | null
  actor_email: string
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

export interface UserLLMSettings {
  provider: string
  base_url: string
  api_key_masked: string
  model: string
  embedding_model: string | null
  is_active: boolean
}

// ── 技能开关 ──

export interface AgentSkill {
  skill_key: string
  name: string
  description: string
  enabled: boolean
  config: Record<string, unknown> | null
  is_builtin: boolean
  is_overridden: boolean
}

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
