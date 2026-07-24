<script setup lang="ts">
// Seletor de contexto da topbar: vale para todas as telas, por isso vive no
// cabeçalho e não em um card da página de documentos.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import UiIcon from './UiIcon.vue'

const auth = useAuthStore()
const context = useContextStore()
const tenantName = ref('')
const groupName = ref('')
const categoryName = ref('')
const open = ref(false)
const root = ref<HTMLElement | null>(null)

const currentTenantName = computed(() => context.tenants.find((tenant) => tenant.tenant_id === context.tenantId)?.name || 'Sem tenant')
const currentGroupName = computed(() => context.groupName(context.groupId) || 'Todos os grupos')
const currentCategoryName = computed(() => context.categoryName(context.categoryId) || 'Todas as categorias')
const summary = computed(() => `${currentTenantName.value} · ${currentGroupName.value} · ${currentCategoryName.value}`)

function close() {
  open.value = false
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) close()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

// Os listeners globais só existem enquanto o popup está aberto.
watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

onMounted(() => {
  // Para quem não é admin, o AppSidebar já carrega e escolhe tenant e grupo.
  if (auth.isAdmin) context.loadTenants()
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})

async function onTenantChange() {
  await context.onTenantChange()
}
async function onGroupChange() {
  await context.onGroupChange()
}
async function onCategoryChange() {
  await context.onCategoryChange()
}

async function createTenant() {
  const name = tenantName.value.trim()
  if (!name) {
    context.status = 'Informe o nome do tenant.'
    return
  }
  try {
    const data = await context.createTenant(name)
    tenantName.value = ''
    context.status = `Tenant "${data.name}" criado.`
  } catch (error) {
    context.status = 'Erro ao criar tenant: ' + (error as Error).message
  }
}

async function createGroup() {
  const name = groupName.value.trim()
  if (!name || !context.tenantId) {
    context.status = 'Selecione um tenant e informe o nome do grupo.'
    return
  }
  try {
    const data = await context.createGroup(name)
    groupName.value = ''
    context.status = `Grupo "${data.name}" criado.`
  } catch (error) {
    context.status = 'Erro ao criar grupo: ' + (error as Error).message
  }
}

async function createCategory() {
  const name = categoryName.value.trim()
  if (!name || !context.tenantId || !context.groupId) {
    context.status = 'Selecione um tenant e um grupo, e informe o nome da categoria.'
    return
  }
  try {
    const data = await context.createCategory(name)
    categoryName.value = ''
    context.status = `Categoria "${data.name}" criada.`
  } catch (error) {
    context.status = 'Erro ao criar categoria: ' + (error as Error).message
  }
}
</script>

<template>
  <div ref="root" class="app-context-switcher">
    <button
      type="button"
      class="app-context-trigger"
      aria-haspopup="dialog"
      :aria-expanded="open"
      :title="summary"
      @click="open = !open"
    >
      <UiIcon name="layers" />
      <span class="app-context-trigger-label">{{ summary }}</span>
      <UiIcon name="chevron-down" />
    </button>

    <div v-if="open" class="app-context-popup" role="dialog" aria-label="Contexto">
      <div class="context-grid">
        <div>
          <label class="context-field">Tenant
            <select v-model="context.tenantId" @change="onTenantChange">
              <option value="">Selecione um tenant</option>
              <option v-for="tenant in context.tenants" :key="tenant.tenant_id" :value="tenant.tenant_id">{{ tenant.name }}</option>
            </select>
          </label>
          <div v-if="auth.isAdmin" class="context-create">
            <input v-model="tenantName" maxlength="120" placeholder="Nome do novo tenant" aria-label="Nome do novo tenant">
            <button type="button" @click="createTenant">Criar tenant</button>
          </div>
        </div>
        <div>
          <label class="context-field">Grupo
            <select v-model="context.groupId" :disabled="!context.tenantId" @change="onGroupChange">
              <option value="">Todos os grupos</option>
              <option v-for="group in context.groups" :key="group.group_id" :value="group.group_id">{{ group.name }}</option>
            </select>
          </label>
          <div v-if="auth.isAdmin" class="context-create">
            <input v-model="groupName" maxlength="120" placeholder="Nome do novo grupo" aria-label="Nome do novo grupo" :disabled="!context.tenantId">
            <button type="button" :disabled="!context.tenantId" @click="createGroup">Criar grupo</button>
          </div>
        </div>
        <div>
          <label class="context-field">Categoria / filtro
            <select v-model="context.categoryId" :disabled="!context.tenantId || !context.groupId" @change="onCategoryChange">
              <option value="">Todas as categorias</option>
              <option v-for="category in context.categories" :key="category.category_id" :value="category.category_id">{{ category.name }}</option>
            </select>
          </label>
          <div v-if="auth.isAdmin" class="context-create">
            <input v-model="categoryName" maxlength="120" placeholder="Nome da nova categoria" aria-label="Nome da nova categoria" :disabled="!context.tenantId || !context.groupId">
            <button type="button" :disabled="!context.tenantId || !context.groupId" @click="createCategory">Criar categoria</button>
          </div>
        </div>
      </div>
      <div v-if="context.status" class="status">{{ context.status }}</div>
    </div>
  </div>
</template>
