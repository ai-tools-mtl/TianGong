import type {
  ApiError,
  DiffResponse,
  LoginRequest,
  Member,
  MyGrant,
  Project,
  ProjectCreate,
  ProjectTag,
  ProjectUpdate,
  RegisterRequest,
  Section,
  ShareLink,
  ShareLinkCreate,
  SharedInfo,
  Skill,
  SkillCreate,
  SkillDetail,
  SkillUpdate,
  Tag,
  TagCreate,
  TagMerge,
  TagUpdate,
  User,
  UserLLMConfig,
  UserLLMConfigCreate,
  UserLLMConfigUpdate,
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
    // 全局拦截 401：JWT 过期或被踢下线。清登录态 + 硬跳转 /login。
    // login 接口本身返回 401（密码错）不跳转——已在 /login 页时跳转会死循环，
    // 由 login 页自己处理错误提示。
    if (
      res.status === 401 &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/login')
    ) {
      const { useAuthStore } = await import('@/stores/auth')
      useAuthStore.getState().setUser(null)
      window.location.href = '/login'
    }
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

  // ── Admin：内置模板管理（refactor/admin-ia-phase3 切片 B）──
  listAdminTemplates: () =>
    request<import('@/types/api').TemplateSummary[]>(`/admin/content/templates`),
  uploadAdminTemplate: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/admin/content/templates/upload`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<{ parse_job_id: string; status: string }>
  },
  getAdminParseJob: (jobId: string) =>
    request<{ id: string; status: string; template_id: string | null; error_message: string | null }>(
      `/admin/content/templates/parse-jobs/${jobId}`,
    ),
  setAdminTemplateStatus: (id: string, status: 'draft' | 'published' | 'offline') =>
    request<import('@/types/api').TemplateSummary>(
      `/admin/content/templates/${id}/status`,
      { method: 'POST', body: JSON.stringify({ status }) },
    ),
  deleteAdminTemplate: (id: string) =>
    request<void>(`/admin/content/templates/${id}`, { method: 'DELETE' }),

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
    source?: string,
    conversationId?: string,
    onDone?: (data: { message_id: string; conversation_id?: string; title?: string | null }) => void,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId ?? null,
        ...(source ? { source } : {}),
      }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone)
  },

  streamGenerate: async (
    sectionId: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    source?: string,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/generate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(source ? { source } : {}),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken)
  },

  streamRewrite: async (
    sectionId: string,
    data: { selected_text: string; instruction?: string },
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/rewrite`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal,
    })
    return _consumeSSE(res, onToken)
  },

  listMessages: (sectionId: string, conversationId?: string) =>
    request<{ id: string; role: string; content: string; created_at: string }[]>(
      `/sections/${sectionId}/messages${conversationId ? `?conversation_id=${conversationId}` : ''}`,
    ),

  // ── AI 会话 ──
  listConversations: (sectionId: string) =>
    request<import('@/types/api').Conversation[]>(`/sections/${sectionId}/conversations`),

  createConversation: (sectionId: string, title?: string) =>
    request<import('@/types/api').Conversation>(`/sections/${sectionId}/conversations`, {
      method: 'POST',
      body: JSON.stringify({ title: title ?? null }),
    }),

  updateConversation: (sectionId: string, conversationId: string, title: string) =>
    request<import('@/types/api').Conversation>(
      `/sections/${sectionId}/conversations/${conversationId}`,
      { method: 'PATCH', body: JSON.stringify({ title }) },
    ),

  deleteConversation: (sectionId: string, conversationId: string) =>
    request<void>(`/sections/${sectionId}/conversations/${conversationId}`, { method: 'DELETE' }),

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
  setGlobalLLM: (data: {
    enabled: boolean
    base_url?: string
    api_key?: string
    model?: string
    embedding_model?: string
    allowed_models?: string[]
  }) =>
    request<import('@/types/api').GlobalLLMSettings>(`/admin/llm-config`, { method: 'PUT', body: JSON.stringify(data) }),

  banUser: (userId: string, status: 'active' | 'disabled') =>
    request<{ id: string; status: string }>(`/admin/users/${userId}/status`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  resetUserPassword: (userId: string, newPassword: string) =>
    request<{ ok: boolean }>(`/admin/users/${userId}/reset-password`, { method: 'POST', body: JSON.stringify({ new_password: newPassword }) }),

  // 全局 Key 授权（Task 2.2）
  getUserGrant: (userId: string) =>
    request<import('@/types/api').UserGrant>(`/admin/users/${userId}/global-llm-grant`),
  grantGlobalLLM: (userId: string) =>
    request<{ message: string }>(`/admin/users/${userId}/global-llm-grant`, { method: 'POST' }),
  revokeGlobalLLM: (userId: string) =>
    request<{ message: string }>(`/admin/users/${userId}/global-llm-grant`, { method: 'DELETE' }),

  listLLMStats: (days = 7) =>
    request<import('@/types/api').LLMStats>(`/admin/stats/llm?days=${days}`),
  /** GET /admin/users/{id} 单用户详情（含 grant_detail）。 */
  getUserDetail: (userId: string) =>
    request<import('@/types/api').UserDetail>(`/admin/users/${userId}`),
  listUserStats: () =>
    request<import('@/types/api').UserStats>(`/admin/stats/users`),
  listAuditLogs: (page = 1, size = 50) =>
    request<import('@/types/api').AuditLogPage>(`/admin/audit-logs?page=${page}&size=${size}`),

  // 落地页聚合（refactor/admin-ia-phase1）
  /** 最近登录 5 个用户（按 last_login_at 倒序）。 */
  listRecentLogins: () =>
    request<import('@/types/api').RecentUser[]>(`/admin/users/recent-logins`),
  /** 最近注册 5 个用户（按 created_at 倒序）。 */
  listRecentCreations: () =>
    request<import('@/types/api').RecentUser[]>(`/admin/users/recent-creations`),
  /** LLM 调用健康摘要（落地页 LLM 健康卡用，返回 status=ok/warning）。 */
  getLLMHealth: (days = 7) =>
    request<import('@/types/api').LLMHealth>(`/admin/stats/llm/health?days=${days}`),

  // ── 用户设置（多 BYOK 配置 CRUD，Task 4.0）──
  listMyLLM: () => request<UserLLMConfig[]>(`/settings/llm`),
  createMyLLM: (data: UserLLMConfigCreate) =>
    request<UserLLMConfig>(`/settings/llm`, { method: 'POST', body: JSON.stringify(data) }),
  updateMyLLM: (configId: string, data: UserLLMConfigUpdate) =>
    request<UserLLMConfig>(`/settings/llm/${configId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMyLLM: (configId: string) =>
    request<{ message: string }>(`/settings/llm/${configId}`, { method: 'DELETE' }),
  testMyLLM: (data: { base_url: string; api_key: string; model: string }) =>
    request<{ ok: boolean; response?: string; error?: string }>(`/settings/llm/test`, { method: 'POST', body: JSON.stringify(data) }),
  /** 普通用户查自己的全局 Key 授权状态（选源器用）。 */
  getMyGrant: () => request<MyGrant>(`/settings/my-grant`),

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

  // ── Diff（计划 16）──
  computeDiff: (sectionId: string, aiText: string) =>
    request<DiffResponse>(`/sections/${sectionId}/diff`, {
      method: 'POST',
      body: JSON.stringify({ ai_text: aiText }),
    }),

  applyDiff: (sectionId: string, data: { ai_text: string; accepted_hunk_ids: string[]; expected_version: number }) =>
    request<Section>(`/sections/${sectionId}/apply-diff`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── 协作（计划 17）──
  listMembers: (projectId: string) =>
    request<Member[]>(`/projects/${projectId}/members`),

  addMember: (projectId: string, email: string) =>
    request<Member>(`/projects/${projectId}/members`, {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  removeMember: (projectId: string, memberId: string) =>
    request<void>(`/projects/${projectId}/members/${memberId}`, { method: 'DELETE' }),

  listShareLinks: (projectId: string) =>
    request<ShareLink[]>(`/projects/${projectId}/share-links`),

  createShareLink: (projectId: string, data: ShareLinkCreate) =>
    request<ShareLink>(`/projects/${projectId}/share-links`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  revokeShareLink: (projectId: string, linkId: string) =>
    request<void>(`/projects/${projectId}/share-links/${linkId}`, { method: 'DELETE' }),

  getSharedInfo: (token: string) =>
    request<SharedInfo>(`/shared/${token}`),

  // ── Agent Skills（spec 合规）──
  listGlobalSkills: () => request<Skill[]>('/admin/skills'),
  createGlobalSkill: (data: SkillCreate) =>
    request<Skill>('/admin/skills', { method: 'POST', body: JSON.stringify(data) }),
  getGlobalSkill: (id: string) => request<SkillDetail>(`/admin/skills/${id}`),
  updateGlobalSkill: (id: string, data: SkillUpdate) =>
    request<Skill>(`/admin/skills/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteGlobalSkill: (id: string) =>
    request<{ ok: boolean }>(`/admin/skills/${id}`, { method: 'DELETE' }),

  listVisibleSkills: () => request<Skill[]>('/skills/visible'),
  listMySkills: () => request<Skill[]>('/skills/mine'),
  createMySkill: (data: SkillCreate) =>
    request<Skill>('/skills/mine', { method: 'POST', body: JSON.stringify(data) }),
  getMySkill: (id: string) => request<SkillDetail>(`/skills/mine/${id}`),
  updateMySkill: (id: string, data: SkillUpdate) =>
    request<Skill>(`/skills/mine/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMySkill: (id: string) =>
    request<{ ok: boolean }>(`/skills/mine/${id}`, { method: 'DELETE' }),
}

/**
 * SSE 端点（streamChat/streamGenerate/...）的初始 POST 非 2xx 时的错误归一化。
 *
 * 后端 AppError 经全局异常处理器序列化为 {code, message}（见 exceptions.py），
 * 与 request() 的 ApiError 形态一致。这里把 HTTP 状态码挂到 Error 上，
 * 方便调用方按 status（403/404/...）分支处理。
 *
 * 例如全局 Key 授权被撤销：后端 resolve_llm_config 抛 ForbiddenError →
 * HTTP 403 + {code:"forbidden", message:"未授权使用全局 Key..."}。
 */
async function _sseHttpError(res: Response): Promise<Error & { status: number; code?: string }> {
  let body: { code?: string; message?: string } | null = null
  try {
    body = (await res.json()) as { code?: string; message?: string }
  } catch {
    body = null
  }
  const err = new Error(body?.message || `HTTP ${res.status}`) as Error & {
    status: number
    code?: string
  }
  err.status = res.status
  if (body?.code) err.code = body.code
  return err
}

/**
 * 消费 SSE 流：按 event 字段分发。
 *
 * 后端事件类型（见 app/api/ai.py）：
 * - token：追加文本 {text}
 * - heartbeat：保活心跳，忽略
 * - done：完成 {message_id, conversation_id?, title?}，触发 onDone 回调
 * - error：服务端错误 {code, message}，抛出 ApiError 让上层走 catch 分支
 *
 * 原实现只看 data.text，导致 error 事件被静默吞掉（用户看到"空回复+无报错"）。
 */
async function _consumeSSE(
  res: Response,
  onToken: (t: string) => void,
  onDone?: (data: { message_id: string; conversation_id?: string; title?: string | null }) => void,
): Promise<void> {
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
      let eventType = 'message'
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim()
        else if (line.startsWith('data: ')) dataLine = line.slice(6)
      }
      if (!dataLine) continue
      let data: Record<string, unknown> = {}
      try {
        data = JSON.parse(dataLine)
      } catch {
        continue
      }
      if (eventType === 'error') {
        // 服务端明确报错：抛出，让调用方弹 toast
        const code = (data.code as string) || 'llm_error'
        const message = (data.message as string) || 'AI 服务错误'
        const err: ApiError = { code, message }
        throw err
      }
      if (eventType === 'token') {
        const text = data.text as string | undefined
        if (text) onToken(text)
      } else if (eventType === 'done' && onDone) {
        // done 事件：透传元数据（message_id / conversation_id / title）
        onDone(data as { message_id: string; conversation_id?: string; title?: string | null })
      }
      // heartbeat：忽略
    }
  }
}
