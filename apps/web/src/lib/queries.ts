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
