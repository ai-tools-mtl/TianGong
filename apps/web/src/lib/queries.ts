'use client'

import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { Project, ProjectCreate, Section, TemplateSummary } from '@/types/api'

export const queryKeys = {
  projects: ['projects'] as const,
  me: ['me'] as const,
  templates: ['templates'] as const,
  sections: (id: string) => ['sections', id] as const,
}

// ── 项目 ──
export function useProjects() {
  return useQuery<Project[]>({
    queryKey: queryKeys.projects,
    queryFn: api.listProjects,
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
    mutationFn: ({ id, content, status }: { id: string; content?: object; status?: string }) =>
      api.updateSection(id, { content, status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sections'] }),
  })
}
