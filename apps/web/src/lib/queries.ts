'use client'

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'
import type {
  KnowledgeFile,
  KnowledgeReview,
  Memory,
  Project,
  ProjectCreate,
  Section,
  Skill,
  SkillCreate,
  SkillUpdate,
  WritingProfile,
  WritingProfileUpdate,
  Tag,
  TagCreate,
  TagMerge,
  TemplateSummary,
  InviteCode,
  TermEntry,
} from '@/types/api'

export const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
  attachments: (projectId: string) => ['attachments', projectId] as const,
  tags: ['tags'] as const,
  knowledgePersonal: ['knowledge', 'personal'] as const,
  knowledgeGlobal: ['knowledge', 'global'] as const,
  knowledgeJobs: ['knowledge', 'ingest-jobs'] as const,
  knowledgeJob: (id: string) => ['knowledge', 'ingest-jobs', id] as const,
  reviews: ['reviews'] as const,
  members: (projectId: string) => ['members', projectId] as const,
  shareLinks: (projectId: string) => ['share-links', projectId] as const,
  messages: (sectionId: string, conversationId?: string) =>
    ['messages', sectionId, conversationId ?? null] as const,
  skills: {
    all: ['skills'] as const,
    visible: ['skills', 'visible'] as const,
    mine: ['skills', 'mine'] as const,
    admin: ['skills', 'admin'] as const,
    detail: (id: string) => ['skills', 'detail', id] as const,
  },
  // 内置 LLM provider 模板（静态数据）。模型拉取/测试连接是命令式动作，用 mutation，不进 queryKeys。
  llmTemplates: ['llm-templates'] as const,
  // admin 域（refactor/admin-ia-phase1 切片 1）。all 用于一刀切失效所有 admin 缓存。
  admin: {
    all: ['admin'] as const,
    users: ['admin', 'users'] as const,
    userDetail: (id: string) => ['admin', 'users', id] as const,
    // Console 域（refactor/admin-ia-phase2 切片 2）
    llmConfig: ['admin', 'llm-config'] as const,
    // 轻量任务模型配置（会话标题/章节摘要，默认 GLM-4.7-Flash）
    liteConfig: ['admin', 'lite-config'] as const,
    // MinerU 配置（PDF→Markdown 解析）
    mineruConfig: ['admin', 'mineru-config'] as const,
    // ima 检索源配置（腾讯 ima 知识库全局检索源）
    imaConfig: ['admin', 'ima-config'] as const,
    // MCP server 配置（stdio/http/sse）
    mcpServers: ['admin', 'mcp-servers'] as const,
    mcpEnabled: ['admin', 'mcp-enabled'] as const,
    llmStats: (days: number) => ['admin', 'llm-stats', days] as const,
    // LLM 余额告警（探测结果 + 阈值）
    llmBalance: ['admin', 'llm-balance'] as const,
    auditLogs: (page: number, size: number) =>
      ['admin', 'audit-logs', page, size] as const,
    // 内置模板管理（refactor/admin-ia-phase3 切片 B）
    adminTemplates: ['admin', 'content', 'templates'] as const,
    // 邀请码管理（内部产品化）
    invites: ['admin', 'invites'] as const,
    // G4 分块可视化干预：某文件的 chunks 列表。id=null 时无效（hook 会 enabled:false）
    fileChunks: (id: string | null) => ['admin', 'fileChunks', id] as const,
  },
  // 初始化助手顶层会话（ChatGPT 式对话页）
  assistant: {
    conversations: ['assistant', 'conversations'] as const,
    conversation: (id: string) => ['assistant', 'conversations', id] as const,
  },
}

// ── 项目 ──
export function useProjects(status?: string) {
  return useQuery<Project[]>({
    queryKey: status ? [...queryKeys.projects, { status }] : queryKeys.projects,
    queryFn: () => (status ? api.listProjectsFiltered({ status }) : api.listProjects()),
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ProjectCreate) => api.createProject(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useProject(projectId: string) {
  return useQuery<Project>({
    queryKey: queryKeys.project(projectId),
    queryFn: () => api.getProject(projectId),
    enabled: !!projectId,
  })
}

export function useArchiveProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.archiveProject(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useUpdateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: { title?: string; metadata?: Record<string, unknown> | null } }) =>
      api.updateProject(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

// ── 用户 ──
export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    retry: false,
  })
}

// ── 模板 ──
export function useTemplates() {
  return useQuery<TemplateSummary[]>({
    queryKey: queryKeys.templates,
    queryFn: api.listTemplates,
    // 路由切回 /templates 时无条件 refetch，绕过全局 staleTime=30s 限制。
    // 解决「admin 上线模板后，普通用户切走再切回仍看不到」——必须刷新才生效的问题。
    // 全局 refetchOnWindowFocus=false 不够：用户在同一 tab 内路由切换不会触发它。
    refetchOnMount: 'always',
  })
}

export function useTemplate(id: string) {
  return useQuery<import('@/types/api').Template>({
    queryKey: ['templates', id],
    queryFn: () => api.getTemplate(id),
    enabled: !!id,
  })
}

// ── 章节 ──
export function useSections(projectId: string) {
  return useQuery<Section[]>({
    queryKey: queryKeys.sections(projectId),
    queryFn: () => api.listSections(projectId),
    enabled: !!projectId,
  })
}

export function useUpdateSection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      content,
      status,
      expected_version,
    }: {
      id: string
      content?: object
      status?: string
      expected_version?: number
    }) => api.updateSection(id, { content, status, expected_version }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sections'] }),
  })
}

// ── 附件 ──
export function useAttachments(projectId: string) {
  return useQuery({
    queryKey: queryKeys.attachments(projectId),
    queryFn: () => api.listAttachments(projectId),
    enabled: !!projectId,
  })
}

export function useDeleteAttachment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAttachment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['attachments'] }),
  })
}

// ── 标签 ──
export function useTags() {
  return useQuery<Tag[]>({
    queryKey: queryKeys.tags,
    queryFn: api.listTags,
  })
}

export function useCreateTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TagCreate) => api.createTag(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.tags }),
  })
}

export function useRenameTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.renameTag(id, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.tags }),
  })
}

export function useDeleteTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteTag(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tags })
      qc.invalidateQueries({ queryKey: queryKeys.projects })
    },
  })
}

export function useMergeTags() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: TagMerge) => api.mergeTags(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.tags })
      qc.invalidateQueries({ queryKey: queryKeys.projects })
    },
  })
}

export function useAttachProjectTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, tagId }: { projectId: string; tagId: string }) =>
      api.attachProjectTag(projectId, tagId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

export function useDetachProjectTag() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ projectId, tagId }: { projectId: string; tagId: string }) =>
      api.detachProjectTag(projectId, tagId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.projects }),
  })
}

// ── 知识库(三域)──
// 有未完成向量化的文件（pending/processing/failed）时每 3s 轮询，推进进度展示；
// 全部 ready 则停止轮询（省请求）。plan async-knowledge-upload。
function _hasPendingFiles(files: KnowledgeFile[] | undefined): boolean {
  return !!files?.some((f) => f.status !== 'ready')
}

export function usePersonalKnowledge() {
  return useQuery<KnowledgeFile[]>({
    queryKey: queryKeys.knowledgePersonal,
    queryFn: () => api.listPersonalKnowledge(),
    refetchInterval: (query) => (_hasPendingFiles(query.state.data) ? 3000 : false),
  })
}

export function useGlobalKnowledge() {
  return useQuery<KnowledgeFile[]>({
    queryKey: queryKeys.knowledgeGlobal,
    queryFn: () => api.listGlobalKnowledge(),
    refetchInterval: (query) => (_hasPendingFiles(query.state.data) ? 3000 : false),
  })
}

export function useUploadKnowledgeFile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadKnowledgeFile(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.knowledgePersonal }),
  })
}

export function useAdminUploadGlobal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.adminUploadGlobal(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.knowledgeGlobal }),
  })
}

export function useDeleteGlobalKnowledge() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => api.deleteGlobalKnowledge(fileId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.knowledgeGlobal })
    },
  })
}

export function useSubmitKnowledgeReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => api.submitKnowledgeReview(fileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.knowledgePersonal }),
  })
}

// ── 网页摄入(Firecrawl)──
export function useIngestWeb() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').WebIngestRequest) => api.ingestWeb(payload),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: queryKeys.knowledgeJobs })
      if (data.kind === 'file') {
        qc.invalidateQueries({
          queryKey: data.file.scope === 'global'
            ? queryKeys.knowledgeGlobal
            : queryKeys.knowledgePersonal,
        })
      }
    },
  })
}

export function useIngestJobs() {
  return useQuery<import('@/types/api').WebIngestJob[]>({
    queryKey: queryKeys.knowledgeJobs,
    queryFn: () => api.listIngestJobs(),
    refetchInterval: (query) => {
      const jobs = query.state.data
      const hasActive = jobs?.some(
        (j) => j.status === 'pending' || j.status === 'running',
      )
      return hasActive ? 5000 : false
    },
  })
}

/**
 * G2 检索测试。命令式触发——按需检索，不进 queryKeys 缓存。
 * mutation 内只做逻辑/invalidate，不弹 toast（queries.ts:480-482 约定）。
 */
export function useRetrievalTest() {
  return useMutation({
    mutationFn: (payload: { query: string; top_k?: number; scope?: 'global' | 'personal' | null }) =>
      api.retrievalTest(payload),
  })
}

// ── 知识库审核(admin)──
export function usePendingReviews() {
  return useQuery<KnowledgeReview[]>({
    queryKey: queryKeys.reviews,
    queryFn: () => api.listPendingReviews(),
  })
}

export function useApproveReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (reviewId: string) => api.approveReview(reviewId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.reviews })
      qc.invalidateQueries({ queryKey: queryKeys.knowledgeGlobal })
    },
  })
}

export function useRejectReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ reviewId, comment }: { reviewId: string; comment?: string }) =>
      api.rejectReview(reviewId, comment),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.reviews }),
  })
}

// ── Diff（计划 16）──

/**
 * 计算差异：传入 AI 生成的 markdown 文本，返回 hunks。
 * 纯计算接口，不在 onSuccess 里做任何 UI 副作用——
 * onSuccess 回调里拿到 hunks 后由调用方决定如何展示。
 */
export function useComputeDiff(sectionId: string) {
  return useMutation({
    mutationFn: (aiText: string) => api.computeDiff(sectionId, aiText),
  })
}

/**
 * 应用 diff。成功后失效 sections 缓存（apply-diff 改写了章节内容，版本号变化）。
 */
export function useApplyDiff(sectionId: string, projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { ai_text: string; accepted_hunk_ids: string[]; expected_version: number }) =>
      api.applyDiff(sectionId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.sections(projectId) })
    },
  })
}

/**
 * 选区重写 diff：传入选区原文 + AI 重写文本，返回 hunks。
 * 纯计算接口（不改库），与 useComputeDiff 一致不在 onSuccess 里做 UI 副作用——
 * 调用方拿到 hunks 后自行决定如何展示。
 */
export function useRewriteDiff(sectionId: string) {
  return useMutation({
    mutationFn: (data: { selected_text: string; ai_text: string }) =>
      api.rewriteDiff(sectionId, data),
  })
}

// ── 协作（计划 17）──

export function useMembers(projectId: string) {
  return useQuery({
    queryKey: queryKeys.members(projectId),
    queryFn: () => api.listMembers(projectId),
    enabled: !!projectId,
  })
}

export function useAddMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (email: string) => api.addMember(projectId, email),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.members(projectId) }),
  })
}

export function useRemoveMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (memberId: string) => api.removeMember(projectId, memberId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.members(projectId) }),
  })
}

export function useShareLinks(projectId: string) {
  return useQuery({
    queryKey: queryKeys.shareLinks(projectId),
    queryFn: () => api.listShareLinks(projectId),
    enabled: !!projectId,
  })
}

export function useCreateShareLink(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { permissions: 'comment' | 'readonly'; expires_days?: number | null }) =>
      api.createShareLink(projectId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.shareLinks(projectId) }),
  })
}

export function useRevokeShareLink(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (linkId: string) => api.revokeShareLink(projectId, linkId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.shareLinks(projectId) }),
  })
}

// ── AI 对话记录 ──

export function useMessages(sectionId: string, conversationId?: string) {
  return useQuery({
    queryKey: queryKeys.messages(sectionId, conversationId),
    queryFn: () => api.listMessages(sectionId, conversationId),
    // 无 conversationId 不查询（后端已强制要求，避免 422 噪音）
    enabled: !!conversationId,
  })
}

// ── AI 会话 ──

export function useConversations(sectionId: string) {
  return useQuery({
    queryKey: ['conversations', sectionId] as const,
    queryFn: () => api.listConversations(sectionId),
  })
}

export function useCreateConversation(sectionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => api.createConversation(sectionId, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations', sectionId] }),
  })
}

export function useDeleteConversation(sectionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (conversationId: string) => api.deleteConversation(sectionId, conversationId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conversations', sectionId] }),
  })
}

// ── Admin：用户管理（refactor/admin-ia-phase1 切片 1）──
// 注：本组 hook 与项目其它 hook 一致，mutation 内部只做缓存失效，
// 不在 onSuccess/onError 里弹 toast——toast 由调用方处理（参考 review-workbench.tsx）。

import type { AdminUser, UserDetail } from '@/types/api'

/** 用户列表。 */
export function useUsers() {
  return useQuery<AdminUser[]>({
    queryKey: queryKeys.admin.users,
    queryFn: () => api.listUsers(),
  })
}

/** 单用户详情。 */
export function useUserDetail(userId: string) {
  return useQuery<UserDetail>({
    queryKey: queryKeys.admin.userDetail(userId),
    queryFn: () => api.getUserDetail(userId),
    enabled: !!userId,
  })
}

/** 封禁/解禁。onSuccess 同时失效列表 + 该用户详情缓存。 */
export function useBanUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, status }: { userId: string; status: 'active' | 'disabled' }) =>
      api.banUser(userId, status),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.users })
      qc.invalidateQueries({ queryKey: queryKeys.admin.userDetail(vars.userId) })
    },
  })
}

/** 授权使用全局 Key。grant/revoke 都一刀切失效 admin 缓存（统计/列表/详情都受影响）。 */
export function useGrantGlobalLLM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.grantGlobalLLM(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.all }),
  })
}

/** 撤销全局 Key 授权。 */
export function useRevokeGlobalLLM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => api.revokeGlobalLLM(userId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.all }),
  })
}

/** 重置用户密码。仅失效该用户详情（密码不返字段，列表不显示）。 */
export function useResetUserPassword() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, newPassword }: { userId: string; newPassword: string }) =>
      api.resetUserPassword(userId, newPassword),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.userDetail(vars.userId) })
    },
  })
}

/** admin 直接创建用户（内部产品化：无需邀请码）。失效用户列表。 */
export function useCreateUser() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: import('@/types/api').AdminCreateUserRequest) => api.adminCreateUser(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.users }),
  })
}

// ── 邀请码管理（内部产品化）──

/** 邀请码列表。 */
export function useInvites() {
  return useQuery<InviteCode[]>({
    queryKey: queryKeys.admin.invites,
    queryFn: () => api.listInvites(),
  })
}

/** 生成邀请码。失效邀请码列表。 */
export function useCreateInvite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: import('@/types/api').InviteCodeCreate) => api.createInvite(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.invites }),
  })
}

/** 吊销邀请码。失效邀请码列表。 */
export function useRevokeInvite() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (inviteId: string) => api.revokeInvite(inviteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.invites }),
  })
}

// ── Admin：Console 域（refactor/admin-ia-phase2 切片 2）──
// LLM 配置 / 调用统计 / 审计日志。同样不在 hook 内 toast，由调用方处理。

import type {
  AuditLogPage,
  GlobalLLMSettings,
  LiteSettings,
  LLMStats,
} from '@/types/api'

/** 全局 LLM 配置（GET /admin/llm-config）。 */
export function useGlobalLLMConfig() {
  return useQuery<GlobalLLMSettings>({
    queryKey: queryKeys.admin.llmConfig,
    queryFn: () => api.getGlobalLLM(),
  })
}

/** 保存全局 LLM 配置（PUT /admin/llm-config）。失效配置缓存 + 审计（保存会写一条审计）。 */
export function useSaveGlobalLLM() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: {
      enabled: boolean
      chat_config?: { base_url?: string; api_key?: string; model?: string }
    }) => api.setGlobalLLM(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.llmConfig })
      // 保存会写审计日志（admin_service._audit action=set_global_llm）
      qc.invalidateQueries({ queryKey: ['admin', 'audit-logs'] })
    },
  })
}

// ── 轻量任务模型配置（会话标题/章节摘要，默认 GLM-4.7-Flash；未配回退 chat）──

/** 读取轻量任务模型配置（GET /admin/lite-config）。configured=false 表示当前回退 chat。 */
export function useLiteConfig() {
  return useQuery<LiteSettings>({
    queryKey: queryKeys.admin.liteConfig,
    queryFn: () => api.getLiteConfig(),
  })
}

/** 保存轻量任务模型配置（PUT /admin/lite-config）。失效配置缓存 + 审计。 */
export function useSaveLiteConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { lite_config?: { base_url?: string; api_key?: string; model?: string } }) =>
      api.setLiteConfig(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.liteConfig })
      qc.invalidateQueries({ queryKey: ['admin', 'audit-logs'] })
    },
  })
}

/** admin 测试轻量任务模型连接（POST /admin/lite-config/test）。留空走已存配置复检。 */
export function useTestLiteChat() {
  return useMutation({
    mutationFn: (data: { base_url?: string; api_key?: string; model?: string }) =>
      api.testLiteChat(data),
  })
}

/** admin 拉取轻量配置可用模型列表（POST /admin/lite-config/models）。 */
export function useListLiteModels() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      provider_template_id?: string | null
    }) => api.listLiteModels(data),
  })
}

// ── MinerU 全局配置（PDF→Markdown 解析）──
export function useMineruConfig() {
  return useQuery({
    queryKey: queryKeys.admin.mineruConfig,
    queryFn: () => api.getMineruConfig(),
  })
}

export function useSaveMineruConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').MineruConfigPayload) =>
      api.setMineruConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mineruConfig })
      qc.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
  })
}

export function useTestMineruConfig() {
  return useMutation({
    mutationFn: () => api.testMineruConfig(),
  })
}

// ── ima 检索源全局配置（腾讯 ima 知识库）──
export function useIMAConfig() {
  return useQuery({
    queryKey: queryKeys.admin.imaConfig,
    queryFn: () => api.getIMAConfig(),
  })
}

export function useSaveIMAConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').IMAConfigPayload) =>
      api.setIMAConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.imaConfig })
      qc.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
  })
}

// ── MCP server 配置（admin 全局，stdio/http/sse）──
export function useMcpServers() {
  return useQuery({
    queryKey: queryKeys.admin.mcpServers,
    queryFn: () => api.listMcpServers(),
  })
}

export function useMcpEnabled() {
  return useQuery({
    queryKey: queryKeys.admin.mcpEnabled,
    queryFn: () => api.getMcpEnabled(),
  })
}

export function useSaveMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').McpServerPayload) =>
      api.createMcpServer(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useUpdateMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Partial<import('@/types/api').McpServerPayload> }) =>
      api.updateMcpServer(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useDeleteMcpServer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMcpServer(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

export function useToggleMcpGlobal() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').McpGlobalEnabled) =>
      api.setMcpEnabled(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpEnabled })
    },
  })
}

export function useTestMcpServer() {
  return useMutation({
    mutationFn: (id: string) => api.testMcpServer(id),
  })
}

export function useImportMcpServers() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (json: object) => api.importMcpServers(json),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.mcpServers })
    },
  })
}

/** LLM 调用统计（GET /admin/stats/llm?days=）。 */
export function useLLMStats(days: number) {
  return useQuery<LLMStats>({
    queryKey: queryKeys.admin.llmStats(days),
    queryFn: () => api.listLLMStats(days),
  })
}

/** 审计日志分页（GET /admin/audit-logs?page=&size=）。 */
export function useAuditLogs(page: number, size: number) {
  return useQuery<AuditLogPage>({
    queryKey: queryKeys.admin.auditLogs(page, size),
    queryFn: () => api.listAuditLogs(page, size),
  })
}

// ── G4 分块可视化干预（Task 4.4）──
// admin 查看某文件的 chunks 列表，并可编辑单个 chunk 的
// content(keywords/questions)/weight/locked。编辑文本会触发后端重新 embed。

/** 某文件的 chunks 列表（GET /admin/knowledge/files/{file_id}/chunks）。 */
export function useFileChunks(fileId: string | null) {
  return useQuery<
    Awaited<ReturnType<typeof api.listChunks>>
  >({
    queryKey: queryKeys.admin.fileChunks(fileId),
    queryFn: () => api.listChunks(fileId!),
    enabled: !!fileId,
  })
}

/**
 * 编辑单 chunk（PATCH /admin/knowledge/chunks/{chunk_id}）。
 * 失效用 ['admin', 'fileChunks'] 前缀一刀切（编辑后精确的 fileId 维度难取，
 * 反正列表数据量小、重拉便宜）。mutation 内只 invalidate，不弹 toast（queries.ts 约定）。
 */
export function useUpdateChunk() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ chunkId, payload }: {
      chunkId: string
      payload: Parameters<typeof api.updateChunk>[1]
    }) => api.updateChunk(chunkId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'fileChunks'] }),
  })
}

// ── Admin：内置模板管理（refactor/admin-ia-phase3 切片 B）──

import type { TemplateStatus } from '@/types/api'

/** 系统模板列表（admin 视角，含 draft/offline）。 */
export function useAdminTemplates() {
  return useQuery<TemplateSummary[]>({
    queryKey: queryKeys.admin.adminTemplates,
    queryFn: () => api.listAdminTemplates(),
  })
}

/** 上传 admin 模板（docx）。onSuccess 失效列表，前端轮询 parse_job 状态。 */
export function useUploadAdminTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadAdminTemplate(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.adminTemplates }),
  })
}

/**
 * 改模板状态（状态机校验在后端 service 层）。
 * 同时失效 admin 列表 + 普通用户视角的 ['templates']，
 * 这样同 tab 内 admin 改完后切到 /templates 也能看到新状态。
 */
export function useSetAdminTemplateStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TemplateStatus }) =>
      api.setAdminTemplateStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.adminTemplates })
      qc.invalidateQueries({ queryKey: queryKeys.templates })
    },
  })
}

/**
 * 删除系统模板（published 必须先下线，后端拒删 409）。
 * 同步失效普通用户视角的 ['templates']（同 useSetAdminTemplateStatus）。
 */
export function useDeleteAdminTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAdminTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.adminTemplates })
      qc.invalidateQueries({ queryKey: queryKeys.templates })
    },
  })
}

// ── Agent Skills（spec 合规）──
export function useGlobalSkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.admin, queryFn: api.listGlobalSkills })
}

export function useCreateGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillCreate) => api.createGlobalSkill(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useUpdateGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillUpdate }) => api.updateGlobalSkill(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useDeleteGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteGlobalSkill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useVisibleSkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.visible, queryFn: api.listVisibleSkills })
}

export function useMySkills() {
  return useQuery<Skill[]>({ queryKey: queryKeys.skills.mine, queryFn: api.listMySkills })
}

export function useCreateMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SkillCreate) => api.createMySkill(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

export function useUpdateMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: SkillUpdate }) => api.updateMySkill(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

export function useDeleteMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMySkill(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

export function useImportGlobalSkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.importGlobalSkillZip(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.admin }),
  })
}

export function useImportMySkill() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.importMySkillZip(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills.mine }),
  })
}

// ── LLM provider 模板 / 模型拉取 / 测试连接（feat/llm-config-redesign）──

/**
 * 内置 provider 模板列表（选模板自动填 base_url/model）。
 * 静态数据：staleTime=Infinity，不主动刷新。
 */
export function useProviderTemplates() {
  return useQuery({
    queryKey: queryKeys.llmTemplates,
    queryFn: api.listProviderTemplates,
    staleTime: Infinity,
  })
}

/**
 * 按 base_url + api_key 拉取 provider 的可用模型列表。
 * 命令式动作（按需触发），用 mutation，不在 onSuccess 失效缓存。
 */
export function useListProviderModels() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      provider_template_id?: string | null
    }) => api.listProviderModels(data),
  })
}

/**
 * 测试用户 LLM 连接（chat 单测；embedding 走固定服务无需测）。
 * 命令式动作，用 mutation。
 */
export function useTestLLMConnection() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      model: string
    }) => api.testMyLLM(data),
  })
}

/**
 * admin 测试全局 chat 连接（POST /admin/llm-config/chat/test）。
 * 字段全可选：留空走当前已存 chat 配置复检。命令式动作，用 mutation。
 */
export function useTestGlobalChat() {
  return useMutation({
    mutationFn: (data: {
      base_url?: string
      api_key?: string
      model?: string
    }) => api.testGlobalChat(data),
  })
}

/**
 * admin 按 base_url + api_key 拉取 provider 的可用 chat 模型列表。
 * 命令式动作，用 mutation。
 */
export function useListGlobalChatModels() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      provider_template_id?: string | null
    }) => api.listGlobalChatModels(data),
  })
}

// ── 用户绑定长期记忆 ──

/** 当前用户的记忆列表。source 留空查全部。 */
export function useMemories(source?: 'agent' | 'manual') {
  return useQuery<Memory[]>({
    queryKey: ['memories', source],
    queryFn: () => api.listMemories(source),
  })
}

/** 新增记忆。成功后失效记忆列表。 */
export function useCreateMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { content: string; source?: 'agent' | 'manual' }) =>
      api.createMemory({ content: vars.content, source: vars.source }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}

/** 修改记忆内容。成功后失效记忆列表。 */
export function useUpdateMemory(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (content: string) => api.updateMemory(id, { content }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}

/** 删除记忆。成功后失效记忆列表。 */
export function useDeleteMemory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMemory(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['memories'] }),
  })
}

// ── 写作画像（/settings/profile，一对一 upsert）──

/** 读取当前用户写作画像。无记录时各字段为 null。 */
export function useWritingProfile() {
  return useQuery<WritingProfile>({
    queryKey: ['writing-profile'],
    queryFn: () => api.getWritingProfile(),
  })
}

/** 新建/更新写作画像（upsert）。成功后失效画像缓存。 */
export function useUpdateWritingProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: WritingProfileUpdate) => api.updateWritingProfile(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['writing-profile'] }),
  })
}

// ── 专利检索（prior art search）──

/** 读取已存的检索结果。无记录返回 null。 */
export function usePriorArt(projectId: string) {
  return useQuery({
    queryKey: ['patents', projectId],
    queryFn: () => api.getPatents(projectId),
    enabled: !!projectId,
  })
}

/** 执行专利检索。成功后失效缓存。 */
export function useSearchPatents(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (query: string) => api.searchPatents(projectId, query),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['patents', projectId] }),
  })
}

// ── 初始化助手顶层会话（ChatGPT 式对话页）──
export function useAssistantConversations() {
  return useQuery({
    queryKey: queryKeys.assistant.conversations,
    queryFn: () => api.listAssistantConversations(),
  })
}

export function useAssistantConversation(id: string | null) {
  return useQuery({
    queryKey: id ? queryKeys.assistant.conversation(id) : ['assistant', 'conversations', 'none'],
    queryFn: () => api.getAssistantConversation(id!),
    enabled: !!id,
  })
}

export function useCreateAssistantConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => api.createAssistantConversation(title),
    // exact:true：仅失效列表，不连带失效单会话详情（子 key），避免重拉覆盖本地流式状态。
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations, exact: true }),
  })
}

export function useDeleteAssistantConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteAssistantConversation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.assistant.conversations, exact: true }),
  })
}

/**
 * 失效 init 助手会话列表缓存。严格只失效列表，不连带失效单会话详情
 * （单会话 key 是列表的子 key：`['assistant','conversations',id]`）。
 * 误伤子 key 会触发单会话 refetch → 外层 effect 用服务端快照覆盖本地流式 messages，
 * 那正是「切对话丢最新消息」的根因（见 commit 2a36319）。
 *
 * 所有需要刷新 init 助手列表的调用点统一用这个 helper，把 `exact: true` 收敛进单一函数，
 * 杜绝新调用点漏写 flag 导致丢对话回归。
 */
export function useInvalidateAssistantList() {
  const qc = useQueryClient()
  return () => qc.invalidateQueries({
    queryKey: queryKeys.assistant.conversations,
    exact: true,
  })
}

// ── T2 项目术语表 ────────────────────────────────────────────────────────────

export function useTerms(projectId: string) {
  return useQuery<TermEntry[]>({
    queryKey: ['terms', projectId],
    queryFn: () => api.listTerms(projectId),
    enabled: !!projectId,
  })
}

export function useCreateTerm(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { term: string; definition?: string | null; variants?: string[]; source?: string }) =>
      api.createTerm(projectId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['terms', projectId] }),
  })
}

export function useUpdateTerm(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string; term?: string; definition?: string | null; variants?: string[]; enabled?: boolean }) =>
      api.updateTerm(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['terms', projectId] }),
  })
}

export function useDeleteTerm(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteTerm(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['terms', projectId] }),
  })
}
