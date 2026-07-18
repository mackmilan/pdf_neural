export interface SubmissionListItem {
  submission_id: string
  document_name: string
  document_id?: string
  job_id?: string
  version?: number
  created_at?: string
  email?: string
}

export interface AdminSubmission {
  submission_id: string
  document_name: string
  tenant_id?: string | null
  tenant_name?: string | null
  group_id?: string | null
  group_name?: string | null
  category_id?: string | null
  category_name?: string | null
  subject?: string
  username?: string | null
  email?: string | null
  created_at?: string
}

export interface SubmissionDetail {
  submission_id: string
  values: Record<string, unknown>
  created_at?: string
  subject?: string
  email?: string
}
