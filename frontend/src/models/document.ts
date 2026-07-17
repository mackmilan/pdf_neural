import type { Field } from './field'

export interface NeuralTable {
  page: number
  confidence: number
  row_count?: number
  column_count?: number
}

export interface DocumentVersion {
  version: number
  is_current: boolean
  deprecated: boolean
}

export interface DocumentMetadata {
  filename?: string
  pdf_url?: string
}

export interface DocumentHistoryItem {
  document_id?: string
  job_id: string
  group_id?: string | null
  category_id?: string | null
  single_submission_per_user?: boolean
  allow_document_page_submission?: boolean
  current_version?: number
  version?: number
  created_at: string
  metadata?: DocumentMetadata
  fields: unknown[]
  tables: unknown[]
}

export interface HistoryResponse {
  items: DocumentHistoryItem[]
  page: number
  total_pages: number
  total: number
}

export type FormatNorm = 'abnt' | 'apa'

export interface DocumentResult {
  job_id?: string
  document_id?: string
  version?: number
  category_id?: string | null
  format_norm?: FormatNorm | null
  single_submission_per_user?: boolean
  allow_document_page_submission?: boolean
  metadata?: DocumentMetadata
  filename?: string
  fields: Field[]
  neural_tables?: NeuralTable[]
  preview?: string
  preview_url?: string
  result?: DocumentResult
  [key: string]: unknown
}

export interface AvailableDocument {
  document_id?: string
  job_id?: string
  current_job_id?: string
  current_version?: number
  version?: number
  tenant_id?: string
  group_id?: string | null
  category_id?: string | null
  updated_at?: string
  created_at?: string
  metadata?: DocumentMetadata
  fields?: unknown[]
}
