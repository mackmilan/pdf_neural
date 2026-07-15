<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import LoginScreen from './components/LoginScreen.vue'
import AppShell from './components/AppShell.vue'
import DocumentViewer from './components/DocumentViewer.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import TextInputModal from './components/TextInputModal.vue'
import FieldEditModal from './components/FieldEditModal.vue'

const auth = useAuthStore()
const viewerMatch = location.pathname.match(/^\/documento\/([0-9a-f]{32}|[0-9a-f]{64})\/?$/)
const viewerDocumentId = viewerMatch?.[1] || ''

onMounted(() => {
  auth.initialize()
})
</script>

<template>
  <LoginScreen v-if="!auth.initialized || !auth.isAuthenticated" :password-login="Boolean(viewerDocumentId)" />
  <DocumentViewer v-else-if="viewerDocumentId" :document-id="viewerDocumentId" />
  <AppShell v-else />
  <ConfirmModal />
  <TextInputModal />
  <FieldEditModal />
</template>
