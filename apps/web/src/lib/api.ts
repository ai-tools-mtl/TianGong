import type {
  ApiError,
  LoginRequest,
  Project,
  ProjectCreate,
  ProjectUpdate,
  RegisterRequest,
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

  deleteTemplate: (id: string) =>
    request<void>(`/templates/${id}`, { method: 'DELETE' }),

  setDefaultTemplate: (id: string) =>
    request<import('@/types/api').TemplateSummary>(`/templates/${id}/default`, { method: 'POST' }),

  // ── 章节 ──
  listSections: (projectId: string) =>
    request<import('@/types/api').Section[]>(`/projects/${projectId}/sections`),

  getSection: (id: string) => request<import('@/types/api').Section>(`/sections/${id}`),

  updateSection: (id: string, data: { content?: object; status?: string }) =>
    request<import('@/types/api').Section>(`/sections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // ── AI（SSE 流式）──
  streamChat: async (sectionId: string, message: string, onToken: (t: string) => void) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
    return _consumeSSE(res, onToken)
  },

  streamGenerate: async (sectionId: string, onToken: (t: string) => void) => {
    const res = await fetch(`${BASE}/api/v1/sections/${sectionId}/generate`, {
      method: 'POST',
      credentials: 'include',
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
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const data = JSON.parse(line.slice(6))
          if (data.text) onToken(data.text)
        } catch {
          // 忽略解析失败的行
        }
      }
    }
  }
}
