/**
 * KnowledgeFile.source_type 的中文 label 映射(共享)。
 *
 * 后端值(见 apps/api/app/services/knowledge_service.py 的 _source_type_for):
 * - external_pdf / external_docx:用户上传的 docx/pdf
 * - external_web:网页摄入(Firecrawl)
 * - disclosure_export:归档交底书导出
 *
 * 前端 Badge 直接显示 label,而非后端原值(如 external_web → 「网页」)。
 */
export const SOURCE_TYPE_LABELS: Record<string, string> = {
  external_pdf: 'PDF',
  external_docx: 'Word',
  external_web: '网页',
  disclosure_export: '归档',
  external_md: '网页', // 兼容(若后端 _source_type_for 退化到按扩展名)
}

/**
 * 取 source_type 的 label,未知值回退到原值。
 */
export function sourceTypeLabel(sourceType: string): string {
  return SOURCE_TYPE_LABELS[sourceType] ?? sourceType
}
