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
