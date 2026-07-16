import type {
  ApiError,
  LoginRequest,
  Project,
  ProjectCreate,
  ProjectTag,
  ProjectUpdate,
  RegisterRequest,
  Tag,
  TagCreate,
  TagMerge,
  TagUpdate,
  User,
} from '@/types/api'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${BASE}/api/v1${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
    let err: ApiError
    try {
      err = (await res.json()) as ApiError
    } catch {
      err = { code: 'unknown', message: `HTTP ${res.status}` }
    }
    throw err
  }

  // 204 No Content
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export const api = {
  // ── 认证 ──
  register: (data: RegisterRequest) =>
    request<User>('/auth/register', { method: 'POST', body: JSON.stringify(data) }),

  login: (data: LoginRequest) =>
    request<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify(data) }),

  logout: () => request<{ message: string }>('/auth/logout', { method: 'POST' }),

  me: () => request<User>('/auth/me'),

  // ── 项目 ──
  listProjects: () => request<Project[]>('/projects'),

  createProject: (data: ProjectCreate) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),

  getProject: (id: string) => request<Project>(`/projects/${id}`),

  updateProject: (id: string, data: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteProject: (id: string) =>
    request<void>(`/projects/${id}`, { method: 'DELETE' }),

  listProjectsFiltered: (params: { status?: string; q?: string; tag_id?: string }) =>
    request<Project[]>(`/projects?${new URLSearchParams(
      Object.entries(params).filter(([, v]) => v).map(([k, v]) => [k, v!])
    ).toString()}`),

  // ── 标签 ──
  listTags: () => request<Tag[]>('/tags'),

  createTag: (data: TagCreate) =>
    request<Tag>('/tags', { method: 'POST', body: JSON.stringify(data) }),

  renameTag: (id: string, data: TagUpdate) =>
    request<Tag>(`/tags/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),

  deleteTag: (id: string) =>
    request<void>(`/tags/${id}`, { method: 'DELETE' }),

  mergeTags: (data: TagMerge) =>
    request<Tag>('/tags/merge', { method: 'POST', body: JSON.stringify(data) }),

  attachProjectTag: (projectId: string, tagId: string) =>
    request<ProjectTag[]>(`/projects/${projectId}/tags/${tagId}`, { method: 'POST' }),

  detachProjectTag: (projectId: string, tagId: string) =>
    request<ProjectTag[]>(`/projects/${projectId}/tags/${tagId}`, { method: 'DELETE' }),

  // ── 模板 ──
  listTemplates: () => request<import('@/types/api').TemplateSummary[]>('/templates'),

  getTemplate: (id: string) => request<import('@/types/api').Template>(`/templates/${id}`),

  uploadTemplate: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/templates`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json()
  },

  getParseJob: (jobId: string) =>
    request<{ id: string; status: string; template_id: string | null; error_message: string | null }>(
      `/templates/parse-jobs/${jobId}`,
    ),

  deleteTemplate: (id: string) =>
    request<void>(`/templates/${id}`, { method: 'DELETE' }),

  setDefaultTemplate: (id: string) =>
    request<import('@/types/api').TemplateSummary>(`/templates/${id}/default`, { method: 'POST' }),

  // ── 技能开关 ──
  listSkills: (projectId: string) =>
    request<import('@/types/api').AgentSkill[]>(`/projects/${projectId}/skills`),

  updateSkill: (projectId: string, skillKey: string, data: { enabled: boolean; config?: object | null }) =>
    request<import('@/types/api').AgentSkill>(`/projects/${projectId}/skills/${skillKey}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),

  // ── 章节 ──
  listSections: (projectId: string) =>
    request<import('@/types/api').Section[]>(`/projects/${projectId}/sections`),

  getSection: (id: string) => request<import('@/types/api').Section>(`/sections/${id}`),

  updateSection: (id: string, data: { content?: object; status?: string; expected_version?: number }) =>
    request<import('@/types/api').Section>(`/sections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // ── AI（SSE 流式）──
  streamChat: async (
    sectionId: string,
    message: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
      signal,
    })
    return _consumeSSE(res, onToken)
  },

  streamGenerate: async (
    sectionId: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/generate`, {
      method: 'POST',
      credentials: 'include',
      signal,
    })
    return _consumeSSE(res, onToken)
  },

  // ── 版本 ──
  listVersions: (sectionId: string) =>
    request<import('@/types/api').Version[]>(`/sections/${sectionId}/versions`),

  createVersion: (sectionId: string, note?: string) =>
    request<import('@/types/api').Version>(`/sections/${sectionId}/versions`, {
      method: 'POST', body: JSON.stringify({ note }),
    }),

  rollbackVersion: (sectionId: string, versionId: string) =>
    request<{ message: string }>(`/sections/${sectionId}/versions/${versionId}/rollback`, { method: 'POST' }),

  // ── 预览/导出 ──
  previewProject: (projectId: string) =>
    request<import('@/types/api').ProjectPreview>(`/projects/${projectId}/preview`),

  exportDocxUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/export/docx`,
  exportMarkdownUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/export/markdown`,

  // ── 知识库 ──
  archiveProject: (projectId: string) =>
    request<{ project_id: string; chunks: number; status: string }>(`/projects/${projectId}/archive`, { method: 'POST' }),

  // ── 附件 ──
  listAttachments: (projectId: string) =>
    request<import('@/types/api').Attachment[]>(`/projects/${projectId}/attachments`),

  uploadAttachment: async (sectionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/attachments`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<import('@/types/api').Attachment>
  },

  deleteAttachment: (id: string) =>
    request<void>(`/attachments/${id}`, { method: 'DELETE' }),

  attachmentUrl: (projectId: string, attachmentId: string) =>
    `${BASE}/api/v1/projects/${projectId}/attachments/${attachmentId}/file`,

  // ── 审查 ──
  runReview: (projectId: string) =>
    request<import('@/types/api').ReviewRecord>(`/projects/${projectId}/review`, { method: 'POST' }),
  listReviews: (projectId: string) =>
    request<import('@/types/api').ReviewRecord[]>(`/projects/${projectId}/reviews`),

  // ── Rubric ──
  getRubric: () => request<import('@/types/api').Rubric>(`/rubric`),
  updateRubric: (data: { name?: string; criteria?: Record<string, unknown>[] }) =>
    request<import('@/types/api').Rubric>(`/rubric`, { method: 'PUT', body: JSON.stringify(data) }),
  resetRubric: () => request<import('@/types/api').Rubric>(`/rubric/reset`, { method: 'POST' }),

  // ── 管理员 ──
  listUsers: () => request<import('@/types/api').AdminUser[]>(`/admin/users`),
  getGlobalLLM: () => request<import('@/types/api').GlobalLLMSettings>(`/admin/llm-config`),
  setGlobalLLM: (data: { enabled: boolean; base_url?: string; api_key?: string; model?: string }) =>
    request<import('@/types/api').GlobalLLMSettings>(`/admin/llm-config`, { method: 'PUT', body: JSON.stringify(data) }),

  banUser: (userId: string, status: 'active' | 'disabled') =>
    request<{ id: string; status: string }>(`/admin/users/${userId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  resetUserPassword: (userId: string, newPassword: string) =>
    request<{ ok: boolean }>(`/admin/users/${userId}/reset-password`, { method: 'POST', body: JSON.stringify({ new_password: newPassword }) }),
  listLLMStats: (days = 7) =>
    request<import('@/types/api').LLMStats>(`/admin/stats/llm?days=${days}`),
  listAuditLogs: (page = 1, size = 50) =>
    request<import('@/types/api').AuditLogPage>(`/admin/audit-logs?page=${page}&size=${size}`),

  // ── 用户设置 ──
  getMyLLM: () => request<import('@/types/api').UserLLMSettings | null>(`/settings/llm`),
  setMyLLM: (data: { provider?: string; base_url: string; api_key: string; model: string; embedding_model?: string }) =>
    request<{ message: string }>(`/settings/llm`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMyLLM: () => request<{ message: string }>(`/settings/llm`, { method: 'DELETE' }),
  testMyLLM: (data: { base_url: string; api_key: string; model: string }) =>
    request<{ ok: boolean; response?: string; error?: string }>(`/settings/llm/test`, { method: 'POST', body: JSON.stringify(data) }),

  // ── 知识库(三域 + 审核流)──
  uploadKnowledgeFile: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/knowledge/upload`, {
      method: 'POST', credentials: 'include', body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<import('@/types/api').KnowledgeFile>
  },

  adminUploadGlobal: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/admin/knowledge/upload`, {
      method: 'POST', credentials: 'include', body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<{ file_id: string; scope: string; source_type: string }>
  },

  submitKnowledgeReview: (fileId: string) =>
    request<{ review_id: string; status: string }>(
      `/knowledge/files/${fileId}/submit-review`, { method: 'POST' },
    ),

  submitDisclosureReview: (projectId: string) =>
    request<{ review_id: string; status: string }>(
      `/projects/${projectId}/submit-disclosure-review`, { method: 'POST' },
    ),

  listPersonalKnowledge: () =>
    request<import('@/types/api').KnowledgeFile[]>('/knowledge/files/personal'),
  listGlobalKnowledge: () =>
    request<import('@/types/api').KnowledgeFile[]>('/knowledge/files/global'),

  knowledgeFileUrl: (fileId: string) =>
    `${BASE}/api/v1/knowledge/files/${fileId}/download`,

  // ── 知识库审核(admin)──
  listPendingReviews: () =>
    request<import('@/types/api').KnowledgeReview[]>('/admin/knowledge/reviews'),
  approveReview: (reviewId: string) =>
    request<import('@/types/api').KnowledgeReview>(
      `/admin/knowledge/reviews/${reviewId}/approve`, { method: 'POST' },
    ),
  rejectReview: (reviewId: string, comment?: string) =>
    request<import('@/types/api').KnowledgeReview>(
      `/admin/knowledge/reviews/${reviewId}/reject`,
      { method: 'POST', body: JSON.stringify({ comment: comment ?? null }) },
    ),
}

async function _consumeSSE(res: Response, onToken: (t: string) => void): Promise<void> {
  if (!res.body) return
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE 事件以空行分隔
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''
    for (const evt of events) {
      const lines = evt.split('\n')
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('data: ')) dataLine = line.slice(6)
      }
      if (!dataLine) continue
      try {
        const data = JSON.parse(dataLine)
        if (data.text) onToken(data.text)
        // heartbeat/error/done 事件无 text，忽略（上层靠流结束判断）
      } catch {
        // 忽略解析失败的行
      }
    }
  }
}
