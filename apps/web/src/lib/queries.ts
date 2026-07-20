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
  Tag,
  TagCreate,
  TagMerge,
  TemplateSummary,
} from '@/types/api'

export const queryKeys = {
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
  attachments: (projectId: string) => ['attachments', projectId] as const,
  skills: (id: string) => ['skills', id] as const,
  tags: ['tags'] as const,
  knowledgePersonal: ['knowledge', 'personal'] as const,
  knowledgeGlobal: ['knowledge', 'global'] as const,
  reviews: ['reviews'] as const,
  members: (projectId: string) => ['members', projectId] as const,
  shareLinks: (projectId: string) => ['share-links', projectId] as const,
  messages: (sectionId: string, conversationId?: string) =>
    ['messages', sectionId, conversationId ?? null] as const,
  // admin 域（refactor/admin-ia-phase1 切片 1）。all 用于一刀切失效所有 admin 缓存。
  admin: {
    all: ['admin'] as const,
    users: ['admin', 'users'] as const,
    userDetail: (id: string) => ['admin', 'users', id] as const,
    // Console 域（refactor/admin-ia-phase2 切片 2）
    llmConfig: ['admin', 'llm-config'] as const,
    llmStats: (days: number) => ['admin', 'llm-stats', days] as const,
    auditLogs: (page: number, size: number) =>
      ['admin', 'audit-logs', page, size] as const,
    // 内置模板管理（refactor/admin-ia-phase3 切片 B）
    adminTemplates: ['admin', 'content', 'templates'] as const,
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

// ── 技能 ──
export function useSkills(projectId: string) {
  return useQuery<import('@/types/api').AgentSkill[]>({
    queryKey: queryKeys.skills(projectId),
    queryFn: () => api.listSkills(projectId),
    enabled: !!projectId,
  })
}

export function useUpdateSkill(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ skillKey, enabled, config }: { skillKey: string; enabled: boolean; config?: object | null }) =>
      api.updateSkill(projectId, skillKey, { enabled, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.skills(projectId) }),
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

export function useSubmitKnowledgeReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => api.submitKnowledgeReview(fileId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.knowledgePersonal }),
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
      base_url?: string
      api_key?: string
      model?: string
      embedding_model?: string
      allowed_models?: string[]
    }) => api.setGlobalLLM(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.admin.llmConfig })
      // 保存会写审计日志（admin_service._audit action=set_global_llm）
      qc.invalidateQueries({ queryKey: ['admin', 'audit-logs'] })
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
