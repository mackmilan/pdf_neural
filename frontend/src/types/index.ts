export type FieldType =
  | 'text' | 'date' | 'time' | 'email' | 'tel' | 'number' | 'checkbox' | 'textarea' | 'select'

export type FieldAlign = 'left' | 'center' | 'justify' | 'right'

export interface Field {
  name: string
  label: string
  type: FieldType
  page: number
  x: number
  y: number
  width: number
  height: number
  align?: FieldAlign
  mask?: string
  required?: boolean
  min?: number
  max?: number
  source?: string
  [key: string]: unknown
}

export interface NeuralTable {
  page: number
  confidence: number
  row_count?: number
  column_count?: number
}

export interface Tenant {
  tenant_id: string
  name: string
}

export interface Group {
  group_id: string
  name: string
}

export interface Category {
  category_id: string
  name: string
}

export interface DocumentVersion {
  version: number
  is_current: boolean
  deprecated: boolean
}

export interface DocumentHistoryItem {
  document_id?: string
  job_id: string
  group_id?: string | null
  category_id?: string | null
  current_version?: number
  version?: number
  created_at: string
  metadata?: { filename?: string; pdf_url?: string }
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
  metadata?: { filename?: string }
  filename?: string
  fields: Field[]
  neural_tables?: NeuralTable[]
  preview?: string
  preview_url?: string
  result?: DocumentResult
  [key: string]: unknown
}

export interface AuthTokens {
  access_token: string
  refresh_token?: string
  id_token?: string
  [key: string]: unknown
}

export interface AuthConfig {
  issuer: string
  client_id: string
}

export interface ApiKeyInfo {
  client_id: string
  name: string
  created_at: string
}
