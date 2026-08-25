<script setup lang="ts">
import { computed, onBeforeUnmount, nextTick, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import { useModalsStore } from '../stores/modals'
import ViewerTopMenu from './ViewerTopMenu.vue'
import type { Group, Tenant, UserAccessEntry, UserAccessSummary, UserPermission } from '../types'

const auth = useAuthStore()
const context = useContextStore()
const modals = useModalsStore()
const users = ref<UserAccessSummary[]>([])
const tenants = ref<Tenant[]>([])
const groups = ref<Group[]>([])
const loading = ref(false)
const saving = ref(false)
const status = ref('')
const formStatus = ref('')
const filter = ref('')
const showForm = ref(false)
const editing = ref(false)
const firstFieldRef = ref<HTMLInputElement | null>(null)
let usersRequestId = 0
const form = ref({
  subject: '',
  username: '',
  email: '',
  password: '',
  temporary_password: true,
  tenant_id: '',
  group_id: '',
  permission: 'reader' as UserPermission,
})

const topbarChips = computed(() => [
  `${users.value.length} usuário${users.value.length === 1 ? '' : 's'}`,
])

const filteredUsers = computed(() => {
  const term = filter.value.trim().toLowerCase()
  if (!term) return users.value
  return users.value.filter((user) => {
    const haystack = [
      user.subject,
      user.username || '',
      ...user.access.flatMap((access) => [
        access.tenant_name || access.tenant_id,
        access.group_name || access.group_id || '',
        access.permission,
      ]),
    ].join(' ').toLowerCase()
    return haystack.includes(term)
  })
})

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text()
  let data: any = {}
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { error: text }
    }
  }
  if (!response.ok) {
    throw new Error(data.error || `Operação não concluída. HTTP ${response.status}`)
  }
  return data as T
}

async function loadUsers() {
  const requestId = ++usersRequestId
  const tenantId = context.tenantId
  users.value = []
  if (!tenantId) {
    loading.value = false
    status.value = 'Selecione um tenant para visualizar os usuários.'
    return
  }
  loading.value = true
  try {
    const params = new URLSearchParams({ tenant_id: tenantId })
    const nextUsers = await parseResponse<UserAccessSummary[]>(
      await auth.apiFetch(`/api/users/access?${params}`),
    )
    if (requestId !== usersRequestId || context.tenantId !== tenantId) return
    users.value = nextUsers
    status.value = ''
  } catch (error) {
    if (requestId !== usersRequestId) return
    status.value = 'Erro ao carregar usuários: ' + (error as Error).message
  } finally {
    if (requestId === usersRequestId) loading.value = false
  }
}

async function loadTenants() {
  try {
    tenants.value = await parseResponse<Tenant[]>(await auth.apiFetch('/api/tenants'))
  } catch (error) {
    status.value = 'Erro ao carregar tenants: ' + (error as Error).message
  }
}

async function loadGroups() {
  groups.value = []
  form.value.group_id = ''
  if (!form.value.tenant_id) return
  try {
    groups.value = await parseResponse<Group[]>(
      await auth.apiFetch(`/api/tenants/${encodeURIComponent(form.value.tenant_id)}/groups`),
    )
  } catch (error) {
    status.value = 'Erro ao carregar grupos: ' + (error as Error).message
  }
}

function openCreate() {
  void resetForm()
  editing.value = false
  formStatus.value = ''
  showForm.value = true
}

function closeForm() {
  showForm.value = false
}

function editAccess(user: UserAccessSummary, access: UserAccessEntry) {
  editing.value = true
  formStatus.value = ''
  showForm.value = true
  form.value = {
    subject: user.subject,
    username: access.username || user.username || '',
    email: '',
    password: '',
    temporary_password: true,
    tenant_id: access.tenant_id,
    group_id: access.group_id || '',
    permission: access.permission,
  }
  loadGroups().then(() => {
    form.value.group_id = access.group_id || ''
  })
}

async function resetForm() {
  form.value = {
    subject: '',
    username: '',
    email: '',
    password: '',
    temporary_password: true,
    tenant_id: context.tenantId,
    group_id: '',
    permission: 'reader',
  }
  groups.value = []
  await loadGroups()
  if (context.groupId && groups.value.some((group) => group.group_id === context.groupId)) {
    form.value.group_id = context.groupId
  }
}

async function saveAccess() {
  if (!form.value.tenant_id) {
    formStatus.value = 'Informe o tenant.'
    return
  }
  if (!form.value.subject.trim() && (!form.value.username.trim() || form.value.password.length < 8)) {
    formStatus.value = 'Para criar no Keycloak, informe username e senha com pelo menos 8 caracteres.'
    return
  }
  formStatus.value = ''
  saving.value = true
  try {
    const payload = {
      tenant_id: form.value.tenant_id,
      group_id: form.value.group_id || undefined,
      permission: form.value.permission,
      username: form.value.username.trim() || undefined,
    }
    if (form.value.subject.trim()) {
      await parseResponse(
        await auth.apiFetch(`/api/users/${encodeURIComponent(form.value.subject.trim())}/access`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }),
      )
      status.value = 'Acesso salvo.'
    } else {
      const data = await parseResponse<{ user: { id: string } }>(
        await auth.apiFetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...payload,
            username: form.value.username.trim(),
            display_name: form.value.username.trim(),
            email: form.value.email.trim() || undefined,
            password: form.value.password,
            temporary_password: form.value.temporary_password,
          }),
        }),
      )
      form.value.subject = data.user.id
      form.value.password = ''
      status.value = 'Usuário criado no Keycloak e acesso salvo.'
    }
    closeForm()
    await loadUsers()
  } catch (error) {
    formStatus.value = 'Erro ao salvar usuário: ' + (error as Error).message
  } finally {
    saving.value = false
  }
}

async function revokeAccess(access: UserAccessEntry) {
  const params = new URLSearchParams({ tenant_id: access.tenant_id })
  if (access.group_id) params.set('group_id', access.group_id)
  try {
    await parseResponse(
      await auth.apiFetch(`/api/users/${encodeURIComponent(access.subject)}/access?${params}`, { method: 'DELETE' }),
    )
    status.value = 'Acesso revogado.'
    await loadUsers()
  } catch (error) {
    status.value = 'Erro ao revogar acesso: ' + (error as Error).message
  }
}

async function deleteUser(user: UserAccessSummary) {
  const confirmed = await modals.showConfirm({
    title: 'Excluir usuário?',
    message: `Excluir ${user.username || user.subject} do Keycloak e da aplicação?`,
    confirmLabel: 'Excluir usuário',
    danger: true,
  })
  if (!confirmed) return
  try {
    const data = await parseResponse<{ deleted: number; keycloak_deleted: boolean }>(
      await auth.apiFetch(`/api/users/${encodeURIComponent(user.subject)}`, { method: 'DELETE' }),
    )
    status.value = data.keycloak_deleted
      ? 'Usuário excluído do Keycloak e da aplicação.'
      : 'Usuário removido da aplicação. Ele não foi encontrado no Keycloak.'
    if (form.value.subject === user.subject) {
      await resetForm()
      closeForm()
    }
    await loadUsers()
  } catch (error) {
    status.value = 'Erro ao excluir usuário: ' + (error as Error).message
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeForm()
}

watch(showForm, (visible) => {
  if (visible) {
    document.addEventListener('keydown', onKeydown)
    nextTick(() => firstFieldRef.value?.focus())
  } else {
    document.removeEventListener('keydown', onKeydown)
  }
})

watch(() => context.tenantId, () => {
  void loadUsers()
})

onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

onMounted(async () => {
  await Promise.all([loadUsers(), loadTenants()])
})
</script>

<template>
  <section class="admin-page">
    <ViewerTopMenu
      eyebrow="Usuários"
      :chips="topbarChips"
    >
      <template #actions>
        <button type="button" class="button-secondary" @click="loadUsers">Atualizar</button>
        <button type="button" @click="openCreate">Criar usuário</button>
      </template>
    </ViewerTopMenu>

    <div class="admin-layout">
      <div class="card access-list">
        <div class="access-toolbar">
          <h3>Usuários</h3>
          <input v-model="filter" placeholder="Filtrar" aria-label="Filtrar usuários">
        </div>
        <div v-if="status" class="status">{{ status }}</div>
        <div v-if="loading" class="history-empty">Carregando...</div>
        <div v-else-if="!filteredUsers.length" class="history-empty">Nenhum acesso encontrado.</div>
        <div v-else class="user-access-table">
          <article v-for="user in filteredUsers" :key="user.subject" class="user-access-row">
            <div class="user-access-identity">
              <strong>{{ user.username || 'Usuário sem nome' }}</strong>
              <code>{{ user.subject }}</code>
              <button type="button" class="button-danger user-delete" @click="deleteUser(user)">Excluir usuário</button>
            </div>
            <div class="user-access-scopes">
              <div v-for="access in user.access" :key="`${access.tenant_id}:${access.group_id || 'tenant'}`" class="scope-row">
                <div>
                  <strong>{{ access.tenant_name || access.tenant_id }}</strong>
                  <span>{{ access.group_name || (access.group_id ? access.group_id : 'Todo o tenant') }}</span>
                </div>
                <span class="permission-badge">{{ access.permission }}</span>
                <button type="button" class="button-secondary" @click="editAccess(user, access)">Editar</button>
                <button type="button" class="button-danger" @click="revokeAccess(access)">Revogar</button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>

    <div class="modal-backdrop" :class="{ show: showForm }" :aria-hidden="!showForm" @click.self="closeForm">
      <section v-if="showForm" class="modal access-modal" role="dialog" aria-modal="true" aria-label="Cadastro de usuário">
        <h3>{{ editing ? 'Editar acesso' : 'Novo usuário / acesso' }}</h3>
        <form class="access-form" @submit.prevent="saveAccess">
          <div class="access-form-fields">
            <label v-if="editing">Keycloak sub
              <input v-model="form.subject" autocomplete="off" readonly>
            </label>
            <label>Username
              <input ref="firstFieldRef" v-model="form.username" autocomplete="username" placeholder="Login no Keycloak">
            </label>
            <label>E-mail
              <input v-model="form.email" autocomplete="email" type="email" placeholder="usuario@dominio.com">
            </label>
            <label>Senha inicial
              <input v-model="form.password" autocomplete="new-password" type="password" placeholder="Obrigatória ao criar">
            </label>
            <label class="access-check">
              <input v-model="form.temporary_password" type="checkbox">
              Exigir troca de senha no primeiro login
            </label>
            <label>Tenant
              <select v-model="form.tenant_id" @change="loadGroups">
                <option value="">Selecione</option>
                <option v-for="tenant in tenants" :key="tenant.tenant_id" :value="tenant.tenant_id">{{ tenant.name }}</option>
              </select>
            </label>
            <label>Grupo
              <select v-model="form.group_id" :disabled="!form.tenant_id">
                <option value="">Todo o tenant</option>
                <option v-for="group in groups" :key="group.group_id" :value="group.group_id">{{ group.name }}</option>
              </select>
            </label>
            <label>Papel
              <select v-model="form.permission">
                <option value="reader">reader</option>
                <option value="editor">editor</option>
              </select>
            </label>
          </div>
          <div v-if="formStatus" class="status">{{ formStatus }}</div>
          <div class="modal-actions">
            <button type="button" class="button-secondary" @click="closeForm">Cancelar</button>
            <button type="button" class="button-secondary" @click="resetForm">Limpar</button>
            <button type="submit" :disabled="saving">{{ saving ? 'Salvando...' : 'Salvar' }}</button>
          </div>
        </form>
      </section>
    </div>
  </section>
</template>
