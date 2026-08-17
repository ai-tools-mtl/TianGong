import type {
  ApiError,
  DiffResponse,
  ListModelsResult,
  LoginRequest,
  Member,
  Memory,
  MemoryCreate,
  MemoryUpdate,
  MessageMeta,
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
  SharedProject,
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
  IMASettings,
  IMAConfigPayload,
  IMATestResult,
  WritingProfile,
  WritingProfileUpdate,
  PatentSearchResponse,
  PriorArtRefs,
} from '@/types/api'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

/**
 * Agent 透明化事件回调（类 zcode 工具调用提示 + 思考过程）。
 * 由 _consumeSSE 在收到对应 SSE 事件时分发，供面板实时累积渲染。
 * 三者皆可选——不传则忽略该类事件。
 */
export type AgentStreamHandlers = {
  /** 模型思考过程片段（流式分块，逐块回调，调用方自行拼接） */
  onThinking?: (t: string) => void
  /** agent 发起工具调用 */
  onToolCall?: (e: { name: string; args: Record<string, unknown> }) => void
  /** 工具返回（result 后端已截断 500 字符） */
  onToolResult?: (e: { name: string; result: string }) => void
  /** HITL 工具确认请求：agent 停在断点，等用户同意/拒绝（streamResume 恢复） */
  onInterrupt?: (e: {
    message_id: string | null
    thread_id: string
    actions: { name: string; args: Record<string, unknown>; description?: string }[]
  }) => void
}

// ── 静默刷新：access token 过期(401)时用 refresh token 续期并重试一次 ──
// access 有效期短(默认 30 分钟)，前端无感续期；refresh 长(默认 30 天)才是「记住登录」窗口。
// 单例锁：并发请求同时遇 401 时只发一次 /auth/refresh，其余共享其结果，避免刷新风暴。
let _refreshing: Promise<boolean> | null = null

async function _doRefresh(): Promise<boolean> {
  // 用裸 fetch（不走 authFetch），避免 refresh 自身 401 递归
  try {
    const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    })
    return res.ok
  } catch {
    return false
  }
}

function _redirectToLogin() {
  if (typeof window === 'undefined') return
  // 已在 /login 页不再跳（防死循环），由 login 页自己提示
  if (window.location.pathname.startsWith('/login')) return
  void import('@/stores/auth').then(({ useAuthStore }) => {
    useAuthStore.getState().setUser(null)
    window.location.href = '/login'
  })
}

async function _refreshAndRetry(path: string, options: RequestInit): Promise<Response | null> {
  // refresh/login 自身的 401 不触发刷新（白名单，防自激）
  if (path.startsWith('/auth/refresh') || path.startsWith('/auth/login')) return null
  if (!_refreshing) _refreshing = _doRefresh()
  const ok = await _refreshing
  _refreshing = null
  if (!ok) {
    _redirectToLogin()
    return null
  }
  // 刷新成功，重试原请求一次（仅一次，不二次刷新防死循环）
  return fetch(`${BASE}/api/v1${path}`, { credentials: 'include', ...options })
}

/**
 * 统一 fetch 封装：固定 credentials + 401 静默刷新重试。
 * 所有走后端的 fetch（JSON / 上传 / SSE 初始请求）都应通过它，确保 access 过期时自动续期。
 * 返回原始 Response；错误解析仍由各调用方负责。
 */
export async function authFetch(path: string, options: RequestInit = {}): Promise<Response> {
  // 完整 URL（含 http 前缀，如 attachmentUrl 拼出的）直接用；相对路径拼 BASE/api/v1
  const url = path.startsWith('http') ? path : `${BASE}/api/v1${path}`
  const res = await fetch(url, { credentials: 'include', ...options })
  if (res.status === 401) {
    const retried = await _refreshAndRetry(path, options)
    if (retried) return retried
  }
  return res
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await authFetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
    // 401 走到这里说明刷新也失败（或本就是 login/refresh 的 401）——刷新逻辑已处理跳转，
    // 这里只负责把错误抛给业务层。login 页 401（密码错）由调用方自行提示。
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
    const res = await authFetch('/templates', {
      method: 'POST',
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
    const res = await authFetch('/admin/content/templates/upload', {
      method: 'POST',
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
    agentHandlers?: AgentStreamHandlers,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // 后端 ChatRequest 只认 chat_source（此前误发 source 字段被 pydantic 静默忽略，
      // 用户显式选择的 LLM 源从未真正传到后端）
      body: JSON.stringify({
        message,
        conversation_id: conversationId ?? null,
        ...(source ? { chat_source: source } : {}),
      }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone, agentHandlers)
  },

  streamGenerate: async (
    sectionId: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    source?: string,
    agentHandlers?: AgentStreamHandlers,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // 同 streamChat：GenerateRequest 只认 chat_source
      body: JSON.stringify(source ? { chat_source: source } : {}),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, undefined, agentHandlers)
  },

  /** 章节针对性修订（T2：建议 directives → 流式修订稿；done 事件带权威全文，
   *  产出候选稿由前端走 /diff + apply-diff 人工审核应用）。 */
  streamRevise: async (
    sectionId: string,
    body: { directives: string[]; origin: 'review' | 'novelty' | 'terms' | 'manual'; chat_source?: string | null },
    onToken: (t: string) => void,
    signal?: AbortSignal,
    agentHandlers?: AgentStreamHandlers,
    onDone?: (d: { content: string; section_id: string }) => void,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/revise`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        directives: body.directives,
        origin: body.origin,
        ...(body.chat_source ? { chat_source: body.chat_source } : {}),
      }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone, agentHandlers)
  },

  /** 续跑中断/未完成的 turn（崩溃续跑 decision=undefined；HITL 决策 approve/reject）。 */
  streamResume: async (
    sectionId: string,
    messageId: string,
    data: { thread_id: string; decision?: 'approve' | 'reject'; message?: string; chat_source?: string | null },
    onToken: (t: string) => void,
    signal?: AbortSignal,
    onDone?: (d: { message_id: string; conversation_id?: string; title?: string | null; content?: string }) => void,
    agentHandlers?: AgentStreamHandlers,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/messages/${messageId}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone, agentHandlers)
  },

  streamRewrite: async (
    sectionId: string,
    data: { selected_text: string; instruction?: string },
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/rewrite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken)
  },

  // 图注润色：看图说话（vision 多模态，model 不支持时后端降级文字描述）
  captionFigures: async (
    sectionId: string,
    data: { attachment_ids?: string[]; descriptions?: string[]; chat_source?: string | null },
    onToken: (t: string) => void,
    signal?: AbortSignal,
  ) => {
    const res = await authFetch(`/sections/${sectionId}/caption-figures`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken)
  },

  /** AI 新颖性评估（SSE 流式 Markdown 报告；done 事件带全文）。 */
  streamAssessNovelty: async (
    projectId: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    chatSource?: string | null,
    onDone?: (d: { content: string; project_id: string }) => void,
  ) => {
    const res = await authFetch(`/projects/${projectId}/patents/assess`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(chatSource ? { chat_source: chatSource } : {}),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone)
  },

  // ── 项目初始化助手（ChatGPT 式独立对话页）──
  listAssistantConversations: () =>
    request<{ id: string; title: string; status: string; created_at: string; updated_at: string }[]>(
      '/assistant/conversations',
    ),

  createAssistantConversation: (title?: string) =>
    request<{ id: string; title: string; status: string; created_at: string; updated_at: string }>(
      '/assistant/conversations',
      { method: 'POST', body: JSON.stringify({ title: title ?? null }) },
    ),

  getAssistantConversation: (id: string) =>
    request<{
      id: string; title: string; status: string; created_at: string; updated_at: string
      project_id: string | null
      draft_outline?: Record<string, { title: string; content: string; evidence_type?: string }> | null
      coverage?: {
        covered: string[]
        missing: string[]
        ready: boolean
        core_filled: [number, number]
        aligned: boolean
        alignment_detail: Record<string, number>
      } | null
      messages: { id: string; role: string; content: string; meta?: MessageMeta | null; created_at: string }[]
    }>(`/assistant/conversations/${id}`),

  deleteAssistantConversation: (id: string) =>
    request<void>(`/assistant/conversations/${id}`, { method: 'DELETE' }),

  /** init 助手对话（SSE）。done 事件额外带 ready_to_create + outline + coverage。 */
  streamAssistantChat: async (
    convId: string,
    message: string,
    onToken: (t: string) => void,
    signal?: AbortSignal,
    onDone?: (d: {
      message_id: string
      conversation_id?: string
      ready_to_create?: boolean
      title?: string
      outline?: Record<string, { title: string; content: string; evidence_type?: string }>
      coverage?: {
        covered: string[]
        missing: string[]
        ready: boolean
        core_filled: [number, number]
        aligned: boolean
        alignment_detail: Record<string, number>
      }
    }) => void,
    chatSource?: string,
    agentHandlers?: AgentStreamHandlers,
  ) => {
    const res = await authFetch(`/assistant/conversations/${convId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, ...(chatSource ? { chat_source: chatSource } : {}) }),
      signal,
    })
    if (!res.ok) throw await _sseHttpError(res)
    return _consumeSSE(res, onToken, onDone as never, agentHandlers)
  },

  /** 扳机落地：建项目+填章（SSE，多事件：project_created/chapter_start/token/chapter_done/done）。 */
  streamAssistantGenerate: async (
    convId: string,
    handlers: {
      onProjectCreated?: (d: { project_id: string }) => void
      onChapterStart?: (d: { index: number; total: number; title: string; key: string }) => void
      onToken?: (t: string) => void
      onChapterDone?: (d: { index: number; title: string; key: string; status: string; error: string | null }) => void
      onAllDone?: (d: { project_id: string }) => void
    },
    signal?: AbortSignal,
    sections?: string[],
  ) => {
    const res = await authFetch(`/assistant/conversations/${convId}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(sections && sections.length ? { sections } : {}),
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
        try { data = JSON.parse(dataLine) } catch { continue }
        if (eventType === 'error') {
          throw { code: (data.code as string) || 'llm_error', message: (data.message as string) || 'AI 服务错误' } as ApiError
        }
        if (eventType === 'project_created') handlers.onProjectCreated?.(data as { project_id: string })
        else if (eventType === 'chapter_start') handlers.onChapterStart?.(data as { index: number; total: number; title: string; key: string })
        else if (eventType === 'token') { const t = data.text as string | undefined; if (t) handlers.onToken?.(t) }
        else if (eventType === 'chapter_done') handlers.onChapterDone?.(data as { index: number; title: string; key: string; status: string; error: string | null })
        else if (eventType === 'done') handlers.onAllDone?.(data as { project_id: string })
      }
    }
  },

  listMessages: (sectionId: string, conversationId?: string) =>
    request<{ id: string; role: string; content: string; meta?: MessageMeta | null; created_at: string }[]>(
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
  exportPdfUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/export/pdf`,

  // ── 知识库 ──
  archiveProject: (projectId: string) =>
    request<{ project_id: string; chunks: number; status: string }>(`/projects/${projectId}/archive`, { method: 'POST' }),

  // ── 附件 ──
  listAttachments: (projectId: string) =>
    request<import('@/types/api').Attachment[]>(`/projects/${projectId}/attachments`),

  uploadAttachment: async (sectionId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    const res = await authFetch(`/sections/${sectionId}/attachments`, {
      method: 'POST',
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

  // ── 附图生成（drawio 渲染）──
  generateFigure: (
    sectionId: string,
    body: { prompt: string; diagram_type?: string | null; chat_source?: string | null; style?: string | null },
  ) =>
    request<import('@/types/api').Figure>(`/sections/${sectionId}/figures/generate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  listFigures: (projectId: string) =>
    request<import('@/types/api').Figure[]>(`/projects/${projectId}/figures`),

  getFigure: (figureId: string) =>
    request<import('@/types/api').FigureDetail>(`/figures/${figureId}`),

  regenerateFigure: (
    figureId: string,
    body: { prompt?: string; chat_source?: string | null; style?: string | null },
  ) =>
    request<import('@/types/api').Figure>(`/figures/${figureId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  deleteFigure: (figureId: string) =>
    request<void>(`/figures/${figureId}`, { method: 'DELETE' }),

  // ── 附图风格预设（admin console）──
  getFigurePresets: () =>
    request<{ presets: Record<string, import('@/types/api').FigurePreset> }>(
      '/admin/console/figure-presets',
    ),

  setFigurePreset: (
    presetId: string,
    body: { font_family?: string; font_size?: number; line_width?: number },
  ) =>
    request<import('@/types/api').FigurePreset>(
      `/admin/console/figure-presets/${presetId}`,
      { method: 'PUT', body: JSON.stringify(body) },
    ),

  // ── HITL 工具确认配置（admin console）──
  getHitlConfig: () =>
    request<{ enabled: boolean; tools: string[] }>('/admin/console/hitl'),

  setHitlConfig: (body: { enabled: boolean; tools: string[] }) =>
    request<{ enabled: boolean; tools: string[] }>('/admin/console/hitl', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  // ── Vision 模型名单配置（admin console）──
  getVisionMarkers: () =>
    request<{ enabled: boolean; extra_markers: string[] }>('/admin/console/vision-markers'),

  setVisionMarkers: (body: { enabled: boolean; extra_markers: string[] }) =>
    request<{ enabled: boolean; extra_markers: string[] }>('/admin/console/vision-markers', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  // ── 审查 ──
  runReview: (projectId: string) =>
    request<import('@/types/api').ReviewRecord>(`/projects/${projectId}/review`, { method: 'POST' }),
  listReviews: (projectId: string) =>
    request<import('@/types/api').ReviewRecord[]>(`/projects/${projectId}/reviews`),
  getReviewTrend: (projectId: string) =>
    request<import('@/types/api').ReviewTrendPoint[]>(`/projects/${projectId}/reviews/trend`),
  exportReviewReportUrl: (projectId: string, reviewId: string) =>
    `${BASE}/api/v1/projects/${projectId}/reviews/${reviewId}/export-pdf`,

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

  // ── 轻量任务模型配置（独立第三套；承接会话标题/章节摘要，默认 GLM-4.7-Flash）──
  /** GET /admin/lite-config 读取轻量任务模型配置（configured=false 表示当前回退 chat）。 */
  getLiteConfig: () =>
    request<import('@/types/api').LiteSettings>(`/admin/lite-config`),
  /**
   * 保存轻量任务模型配置（PUT /admin/lite-config）。
   * api_key 留空 = 不改（保留已存密钥）；lite_config 不传则仅写审计不改动。
   */
  setLiteConfig: (data: { lite_config?: { base_url?: string; api_key?: string; model?: string } }) =>
    request<import('@/types/api').LiteSettings>(`/admin/lite-config`, { method: 'PUT', body: JSON.stringify(data) }),
  /** admin 测试轻量任务模型连接。字段全可选：留空走当前已存的轻量配置复检。 */
  testLiteChat: (data: { base_url?: string; api_key?: string; model?: string }) =>
    request<TestConnectionResult>(`/admin/lite-config/test`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  /** admin 按 base_url + api_key 拉取轻量配置可用模型列表。 */
  listLiteModels: (data: {
    base_url: string
    api_key: string
    provider_template_id?: string | null
  }) =>
    request<ListModelsResult>(`/admin/lite-config/models`, {
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

  // ── 腾讯 ima 检索源（admin 全局配置）──
  /** 读全局 ima 配置（掩码）。 */
  getIMAConfig: () =>
    request<IMASettings>('/admin/console/ima'),
  /** 写全局 ima 配置（client_id/api_key 留空=不改）。 */
  setIMAConfig: (payload: IMAConfigPayload) =>
    request<{ ok: true }>('/admin/console/ima', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  /** 测试 ima 检索连通性（不落库）。 */
  testIMAConfig: (data: { client_id: string; api_key: string }) =>
    request<IMATestResult>('/admin/console/ima/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

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
    const res = await authFetch('/knowledge/upload', {
      method: 'POST', body: form,
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
    const res = await authFetch('/admin/knowledge/upload', {
      method: 'POST', body: form,
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

  // ── 经授权临时查看（§8.3：一次性授权码 + admin 限时只读）──
  listSupportCodes: (projectId: string) =>
    request<import('@/types/api').SupportCode[]>(`/projects/${projectId}/support-codes`),

  createSupportCode: (projectId: string, data: { ttl_minutes?: number }) =>
    request<import('@/types/api').SupportCode>(`/projects/${projectId}/support-codes`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  revokeSupportCode: (projectId: string, codeId: string) =>
    request<void>(`/projects/${projectId}/support-codes/${codeId}`, { method: 'DELETE' }),

  /** admin 凭码核销（一次性）→ 返回项目只读视图 + 30 分钟查看窗口。 */
  redeemSupportCode: (code: string) =>
    request<import('@/types/api').SupportView>('/admin/support-codes/redeem', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  /** admin 查看窗口内重复查看（仅核销该码的 admin）。 */
  viewSupportProject: (code: string) =>
    request<import('@/types/api').SupportView>(`/admin/support-codes/${code}/view`),

  getSharedInfo: (token: string) =>
    request<SharedInfo>(`/shared/${token}`),

  // 游客浏览：凭分享 token 取项目全篇章节（只读，图片已 inline 为 data URI）
  getSharedProject: (token: string) =>
    request<SharedProject>(`/shared/${token}/sections`),

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
    const res = await authFetch('/admin/skills/import-zip', {
      method: 'POST',
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
    const res = await authFetch('/skills/mine/import-zip', {
      method: 'POST',
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

  // ── 写作画像（/settings/profile）──
  getWritingProfile: () =>
    request<WritingProfile>('/settings/profile'),
  updateWritingProfile: (data: WritingProfileUpdate) =>
    request<WritingProfile>('/settings/profile', { method: 'PUT', body: JSON.stringify(data) }),

  // ── 专利检索（prior art search）──
  searchPatents: (projectId: string, query: string) =>
    request<PatentSearchResponse>(`/projects/${projectId}/patents/search`, {
      method: 'POST',
      body: JSON.stringify({ query }),
    }),
  getPatents: (projectId: string) =>
    request<PriorArtRefs | null>(`/projects/${projectId}/patents`),
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
 * - thinking：模型思考过程片段 {text}（GLM/DeepSeek reasoning_content，流式分块）
 * - tool_call：agent 发起工具调用 {name, args}
 * - tool_result：工具返回 {name, result}（result 已截断 500 字符）
 * - heartbeat：保活心跳，忽略
 * - done：完成 {message_id, conversation_id?, title?}，触发 onDone 回调
 * - error：服务端错误 {code, message}，抛出 ApiError 让上层走 catch 分支
 *
 * thinking / tool_call / tool_result 是 agent 透明化事件（类 zcode），
 * 通过 agentHandlers 可选回调上抛；不传则忽略（向后兼容旧调用方）。
 *
 * 原实现只看 data.text，导致 error 事件被静默吞掉（用户看到"空回复+无报错"）。
 */
async function _consumeSSE<TDone = { message_id: string; conversation_id?: string; title?: string | null }>(
  res: Response,
  onToken: (t: string) => void,
  onDone?: (data: TDone) => void,
  agentHandlers?: AgentStreamHandlers,
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
      } else if (eventType === 'thinking') {
        const text = data.text as string | undefined
        if (text) agentHandlers?.onThinking?.(text)
      } else if (eventType === 'tool_call') {
        agentHandlers?.onToolCall?.({ name: String(data.name ?? ''), args: (data.args as Record<string, unknown>) ?? {} })
      } else if (eventType === 'tool_result') {
        agentHandlers?.onToolResult?.({ name: String(data.name ?? ''), result: String(data.result ?? '') })
      } else if (eventType === 'interrupt') {
        // HITL 工具确认：流到此结束（无 done），用户决策后走 streamResume
        agentHandlers?.onInterrupt?.({
          message_id: (data.message_id as string | null) ?? null,
          thread_id: String(data.thread_id ?? ''),
          actions: (data.actions as { name: string; args: Record<string, unknown>; description?: string }[]) ?? [],
        })
      } else if (eventType === 'done' && onDone) {
        // done 事件：透传元数据（message_id / conversation_id / title / content 等）
        onDone(data as TDone)
      }
      // heartbeat：忽略
    }
  }
}
