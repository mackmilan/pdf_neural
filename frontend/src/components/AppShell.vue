<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import ContextSelector from './ContextSelector.vue'
import UploadForm from './UploadForm.vue'
import DocumentHistory from './DocumentHistory.vue'
import ResultPanel from './ResultPanel.vue'
import ApiKeyManager from './ApiKeyManager.vue'
import UiIcon from './UiIcon.vue'

const UserAccessManager = defineAsyncComponent(() => import('./UserAccessManager.vue'))
const AdminFilledDocuments = defineAsyncComponent(() => import('./AdminFilledDocuments.vue'))

const auth = useAuthStore()
const context = useContextStore()
const docStore = useDocumentStore()
const apiKeyManager = ref<InstanceType<typeof ApiKeyManager> | null>(null)
defineProps<{ activeView: 'documents' | 'users' | 'available' | 'filled' }>()
const emit = defineEmits<{ navigate: ['documents' | 'users' | 'available' | 'filled'] }>()

const currentTenantName = computed(() => context.tenants.find((tenant) => tenant.tenant_id === context.tenantId)?.name || 'Sem tenant')
const currentGroupName = computed(() => context.groupName(context.groupId))
const brandTitle = computed(() => {
  if (auth.isAdmin) return 'Neural PDF'
  return context.tenants.find((tenant) => tenant.tenant_id === context.tenantId)?.name
    || context.tenants[0]?.name
    || 'Sem tenant'
})
const brandSubtitle = computed(() => {
  if (auth.isAdmin) return 'PDF Admin'
  return context.groups.find((group) => group.group_id === context.groupId)?.name
    || context.groups[0]?.name
    || 'Sem grupo'
})
const currentCategoryName = computed(() => context.categoryName(docStore.currentCategoryId || context.categoryId))
const currentVersionLabel = computed(() => docStore.currentVersion ? `v${docStore.currentVersion}` : 'Sem versão')
const currentFieldsLabel = computed(() => `${docStore.currentFields.length} campo${docStore.currentFields.length === 1 ? '' : 's'}`)
const documentRenderUrl = computed(() =>
  docStore.currentDocumentId ? `/documento/${encodeURIComponent(docStore.currentDocumentId)}` : '',
)

function openDocumentRender() {
  if (!documentRenderUrl.value) return
  const renderWindow = window.open(documentRenderUrl.value, '_blank')
  if (!renderWindow) {
    docStore.status = 'O navegador bloqueou a nova aba. Permita pop-ups para abrir a renderização.'
    return
  }
  renderWindow.opener = null
}
</script>

<template>
  <main id="app-shell">
    <header class="app-topbar">
      <div class="app-topbar-main">
        <div class="app-brand">
          <span class="app-brand-mark" aria-hidden="true"><UiIcon name="file-text" /></span>
          <span class="app-brand-copy">
            <h1 class="app-brand-title">{{ brandTitle }}</h1>
            <span class="app-brand-subtitle">{{ brandSubtitle }}</span>
          </span>
        </div>

        <p class="app-topbar-description">
          Extraia campos, tipos, imagens e logotipos em documentos.
        </p>

        <nav class="app-nav" aria-label="Navegação principal">
          <button type="button" :class="{ active: activeView === 'documents' }" @click="emit('navigate', 'documents')">Documentos</button>
          <button type="button" :class="{ active: activeView === 'available' }" @click="emit('navigate', 'available')">Disponíveis</button>
          <button v-if="auth.isAdmin" type="button" :class="{ active: activeView === 'filled' }" @click="emit('navigate', 'filled')">Preenchidos</button>
          <button v-if="auth.isAdmin" type="button" :class="{ active: activeView === 'users' }" @click="emit('navigate', 'users')">Usuários</button>
        </nav>

        <div class="app-session-actions">
          <button v-if="auth.isAdmin" type="button" class="app-icon-button" title="API Key" aria-label="API Key" @click="apiKeyManager?.open()">
            <UiIcon name="key" />
          </button>
          <span class="app-session-user" :title="auth.displayName">
            <UiIcon name="user" />
            <span>{{ auth.displayName }}</span>
          </span>
          <button type="button" class="app-icon-button" title="Sair" aria-label="Sair" @click="auth.logout()">
            <UiIcon name="log-out" />
          </button>
        </div>
      </div>

      <div v-if="activeView === 'documents'" class="app-context-row">
        <div class="app-breadcrumbs" aria-label="Contexto atual">
          <span>{{ currentTenantName }}</span>
          <span aria-hidden="true">/</span>
          <span>{{ currentGroupName }}</span>
          <span v-if="docStore.currentDocumentName" aria-hidden="true">/</span>
          <strong v-if="docStore.currentDocumentName">{{ docStore.currentDocumentName }}</strong>
        </div>

        <div class="app-context-chips" aria-label="Resumo do documento">
          <span>{{ currentCategoryName }}</span>
          <span v-if="docStore.currentDocumentId">{{ currentVersionLabel }}</span>
          <span v-if="docStore.currentDocumentId">{{ currentFieldsLabel }}</span>
        </div>

        <button
          type="button"
          class="app-render-button button-with-icon"
          :disabled="!documentRenderUrl"
          @click="openDocumentRender"
        >
          <UiIcon name="external-link" />
          Abrir renderização
        </button>
      </div>
    </header>

    <div v-if="activeView === 'documents'" class="page-layout">
      <div class="left-column">
        <ContextSelector />
        <UploadForm />
        <DocumentHistory />
      </div>
      <ResultPanel />
    </div>
    <AdminFilledDocuments v-else-if="activeView === 'filled' && auth.isAdmin" />
    <UserAccessManager v-else-if="auth.isAdmin" />
  </main>
  <ApiKeyManager ref="apiKeyManager" />
</template>
