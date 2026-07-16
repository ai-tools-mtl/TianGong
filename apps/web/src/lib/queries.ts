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
