<script setup lang="ts">
import { computed, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import type { ApiKeyInfo } from '../types'

const auth = useAuthStore()
const context = useContextStore()

const show = ref(false)
const clientId = ref('')
const name = ref('')
const keys = ref<ApiKeyInfo[]>([])
const generatedKey = ref('')
const message = ref('Informe os detalhes para a nova chave de API.')
const submitting = ref(false)

const activeContextLabel = computed(() => {
  const tenantName = context.tenants.find((tenant) => tenant.tenant_id === context.tenantId)?.name || 'Nenhum'
  const groupName = context.groups.find((group) => group.group_id === context.groupId)?.name || 'Todos os grupos'
  return `Tenant: ${tenantName} | Grupo: ${groupName}`
})

async function loadKeys() {
  if (!context.tenantId) return
  try {
    const params = new URLSearchParams({ tenant_id: context.tenantId })
    if (context.groupId) params.set('group_id', context.groupId)
    const response = await auth.apiFetch(`/api/api-keys?${params}`)
    if (!response.ok) return
    keys.value = await response.json()
  } catch (error) {
    console.error('Erro ao carregar API Keys:', error)
  }
}

function open() {
  show.value = true
  clientId.value = ''
  name.value = ''
  generatedKey.value = ''
  message.value = 'Informe os detalhes para a nova chave de API.'
  loadKeys()
}

function close() {
  show.value = false
}

async function revoke(targetClientId: string) {
  if (!confirm(`Deseja realmente revogar o acesso do cliente ${targetClientId}?`)) return
  try {
    const response = await auth.apiFetch('/api/api-keys/revoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: targetClientId, tenant_id: context.tenantId, group_id: context.groupId || null }),
    })
    if (response.ok) {
      await loadKeys()
    } else {
      const error = await response.json()
      alert(error.error || 'Erro ao revogar chave')
    }
  } catch (error) {
    alert((error as Error).message)
  }
}

async function submit() {
  submitting.value = true
  try {
    if (!context.tenantId) throw new Error('Selecione um tenant antes de gerar uma API Key.')
    const payload = { client_id: clientId.value, name: name.value, tenant_id: context.tenantId, group_id: context.groupId || null }
    const response = await auth.apiFetch('/api/api-keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.error || 'Erro ao gerar API Key')
    }
    const data = await response.json()
    generatedKey.value = data.api_key
    message.value = 'Chave gerada com sucesso!'
    await loadKeys()
  } catch (error) {
    alert((error as Error).message)
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <div class="modal-backdrop" :class="{ show }" :aria-hidden="!show" @click.self="close">
    <section v-if="show" class="modal" role="dialog" aria-modal="true">
      <h3>Gerar API Key</h3>
      <p>{{ message }}</p>
      <div class="api-key-context-info">
        A chave será restrita ao Tenant/Grupo selecionado no momento da geração.
        <div class="api-key-active-context">{{ activeContextLabel }}</div>
      </div>
      <div class="api-key-list-container" v-if="keys.length">
        <table class="api-key-table">
          <thead>
            <tr><th>Cliente</th><th>Nome</th><th>Criada em</th><th>Ações</th></tr>
          </thead>
          <tbody>
            <tr v-for="key in keys" :key="key.client_id">
              <td>{{ key.client_id }}</td>
              <td>{{ key.name }}</td>
              <td>{{ new Date(key.created_at).toLocaleDateString() }}</td>
              <td><button type="button" class="button-danger api-key-revoke" @click="revoke(key.client_id)">Revogar</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <form class="field-form" @submit.prevent="submit">
        <label>ID do Cliente (ex.: meu-servico)
          <input v-model="clientId" maxlength="120" required>
        </label>
        <label>Nome Descritivo
          <input v-model="name" maxlength="120" required placeholder="Ex.: Integração ERP">
        </label>
        <div class="api-key-result" :class="{ show: generatedKey }">
          <small>Sua nova API Key (copie agora, ela não será exibida novamente):</small>
          <code>{{ generatedKey }}</code>
        </div>
        <div class="modal-actions">
          <button type="button" class="button-secondary" @click="close">Fechar</button>
          <button v-if="!generatedKey" type="submit" :disabled="submitting">Gerar Chave</button>
        </div>
      </form>
    </section>
  </div>
</template>
