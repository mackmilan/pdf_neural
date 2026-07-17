<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import type { Category, Group, Tenant } from '../types'

interface AdminSubmission {
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

const auth = useAuthStore()
const tenants = ref<Tenant[]>([])
const groups = ref<Group[]>([])
const categories = ref<Category[]>([])
const tenantId = ref('')
const groupId = ref('')
const categoryId = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const user = ref('')
const loading = ref(false)
const error = ref('')
const submissions = ref<AdminSubmission[]>([])

const hasFilters = computed(() => Boolean(
  tenantId.value || groupId.value || categoryId.value || dateFrom.value || dateTo.value || user.value.trim(),
))

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function parseJson<T>(response: Response, fallback: string): Promise<T> {
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new Error(data?.error || fallback)
  return data as T
}

async function loadTenants() {
  tenants.value = await parseJson<Tenant[]>(await auth.apiFetch('/api/tenants'), 'Não foi possível carregar tenants.')
}

async function loadGroups() {
  groups.value = []
  groupId.value = ''
  categories.value = []
  categoryId.value = ''
  if (!tenantId.value) return
  groups.value = await parseJson<Group[]>(
    await auth.apiFetch(`/api/tenants/${encodeURIComponent(tenantId.value)}/groups`),
    'Não foi possível carregar grupos.',
  )
}

async function loadCategories() {
  categories.value = []
  categoryId.value = ''
  if (!tenantId.value || !groupId.value) return
  categories.value = await parseJson<Category[]>(
    await auth.apiFetch(
      `/api/tenants/${encodeURIComponent(tenantId.value)}/groups/${encodeURIComponent(groupId.value)}/categories`,
    ),
    'Não foi possível carregar categorias.',
  )
}

function buildQuery(): string {
  const params = new URLSearchParams()
  if (tenantId.value) params.set('tenant_id', tenantId.value)
  if (groupId.value) params.set('group_id', groupId.value)
  if (categoryId.value) params.set('category_id', categoryId.value)
  if (dateFrom.value) params.set('date_from', dateFrom.value)
  if (dateTo.value) params.set('date_to', dateTo.value)
  if (user.value.trim()) params.set('user', user.value.trim())
  return params.toString()
}

async function loadSubmissions() {
  loading.value = true
  error.value = ''
  try {
    const query = buildQuery()
    submissions.value = await parseJson<AdminSubmission[]>(
      await auth.apiFetch(`/api/admin/submissions${query ? `?${query}` : ''}`),
      'Não foi possível carregar documentos preenchidos.',
    )
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

async function onTenantChange() {
  await loadGroups()
  await loadSubmissions()
}

async function onGroupChange() {
  await loadCategories()
  await loadSubmissions()
}

function clearFilters() {
  tenantId.value = ''
  groupId.value = ''
  categoryId.value = ''
  dateFrom.value = ''
  dateTo.value = ''
  user.value = ''
  groups.value = []
  categories.value = []
  loadSubmissions()
}

function openSubmission(submissionId: string) {
  history.pushState({}, '', `/submissao/${submissionId}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

onMounted(async () => {
  await loadTenants()
  await loadSubmissions()
})
</script>

<template>
  <section class="admin-filled-page">
    <header class="admin-header">
      <div>
        <h2>Documentos preenchidos</h2>
        <span class="admin-role">Acesso restrito: pdf-admin</span>
      </div>
      <button type="button" class="button-secondary" @click="loadSubmissions">Atualizar</button>
    </header>

    <form class="filled-filters card" @submit.prevent="loadSubmissions">
      <label>Tenant
        <select v-model="tenantId" @change="onTenantChange">
          <option value="">Todos os tenants</option>
          <option v-for="tenant in tenants" :key="tenant.tenant_id" :value="tenant.tenant_id">{{ tenant.name }}</option>
        </select>
      </label>
      <label>Grupo
        <select v-model="groupId" :disabled="!tenantId" @change="onGroupChange">
          <option value="">Todos os grupos</option>
          <option v-for="group in groups" :key="group.group_id" :value="group.group_id">{{ group.name }}</option>
        </select>
      </label>
      <label>Categoria
        <select v-model="categoryId" :disabled="!tenantId || !groupId" @change="loadSubmissions">
          <option value="">Todas as categorias</option>
          <option v-for="category in categories" :key="category.category_id" :value="category.category_id">{{ category.name }}</option>
        </select>
      </label>
      <label>De
        <input v-model="dateFrom" type="date" @change="loadSubmissions">
      </label>
      <label>Até
        <input v-model="dateTo" type="date" @change="loadSubmissions">
      </label>
      <label>Usuário
        <input v-model="user" maxlength="255" placeholder="Nome, e-mail ou subject">
      </label>
      <div class="filled-filter-actions">
        <button type="submit">Filtrar</button>
        <button type="button" class="button-secondary" :disabled="!hasFilters" @click="clearFilters">Limpar</button>
      </div>
    </form>

    <section class="card filled-results">
      <p v-if="loading" class="viewer-message">Carregando documentos preenchidos...</p>
      <p v-else-if="error" class="viewer-message viewer-error">{{ error }}</p>
      <p v-else-if="!submissions.length" class="viewer-message">Nenhum documento preenchido encontrado.</p>
      <div v-else class="filled-table">
        <button
          v-for="submission in submissions"
          :key="submission.submission_id"
          type="button"
          class="filled-row"
          @click="openSubmission(submission.submission_id)"
        >
          <span>
            <strong>{{ submission.document_name }}</strong>
            <small>{{ submission.tenant_name || 'Sem tenant' }} / {{ submission.group_name || 'Sem grupo' }}</small>
          </span>
          <span>
            <strong>{{ submission.username || submission.email || submission.subject || 'Usuário' }}</strong>
            <small>{{ submission.email || submission.subject }}</small>
          </span>
          <span>
            <strong>{{ submission.category_name || 'Sem categoria' }}</strong>
            <small>Protocolo: {{ submission.submission_id }}</small>
          </span>
          <small>{{ formatDate(submission.created_at) }}</small>
        </button>
      </div>
    </section>
  </section>
</template>
