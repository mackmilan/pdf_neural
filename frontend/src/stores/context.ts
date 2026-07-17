import { defineStore } from 'pinia'
import { useAuthStore } from './auth'
import type { Category, DocumentHistoryItem, Group, HistoryResponse, Tenant } from '../types'

const TENANT_KEY = 'pdf-neural-tenant'
const GROUP_KEY = 'pdf-neural-group'
const CATEGORY_KEY = 'pdf-neural-category'
const HISTORY_PAGE_SIZE = 10

export const useContextStore = defineStore('context', {
  state: () => ({
    tenants: [] as Tenant[],
    groups: [] as Group[],
    categories: [] as Category[],
    tenantId: '' as string,
    groupId: '' as string,
    categoryId: '' as string,
    status: '' as string,
    historyItems: [] as DocumentHistoryItem[],
    historyPage: 1,
    historyTotalPages: 1,
    historyTotal: 0,
    historyNameFilter: '' as string,
    historyError: '' as string,
    historyLoaded: false,
  }),
  getters: {
    searchParams(state): URLSearchParams {
      const params = new URLSearchParams({ tenant_id: state.tenantId })
      if (state.groupId) params.set('group_id', state.groupId)
      if (state.categoryId) params.set('category_id', state.categoryId)
      return params
    },
  },
  actions: {
    async loadTenants() {
      const auth = useAuthStore()
      try {
        const response = await auth.apiFetch('/api/tenants')
        const data = await response.json()
        if (!response.ok) throw new Error(data.error)
        this.tenants = data
        const saved = localStorage.getItem(TENANT_KEY) || ''
        this.tenantId = data.some((tenant: Tenant) => tenant.tenant_id === saved) ? saved : ''
        await this.loadGroups(localStorage.getItem(GROUP_KEY) || '')
        await this.loadCategories(localStorage.getItem(CATEGORY_KEY) || '')
      } catch (error) {
        this.status = 'Erro ao carregar tenants: ' + (error as Error).message
        await this.loadHistory()
      }
    },
    async loadGroups(preferredGroup: string) {
      const auth = useAuthStore()
      this.groups = []
      if (!this.tenantId) {
        await this.loadHistory()
        return
      }
      const response = await auth.apiFetch(`/api/tenants/${encodeURIComponent(this.tenantId)}/groups`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      this.groups = data
      this.groupId = preferredGroup && data.some((group: Group) => group.group_id === preferredGroup)
        ? preferredGroup
        : auth.isAdmin
          ? ''
          : data[0]?.group_id || ''
      localStorage.setItem(TENANT_KEY, this.tenantId)
      localStorage.setItem(GROUP_KEY, this.groupId)
      await this.loadHistory()
    },
    async loadCategories(preferredCategory: string) {
      const auth = useAuthStore()
      this.categories = []
      if (!this.tenantId || !this.groupId) {
        localStorage.removeItem(CATEGORY_KEY)
        await this.loadHistory()
        return
      }
      const response = await auth.apiFetch(
        `/api/tenants/${encodeURIComponent(this.tenantId)}/groups/${encodeURIComponent(this.groupId)}/categories`,
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      this.categories = data
      this.categoryId = preferredCategory && data.some((category: Category) => category.category_id === preferredCategory)
        ? preferredCategory
        : ''
      localStorage.setItem(CATEGORY_KEY, this.categoryId)
      await this.loadHistory()
    },
    async onTenantChange() {
      this.historyPage = 1
      localStorage.setItem(TENANT_KEY, this.tenantId)
      localStorage.removeItem(GROUP_KEY)
      localStorage.removeItem(CATEGORY_KEY)
      await this.loadGroups('')
      await this.loadCategories('')
    },
    async onGroupChange() {
      this.historyPage = 1
      localStorage.setItem(GROUP_KEY, this.groupId)
      localStorage.removeItem(CATEGORY_KEY)
      await this.loadCategories('')
    },
    async onCategoryChange() {
      this.historyPage = 1
      localStorage.setItem(CATEGORY_KEY, this.categoryId)
      await this.loadHistory()
    },
    async createTenant(name: string) {
      const auth = useAuthStore()
      const response = await auth.apiFetch('/api/tenants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      localStorage.setItem(TENANT_KEY, data.tenant_id)
      await this.loadTenants()
      return data
    },
    async createGroup(name: string) {
      const auth = useAuthStore()
      const response = await auth.apiFetch(`/api/tenants/${encodeURIComponent(this.tenantId)}/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      await this.loadGroups(data.group_id)
      return data
    },
    async createCategory(name: string) {
      const auth = useAuthStore()
      const response = await auth.apiFetch(
        `/api/tenants/${encodeURIComponent(this.tenantId)}/groups/${encodeURIComponent(this.groupId)}/categories`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) },
      )
      const data = await response.json()
      if (!response.ok) throw new Error(data.error)
      await this.loadCategories(data.category_id)
      return data
    },
    async loadHistory(): Promise<void> {
      const auth = useAuthStore()
      if (!this.tenantId) {
        this.historyItems = []
        this.historyLoaded = false
        return
      }
      try {
        const params = this.searchParams
        params.set('page', String(this.historyPage))
        params.set('page_size', String(HISTORY_PAGE_SIZE))
        if (this.historyNameFilter.trim()) params.set('name', this.historyNameFilter.trim())
        const response = await auth.apiFetch(`/api/documents?${params}`)
        const data: HistoryResponse & { error?: string } = await response.json()
        if (!response.ok) throw new Error(data.error || 'Não foi possível carregar os documentos.')
        if (this.historyPage > Math.max(1, data.total_pages)) {
          this.historyPage = Math.max(1, data.total_pages)
          return this.loadHistory()
        }
        this.historyItems = data.items
        this.historyTotalPages = Math.max(1, data.total_pages)
        this.historyTotal = data.total
        this.historyLoaded = true
        this.historyError = ''
      } catch (error) {
        this.historyLoaded = true
        this.historyError = (error as Error).message
        this.historyItems = []
      }
    },
    groupName(groupId: string | null | undefined): string {
      if (!groupId) return 'Sem grupo'
      return this.groups.find((group) => group.group_id === groupId)?.name || 'Outro grupo'
    },
    categoryName(categoryId: string | null | undefined): string {
      if (!categoryId) return 'Sem categoria'
      return this.categories.find((category) => category.category_id === categoryId)?.name || 'Sem categoria'
    },
  },
})
