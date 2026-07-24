<script setup lang="ts">
import { computed, defineAsyncComponent, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import ContextSelector from './ContextSelector.vue'
import UploadForm from './UploadForm.vue'
import DocumentHistory from './DocumentHistory.vue'
import ResultPanel from './ResultPanel.vue'
import UiIcon from './UiIcon.vue'

const UserAccessManager = defineAsyncComponent(() => import('./UserAccessManager.vue'))
const AdminFilledDocuments = defineAsyncComponent(() => import('./AdminFilledDocuments.vue'))

const auth = useAuthStore()
const context = useContextStore()
const docStore = useDocumentStore()
defineProps<{ activeView: 'documents' | 'users' | 'available' | 'filled' }>()

const showUpload = ref(false)

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
    <header v-if="activeView === 'documents'" class="app-topbar">
      <div class="app-topbar-main">
        <h2 class="app-page-title">Documentos</h2>
        <p class="app-topbar-description">
          Extraia campos, tipos, imagens e logotipos em documentos.
        </p>
      </div>

      <div class="app-context-row">
        <ContextSelector />

        <div v-if="docStore.currentDocumentName" class="app-breadcrumbs" aria-label="Documento atual">
          <strong>{{ docStore.currentDocumentName }}</strong>
        </div>

        <div class="app-context-chips" aria-label="Resumo do documento">
          <span v-if="docStore.currentDocumentId">{{ currentCategoryName }}</span>
          <span v-if="docStore.currentDocumentId">{{ currentVersionLabel }}</span>
          <span v-if="docStore.currentDocumentId">{{ currentFieldsLabel }}</span>
        </div>

        <button
          type="button"
          class="app-new-document-button button-with-icon"
          @click="showUpload = true"
        >
          <UiIcon name="plus" />
          Novo documento
        </button>

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
      <div class="left-column" v-show="!docStore.resultVisible">
        <DocumentHistory />
      </div>
      <ResultPanel />
      <UploadForm :open="showUpload" @close="showUpload = false" />
    </div>
    <AdminFilledDocuments v-else-if="activeView === 'filled' && auth.isAdmin" />
    <UserAccessManager v-else-if="auth.isAdmin" />
  </main>
</template>
