<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import ContextSelector from './ContextSelector.vue'
import UploadForm from './UploadForm.vue'
import DocumentHistory from './DocumentHistory.vue'
import ResultPanel from './ResultPanel.vue'
import ApiKeyManager from './ApiKeyManager.vue'

const auth = useAuthStore()
const apiKeyManager = ref<InstanceType<typeof ApiKeyManager> | null>(null)
</script>

<template>
  <main id="app-shell">
    <div class="session-bar">
      <span>{{ auth.displayName }}</span>
      <h1 class="session-title">Neural PDF</h1>
      <div class="button-group">
        <button v-if="auth.isAdmin" type="button" @click="apiKeyManager?.open()">API Key</button>
        <button type="button" @click="auth.logout()">Sair</button>
      </div>
    </div>
    <p class="lead app-description">Extraia campos, tipos, imagens e logotipos. A rede neural treinada com documentos da UEPG localiza regioes de tabela, inclusive em paginas rasterizadas.</p>

    <div class="page-layout">
      <div class="left-column">
        <ContextSelector />
        <UploadForm />
        <DocumentHistory />
      </div>
      <ResultPanel />
    </div>
  </main>
  <ApiKeyManager ref="apiKeyManager" />
</template>
