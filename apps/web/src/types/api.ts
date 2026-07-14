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
