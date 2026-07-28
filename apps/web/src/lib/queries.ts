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
  Project,
  ProjectCreate,
  Section,
  Skill,
  SkillCreate,
  SkillUpdate,
  Tag,
  TagCreate,
  TagMerge,
  TemplateSummary,
  InviteCode,
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
    firecrawlConfig: ['admin', 'firecrawl-config'] as const,
    // G3 rerank 配置（混合检索精排）
    rerankConfig: ['admin', 'rerank-config'] as const,
    llmStats: (days: number) => ['admin', 'llm-stats', days] as const,
    auditLogs: (page: number, size: number) =>
      ['admin', 'audit-logs', page, size] as const,
    // 内置模板管理（refactor/admin-ia-phase3 切片 B）
    adminTemplates: ['admin', 'content', 'templates'] as const,
    // 邀请码管理（内部产品化）
    invites: ['admin', 'invites'] as const,
    // G4 分块可视化干预：某文件的 chunks 列表。id=null 时无效（hook 会 enabled:false）
    fileChunks: (id: string | null) => ['admin', 'fileChunks', id] as const,
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
export function usePersonalKnowledge() {
  return useQuery<KnowledgeFile[]>({
    queryKey: queryKeys.knowledgePersonal,
    queryFn: () => api.listPersonalKnowledge(),
  })
}

export function useGlobalKnowledge() {
  return useQuery<KnowledgeFile[]>({
    queryKey: queryKeys.knowledgeGlobal,
    queryFn: () => api.listGlobalKnowledge(),
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
      embedding_config?: { base_url?: string; api_key?: string; model?: string }
    }) => api.setGlobalLLM(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.llmConfig })
      // 保存会写审计日志（admin_service._audit action=set_global_llm）
      qc.invalidateQueries({ queryKey: ['admin', 'audit-logs'] })
    },
  })
}

// ── Firecrawl 全局配置(admin)──
export function useFirecrawlConfig() {
  return useQuery({
    queryKey: queryKeys.admin.firecrawlConfig,
    queryFn: () => api.getFirecrawlConfig(),
  })
}

export function useSaveFirecrawlConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: import('@/types/api').FirecrawlConfigPayload) =>
      api.setFirecrawlConfig(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.firecrawlConfig })
      qc.invalidateQueries({ queryKey: queryKeys.admin.all })
    },
  })
}

// ── G3 rerank 配置（混合检索精排模型配置）──
// 与 Firecrawl hooks 一致：mutation 内只做 invalidate，不弹 toast（组件层处理）。
export function useRerankConfig() {
  return useQuery({
    queryKey: queryKeys.admin.rerankConfig,
    queryFn: () => api.getRerankConfig(),
  })
}

export function useSaveRerankConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: { enabled: boolean; base_url: string; api_key: string; model: string }) =>
      api.saveRerankConfig(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.admin.rerankConfig }),
  })
}

/** 测试 rerank 连通性（命令式动作，用 mutation，不失效缓存）。 */
export function useTestRerankConfig() {
  return useMutation({
    mutationFn: (payload: { enabled: boolean; base_url: string; api_key: string; model: string }) =>
      api.testRerankConfig(payload),
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

// ── 用户自定义 embedding 配置（feat/llm-chat-embedding-split）──

import type { UserEmbeddingConfig } from '@/types/api'

/** 当前用户的自定义 embedding 配置列表（GET /settings/embedding）。 */
export function useMyEmbeddingConfigs() {
  return useQuery<UserEmbeddingConfig[]>({
    queryKey: ['my-embedding'],
    queryFn: () => api.listMyEmbeddingConfigs(),
  })
}

/** 新增 embedding 配置。成功后失效列表。 */
export function useCreateMyEmbeddingConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: import('@/types/api').UserEmbeddingConfigCreate) =>
      api.createMyEmbeddingConfig(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-embedding'] }),
  })
}

/** 修改 embedding 配置。成功后失效列表。 */
export function useUpdateMyEmbeddingConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: import('@/types/api').UserEmbeddingConfigUpdate }) =>
      api.updateMyEmbeddingConfig(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-embedding'] }),
  })
}

/** 删除 embedding 配置。成功后失效列表。 */
export function useDeleteMyEmbeddingConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteMyEmbeddingConfig(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['my-embedding'] }),
  })
}

/** 测试 embedding 连通性（命令式动作，用 mutation，不失效缓存）。 */
export function useTestMyEmbeddingConfig() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      model: string
    }) => api.testMyEmbeddingConfig(data),
  })
}

/** 按 base_url + api_key 拉取 provider 的可用 embedding 模型列表（命令式动作）。 */
export function useListMyEmbeddingModels() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      provider_template_id?: string | null
    }) => api.listMyEmbeddingModels(data),
  })
}

/**
 * 测试用户 LLM 连接（chat 单测；embedding 另有 useTestMyEmbeddingConfig）。
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
 * admin 测试全局 embedding 连接（POST /admin/llm-config/embedding/test）。
 * 字段全可选：留空走当前已存 embedding 配置复检。命令式动作，用 mutation。
 */
export function useTestGlobalEmbedding() {
  return useMutation({
    mutationFn: (data: {
      base_url?: string
      api_key?: string
      model?: string
    }) => api.testGlobalEmbedding(data),
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

/**
 * admin 按 base_url + api_key 拉取 provider 的可用 embedding 模型列表。
 * 命令式动作，用 mutation。
 */
export function useListGlobalEmbeddingModels() {
  return useMutation({
    mutationFn: (data: {
      base_url: string
      api_key: string
      provider_template_id?: string | null
    }) => api.listGlobalEmbeddingModels(data),
  })
}
