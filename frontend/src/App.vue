<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from './stores/auth'
import LoginScreen from './components/LoginScreen.vue'
import AppShell from './components/AppShell.vue'
import DocumentViewer from './components/DocumentViewer.vue'
import SubmissionViewer from './components/SubmissionViewer.vue'
import AvailableDocuments from './components/AvailableDocuments.vue'
import SubmittedDocuments from './components/SubmittedDocuments.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import TextInputModal from './components/TextInputModal.vue'
import FieldEditModal from './components/FieldEditModal.vue'

const auth = useAuthStore()
const routePath = ref(location.pathname)

const viewerDocumentId = computed(() => routePath.value.match(/^\/documento\/([0-9a-f]{32}|[0-9a-f]{64})\/?$/)?.[1] || '')
const viewerSubmissionId = computed(() => routePath.value.match(/^\/submissao\/([0-9a-f]{32})\/?$/)?.[1] || '')
const isAvailableDocumentsRoute = computed(() => routePath.value.replace(/\/+$/, '') === '/documentos-disponiveis')
const isSubmittedDocumentsRoute = computed(() => routePath.value.replace(/\/+$/, '') === '/submissoes')
const activeView = computed<'documents' | 'users' | 'available'>(() => {
  const normalized = routePath.value.replace(/\/+$/, '')
  if (normalized === '/usuarios' && auth.isAdmin) return 'users'
  if (normalized === '/documentos-disponiveis') return 'available'
  return 'documents'
})

function syncRoute() {
  routePath.value = location.pathname
  redirectNonAdminHome()
}

function redirectNonAdminHome() {
  if (
    auth.initialized && auth.isAuthenticated && !auth.isAdmin
    && !viewerDocumentId.value && !viewerSubmissionId.value && !isAvailableDocumentsRoute.value && !isSubmittedDocumentsRoute.value
  ) {
    history.replaceState({}, '', '/documentos-disponiveis')
    syncRoute()
  }
}

function navigate(view: 'documents' | 'users' | 'available') {
  const path = view === 'users' ? '/usuarios' : view === 'available' ? '/documentos-disponiveis' : '/documentos'
  if (location.pathname !== path) history.pushState({}, '', path)
  syncRoute()
}

onMounted(() => {
  auth.initialize().then(redirectNonAdminHome)
  window.addEventListener('popstate', syncRoute)
})

onUnmounted(() => {
  window.removeEventListener('popstate', syncRoute)
})
</script>

<template>
  <LoginScreen v-if="!auth.initialized || !auth.isAuthenticated" :password-login="Boolean(viewerDocumentId || viewerSubmissionId)" />
  <DocumentViewer v-else-if="viewerDocumentId" :document-id="viewerDocumentId" />
  <SubmissionViewer v-else-if="viewerSubmissionId" :submission-id="viewerSubmissionId" />
  <SubmittedDocuments v-else-if="isSubmittedDocumentsRoute" />
  <AvailableDocuments v-else-if="isAvailableDocumentsRoute || !auth.isAdmin" />
  <AppShell v-else :active-view="activeView" @navigate="navigate" />
  <ConfirmModal />
  <TextInputModal />
  <FieldEditModal />
</template>
