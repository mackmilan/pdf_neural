<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useContextStore } from '../stores/context'

const context = useContextStore()
const tenantName = ref('')
const groupName = ref('')
const categoryName = ref('')

onMounted(() => {
  context.loadTenants()
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
  <details class="card collapsible-card" open>
    <summary><h2>Contexto dos documentos</h2></summary>
    <div class="collapsible-content">
      <p class="status">Organize documentos por tenants, grupos e categorias vinculadas ao grupo.</p>
      <div class="context-grid">
        <div>
          <label class="context-field">Tenant
            <select v-model="context.tenantId" @change="onTenantChange">
              <option value="">Selecione um tenant</option>
              <option v-for="tenant in context.tenants" :key="tenant.tenant_id" :value="tenant.tenant_id">{{ tenant.name }}</option>
            </select>
          </label>
          <div class="context-create">
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
          <div class="context-create">
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
          <div class="context-create">
            <input v-model="categoryName" maxlength="120" placeholder="Nome da nova categoria" aria-label="Nome da nova categoria" :disabled="!context.tenantId || !context.groupId">
            <button type="button" :disabled="!context.tenantId || !context.groupId" @click="createCategory">Criar categoria</button>
          </div>
        </div>
      </div>
      <div class="status">{{ context.status }}</div>
    </div>
  </details>
</template>
