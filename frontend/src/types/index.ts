export type FieldType =
  | 'text' | 'date' | 'time' | 'email' | 'tel' | 'number' | 'checkbox' | 'radio' | 'textarea' | 'select'

export type FieldAlign = 'left' | 'center' | 'justify' | 'right'

export interface RadioOptionBox {
  value: string
  page: number
  x: number
  y: number
  width: number
  height: number
}

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
  options?: string[]
  option_boxes?: RadioOptionBox[]
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
  single_submission_per_user?: boolean
  allow_document_page_submission?: boolean
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
  single_submission_per_user?: boolean
  allow_document_page_submission?: boolean
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

export type UserPermission = 'reader' | 'editor'

export interface UserAccessEntry {
  subject: string
  username?: string | null
  tenant_id: string
  tenant_name?: string | null
  group_id?: string | null
  group_name?: string | null
  permission: UserPermission
  created_at?: string
  updated_at?: string
}

export interface UserAccessSummary {
  subject: string
  username?: string | null
  access: UserAccessEntry[]
}
