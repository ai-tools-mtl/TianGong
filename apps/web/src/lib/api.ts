import type {
  ApiError,
  DiffResponse,
  ListModelsResult,
  LoginRequest,
  Member,
  Memory,
  MemoryCreate,
  MemoryUpdate,
  MyGrant,
  Project,
  ProjectCreate,
  ProjectTag,
  ProjectUpdate,
  ProviderTemplate,
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
  TestConnectionResult,
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

  // ── 项目初始化助手（对话式新建）──
  /** 从描述建项目 + 8 空章节，返回 project_id（首轮对话前调用）。 */
  createProjectFromChat: (description: string) =>
    request<{ project_id: string; section_id: string | null; title: string }>(
      '/projects/from-chat',
      { method: 'POST', body: JSON.stringify({ description }) },
    ),

  /** 初始化对话（SSE）。事件同 chat：token / done / heartbeat / error。 */
  streamInitChat: async (
    projectId: string,
    message: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    conversationId?: string,
    onDone?: (data: { message_id: string; conversation_id?: string }) => void,
  ) => {
    const res = await fetch(`${BASE}/api/v1/projects/${projectId}/init-chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message,
        conversation_id: conversationId ?? null,
      }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone)
  },

  /**
   * 批量生成各章节初稿（SSE）。事件比 chat 多 chapter_start / chapter_done：
   * - chapter_start {index, total, title, key}：开始生成某章
   * - token {text}：当前章节的生成 token（实时累加显示）
   * - chapter_done {index, title, status, error}：某章完成（status: ok|failed）
   * - done {project_id}：全部完成
   */
  streamInitGenerate: async (
    projectId: string,
    handlers: {
      onChapterStart?: (d: { index: number; total: number; title: string; key: string }) => void
      onToken?: (t: string) => void
      onChapterDone?: (d: { index: number; title: string; key: string; status: string; error: string | null }) => void
      onAllDone?: (d: { project_id: string }) => void
    },
    signal?: AbortSignal,
    conversationId?: string,
    sections?: string[],
  ) => {
    const res = await fetch(`${BASE}/api/v1/projects/${projectId}/init-generate`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: conversationId ?? null,
        ...(sections && sections.length ? { sections } : {}),
      }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
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
          throw {
            code: (data.code as string) || 'llm_error',
            message: (data.message as string) || 'AI 服务错误',
          } as ApiError
        }
        if (eventType === 'chapter_start') {
          handlers.onChapterStart?.(data as { index: number; total: number; title: string; key: string })
        } else if (eventType === 'token') {
          const text = data.text as string | undefined
          if (text) handlers.onToken?.(text)
        } else if (eventType === 'chapter_done') {
          handlers.onChapterDone?.(data as { index: number; title: string; key: string; status: string; error: string | null })
        } else if (eventType === 'done') {
          handlers.onAllDone?.(data as { project_id: string })
        }
        // heartbeat：忽略
      }
    }
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
  /** POST /admin/users admin 直接创建用户(内部产品化:无需邀请码)。 */
  adminCreateUser: (data: import('@/types/api').AdminCreateUserRequest) =>
    request<import('@/types/api').AdminUser>(`/admin/users`, { method: 'POST', body: JSON.stringify(data) }),
  getGlobalLLM: () => request<import('@/types/api').GlobalLLMSettings>(`/admin/llm-config`),
  /**
   * 保存全局 LLM 配置（PUT /admin/llm-config）。
   * 只管 chat（embedding 走固定 bge-m3 微服务）；chat_config 不传则只切 enabled 开关。
   * api_key 留空 = 不改（后端只在传值时加密落库）。
   */
  setGlobalLLM: (data: {
    enabled: boolean
    chat_config?: { base_url?: string; api_key?: string; model?: string }
  }) =>
    request<import('@/types/api').GlobalLLMSettings>(`/admin/llm-config`, { method: 'PUT', body: JSON.stringify(data) }),

  // ── Firecrawl 全局配置(admin)──
  getFirecrawlConfig: () =>
    request<import('@/types/api').FirecrawlSettings>('/admin/console/firecrawl'),

  setFirecrawlConfig: (payload: import('@/types/api').FirecrawlConfigPayload) =>
    request<{ ok: true }>('/admin/console/firecrawl', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  // ── MinerU 全局配置(admin) — PDF→Markdown 云端解析 ──
  getMineruConfig: () =>
    request<import('@/types/api').MineruSettings>('/admin/console/mineru'),

  setMineruConfig: (payload: import('@/types/api').MineruConfigPayload) =>
    request<{ ok: true }>('/admin/console/mineru', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  /** 测试 MinerU 连通性（解析一个极小 PDF 样本）。 */
  testMineruConfig: () =>
    request<{ ok: boolean; message: string }>('/admin/console/mineru/test', {
      method: 'POST',
    }),

  // ── MCP server 全局配置（admin）── stdio/http/sse 三种传输
  listMcpServers: () =>
    request<import('@/types/api').McpServer[]>('/admin/mcp/servers'),

  createMcpServer: (payload: import('@/types/api').McpServerPayload) =>
    request<import('@/types/api').McpServer>('/admin/mcp/servers', {
      method: 'POST', body: JSON.stringify(payload),
    }),

  getMcpServer: (id: string) =>
    request<import('@/types/api').McpServer>(`/admin/mcp/servers/${id}`),

  updateMcpServer: (id: string, payload: Partial<import('@/types/api').McpServerPayload>) =>
    request<import('@/types/api').McpServer>(`/admin/mcp/servers/${id}`, {
      method: 'PUT', body: JSON.stringify(payload),
    }),

  deleteMcpServer: (id: string) =>
    request<{ ok: boolean }>(`/admin/mcp/servers/${id}`, { method: 'DELETE' }),

  getMcpEnabled: () =>
    request<import('@/types/api').McpGlobalEnabled>('/admin/mcp/enabled'),

  setMcpEnabled: (payload: import('@/types/api').McpGlobalEnabled) =>
    request<import('@/types/api').McpGlobalEnabled>('/admin/mcp/enabled', {
      method: 'PUT', body: JSON.stringify(payload),
    }),

  testMcpServer: (id: string) =>
    request<import('@/types/api').McpTestResult>(`/admin/mcp/servers/${id}/test`, {
      method: 'POST',
    }),

  importMcpServers: (json: object) =>
    request<import('@/types/api').McpServer[]>('/admin/mcp/servers/import', {
      method: 'POST', body: JSON.stringify(json),
    }),

  // admin LLM 连接测试 / 模型拉取（embedding 走固定服务，只剩 chat 两端点）
  /** admin 测试全局 chat 连接。字段全可选：留空走当前已存的 chat 配置复检。 */
  testGlobalChat: (data: {
    base_url?: string
    api_key?: string
    model?: string
  }) =>
    request<TestConnectionResult>(`/admin/llm-config/chat/test`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  /** admin 按 base_url + api_key 拉取 provider 的可用 chat 模型列表。 */
  listGlobalChatModels: (data: {
    base_url: string
    api_key: string
    provider_template_id?: string | null
  }) =>
    request<ListModelsResult>(`/admin/llm-config/chat/models`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

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

  // ── 邀请码管理（内部产品化：关闭开放注册后的发号机制）──
  listInvites: () => request<import('@/types/api').InviteCode[]>(`/admin/invites`),
  createInvite: (data: import('@/types/api').InviteCodeCreate) =>
    request<import('@/types/api').InviteCode>(`/admin/invites`, { method: 'POST', body: JSON.stringify(data) }),
  revokeInvite: (inviteId: string) =>
    request<{ ok: boolean }>(`/admin/invites/${inviteId}`, { method: 'DELETE' }),

  // ── 用户设置（多自定义配置 CRUD，Task 4.0）──
  listMyLLM: () => request<UserLLMConfig[]>(`/settings/llm`),
  createMyLLM: (data: UserLLMConfigCreate) =>
    request<UserLLMConfig>(`/settings/llm`, { method: 'POST', body: JSON.stringify(data) }),
  updateMyLLM: (configId: string, data: UserLLMConfigUpdate) =>
    request<UserLLMConfig>(`/settings/llm/${configId}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteMyLLM: (configId: string) =>
    request<{ message: string }>(`/settings/llm/${configId}`, { method: 'DELETE' }),
  testMyLLM: (data: {
    base_url: string
    api_key: string
    model: string
  }) =>
    request<TestConnectionResult>(`/settings/llm/test`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  /** 普通用户查自己的全局 Key 授权状态（选源器用）。 */
  getMyGrant: () => request<MyGrant>(`/settings/my-grant`),

  // ── LLM provider 模板 / 模型拉取（feat/llm-config-redesign）──
  /** 内置 provider 模板列表（选模板自动填 base_url/model 等）。 */
  listProviderTemplates: () =>
    request<ProviderTemplate[]>(`/settings/llm/templates`),
  /** 按 base_url + api_key 拉取 provider 的可用模型列表。 */
  listProviderModels: (data: {
    base_url: string
    api_key: string
    provider_template_id?: string | null
  }) =>
    request<ListModelsResult>(`/settings/llm/models`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

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

  deleteGlobalKnowledge: (fileId: string) =>
    request<void>(`/admin/knowledge/files/${fileId}`, { method: 'DELETE' }),

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

  // ── 网页摄入(Firecrawl)──
  ingestWeb: (payload: import('@/types/api').WebIngestRequest) =>
    request<import('@/types/api').WebIngestResult>('/knowledge/ingest/web', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getIngestJob: (jobId: string) =>
    request<import('@/types/api').WebIngestJob>(`/knowledge/ingest/jobs/${jobId}`),

  listIngestJobs: () =>
    request<import('@/types/api').WebIngestJob[]>('/knowledge/ingest/jobs'),

  // G2 检索测试
  retrievalTest: (payload: { query: string; top_k?: number; scope?: 'global' | 'personal' | null }) =>
    request<{
      results: Array<{ content: string; score: number; section_key: string | null; project_title: string | null }>
      threshold: number
      top_k: number
      scope: string | null
    }>('/admin/knowledge/retrieval-test', {
      method: 'POST',
      body: JSON.stringify({ top_k: 5, ...payload }),
    }),

  // G4 分块可视化干预：列出某文件的所有 chunks（GET /admin/knowledge/files/{file_id}/chunks）
  listChunks: (fileId: string) =>
    request<Array<{
      id: string
      content: string
      edited_text: string | null
      keywords: string[]
      questions: string[]
      weight: number
      locked: boolean
      chunk_index: number
      source_section_key: string | null
    }>>(`/admin/knowledge/files/${fileId}/chunks`),

  // G4 分块可视化干预：编辑单 chunk（PATCH /admin/knowledge/chunks/{chunk_id}）
  // edited_text 改变会触发后端重新 embed；keywords/questions 进 tsv 参与关键词路召回；
  // weight 是召回分数乘子；locked 防 re-ingest 覆盖。
  updateChunk: (chunkId: string, payload: {
    keywords?: string[]
    questions?: string[]
    weight?: number
    edited_text?: string
    locked?: boolean
    force_unlock?: boolean
  }) =>
    request(`/admin/knowledge/chunks/${chunkId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

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

  /** 选区重写 diff：传入选区原文 + AI 重写文本，返回 hunks（不改库，纯计算）。 */
  rewriteDiff: (sectionId: string, data: { selected_text: string; ai_text: string }) =>
    request<DiffResponse>(`/sections/${sectionId}/rewrite-diff`, {
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

  // zip 导入（FormData，绕过 JSON wrapper，仿 uploadAdminTemplate）
  importGlobalSkillZip: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/admin/skills/import-zip`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<Skill>
  },
  importMySkillZip: async (file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/api/v1/skills/mine/import-zip`, {
      method: 'POST',
      credentials: 'include',
      body: form,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: `HTTP ${res.status}` }))
      throw err
    }
    return res.json() as Promise<Skill>
  },

  // ── 用户绑定长期记忆 ──
  listMemories: (source?: string) =>
    request<Memory[]>('/memories' + (source ? `?source=${source}` : '')),
  createMemory: (data: MemoryCreate) =>
    request<Memory>('/memories', { method: 'POST', body: JSON.stringify(data) }),
  updateMemory: (id: string, data: MemoryUpdate) =>
    request<Memory>(`/memories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteMemory: (id: string) =>
    request<{ ok: boolean }>(`/memories/${id}`, { method: 'DELETE' }),
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
