import { defineStore } from 'pinia'
import type { AuthConfig, AuthTokens } from '../types'

const STORAGE_KEY = 'pdf-neural-oidc'
const STATE_KEY = 'pdf-neural-oidc-state'
const VERIFIER_KEY = 'pdf-neural-pkce-verifier'
const ACCOUNT_SETUP_MESSAGE =
  'Sua conta precisa ser concluída no Keycloak antes de entrar por e-mail e senha.'

function decodeToken(token: string): Record<string, any> {
  try {
    const payload = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(
      decodeURIComponent(
        Array.from(atob(payload), (c) => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`).join(''),
      ),
    )
  } catch {
    return {}
  }
}

function randomValue(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(64))
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

async function sha256Challenge(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
  return btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function redirectUri(): string {
  return `${location.origin}${location.pathname}`
}

function normalizeAuthError(data: Record<string, any>): Error {
  const description = String(data.error_description || data.error || '')
  if (/account is not fully set up|required action|resolve required actions/i.test(description)) {
    const error = new Error(ACCOUNT_SETUP_MESSAGE)
    ;(error as Error & { accountSetupRequired?: boolean }).accountSetupRequired = true
    return error
  }
  return new Error(description || 'Não foi possível autenticar no Keycloak')
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    config: null as AuthConfig | null,
    tokens: null as AuthTokens | null,
    initialized: false,
    loginError: '' as string,
    accountSetupRequired: false,
    refreshTimer: null as ReturnType<typeof setTimeout> | null,
  }),
  getters: {
    claims(state): Record<string, any> {
      return state.tokens?.access_token ? decodeToken(state.tokens.access_token) : {}
    },
    isAuthenticated(state): boolean {
      if (!state.tokens?.access_token) return false
      const exp = Number(decodeToken(state.tokens.access_token).exp || 0)
      return exp > Date.now() / 1000 + 30
    },
    isAdmin(): boolean {
      const roles: string[] = this.claims.realm_access?.roles || []
      return roles.includes('pdf-admin')
    },
    displayName(): string {
      return this.claims.name || this.claims.preferred_username || 'Usuário autenticado'
    },
  },
  actions: {
    storeTokens(value: Partial<AuthTokens>) {
      this.tokens = { ...(this.tokens || {}), ...value } as AuthTokens
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(this.tokens))
      if (this.refreshTimer) clearTimeout(this.refreshTimer)
      const expiresAt = Number(decodeToken(this.tokens.access_token).exp || 0) * 1000
      this.refreshTimer = setTimeout(
        () => this.refreshSession().catch((error) => this.showLogin(error)),
        Math.max(1000, expiresAt - Date.now() - 60000),
      )
    },
    async exchangeToken(parameters: Record<string, string>) {
      if (!this.config) throw new Error('Configuração de autenticação não carregada')
      let response: Response
      try {
        response = await fetch(`${this.config.issuer}/protocol/openid-connect/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
          body: new URLSearchParams({ client_id: this.config.client_id, ...parameters }),
        })
      } catch {
        throw new Error(
          `Não foi possível acessar o Keycloak em ${this.config.issuer}. Verifique se ele está online e se a origem ${location.origin} está autorizada em Web Origins/Redirect URIs.`,
        )
      }
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw normalizeAuthError(data)
      this.storeTokens(data)
      return data
    },
    async refreshSession() {
      if (!this.tokens?.refresh_token) throw new Error('Sessão expirada')
      await this.exchangeToken({ grant_type: 'refresh_token', refresh_token: this.tokens.refresh_token })
    },
    async loginWithPassword(email: string, password: string) {
      this.loginError = ''
      this.accountSetupRequired = false
      if (!email.trim() || !password) throw new Error('Informe o e-mail e a senha.')
      await this.exchangeToken({
        grant_type: 'password',
        username: email.trim(),
        password,
        scope: 'openid profile email',
      })
    },
    async beginLogin() {
      if (!this.config) throw new Error('Configuração de autenticação não carregada')
      this.accountSetupRequired = false
      const verifier = randomValue()
      const state = randomValue()
      sessionStorage.setItem(VERIFIER_KEY, verifier)
      sessionStorage.setItem(STATE_KEY, state)
      const query = new URLSearchParams({
        client_id: this.config.client_id,
        redirect_uri: redirectUri(),
        response_type: 'code',
        scope: 'openid profile email',
        state,
        code_challenge: await sha256Challenge(verifier),
        code_challenge_method: 'S256',
      })
      location.assign(`${this.config.issuer}/protocol/openid-connect/auth?${query}`)
    },
    showLogin(error?: Error) {
      if (this.refreshTimer) clearTimeout(this.refreshTimer)
      this.tokens = null
      sessionStorage.removeItem(STORAGE_KEY)
      this.loginError = error?.message || 'Faça login para continuar.'
      this.accountSetupRequired = Boolean((error as Error & { accountSetupRequired?: boolean } | undefined)?.accountSetupRequired)
    },
    logout() {
      const idToken = this.tokens?.id_token
      const clientId = this.config?.client_id
      if (this.refreshTimer) clearTimeout(this.refreshTimer)
      this.tokens = null
      sessionStorage.removeItem(STORAGE_KEY)
      if (!this.config) return
      const query = new URLSearchParams({ client_id: clientId || '', post_logout_redirect_uri: redirectUri() })
      if (idToken) query.set('id_token_hint', idToken)
      location.assign(`${this.config.issuer}/protocol/openid-connect/logout?${query}`)
    },
    async apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
      if (!this.isAuthenticated) await this.refreshSession()
      const headers = new Headers(options.headers || {})
      headers.set('Authorization', `Bearer ${this.tokens!.access_token}`)
      let response: Response
      try {
        response = await fetch(url, { ...options, headers })
      } catch {
        throw new Error('Não foi possível acessar a API. Verifique se o servidor está online e se a URL da aplicação está correta.')
      }
      if (response.status === 401 && this.tokens?.refresh_token) {
        await this.refreshSession()
        headers.set('Authorization', `Bearer ${this.tokens.access_token}`)
        try {
          response = await fetch(url, { ...options, headers })
        } catch {
          throw new Error('Não foi possível acessar a API. Verifique se o servidor está online e se a URL da aplicação está correta.')
        }
      }
      return response
    },
    async initialize() {
      try {
        this.config = await fetch('/auth/config').then((response) => response.json())
        const query = new URLSearchParams(location.search)
        if (query.has('code')) {
          const expectedState = sessionStorage.getItem(STATE_KEY)
          const verifier = sessionStorage.getItem(VERIFIER_KEY)
          if (!expectedState || query.get('state') !== expectedState || !verifier) {
            throw new Error('Retorno de autenticação inválido')
          }
          await this.exchangeToken({
            grant_type: 'authorization_code',
            code: query.get('code')!,
            redirect_uri: redirectUri(),
            code_verifier: verifier,
          })
          sessionStorage.removeItem(STATE_KEY)
          sessionStorage.removeItem(VERIFIER_KEY)
          history.replaceState({}, document.title, location.pathname)
        } else {
          try {
            this.tokens = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || 'null')
          } catch {
            this.tokens = null
          }
          if (!this.isAuthenticated && this.tokens?.refresh_token) await this.refreshSession()
        }
        if (!this.isAuthenticated) {
          this.showLogin()
          return
        }
        this.storeTokens(this.tokens!)
      } catch (error) {
        this.showLogin(error as Error)
      } finally {
        this.initialized = true
      }
    },
  },
})
