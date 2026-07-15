<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import ContextSelector from './ContextSelector.vue'
import UploadForm from './UploadForm.vue'
import DocumentHistory from './DocumentHistory.vue'
import ResultPanel from './ResultPanel.vue'
import ApiKeyManager from './ApiKeyManager.vue'
import UserAccessManager from './UserAccessManager.vue'

const auth = useAuthStore()
const apiKeyManager = ref<InstanceType<typeof ApiKeyManager> | null>(null)
defineProps<{ activeView: 'documents' | 'users' | 'available' }>()
const emit = defineEmits<{ navigate: ['documents' | 'users' | 'available'] }>()
</script>

<template>
  <main id="app-shell">
    <div class="session-bar">
      <span class="session-user">{{ auth.displayName }}</span>
      <h1 class="session-title">Neural PDF</h1>
      <div class="button-group">
        <button type="button" :class="{ active: activeView === 'documents' }" @click="emit('navigate', 'documents')">Documentos</button>
        <button type="button" :class="{ active: activeView === 'available' }" @click="emit('navigate', 'available')">Disponíveis</button>
        <button v-if="auth.isAdmin" type="button" :class="{ active: activeView === 'users' }" @click="emit('navigate', 'users')">Usuários</button>
        <button v-if="auth.isAdmin" type="button" @click="apiKeyManager?.open()">API Key</button>
        <button type="button" @click="auth.logout()">Sair</button>
      </div>
    </div>
    <p v-if="activeView === 'documents'" class="lead app-description">Extraia campos, tipos, imagens e logotipos. A rede neural treinada com documentos da UEPG localiza regioes de tabela, inclusive em paginas rasterizadas.</p>

    <div v-if="activeView === 'documents'" class="page-layout">
      <div class="left-column">
        <ContextSelector />
        <UploadForm />
        <DocumentHistory />
      </div>
      <ResultPanel />
    </div>
    <UserAccessManager v-else-if="auth.isAdmin" />
  </main>
  <ApiKeyManager ref="apiKeyManager" />
</template>
