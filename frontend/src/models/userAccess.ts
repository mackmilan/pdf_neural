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
