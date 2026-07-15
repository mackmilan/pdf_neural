<script setup lang="ts">
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ activeRoute?: 'available' | 'submissions' }>()
const auth = useAuthStore()

function goToAvailable() {
  if (location.pathname !== '/documentos-disponiveis') history.pushState({}, '', '/documentos-disponiveis')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function goToSubmissions() {
  if (location.pathname !== '/submissoes') history.pushState({}, '', '/submissoes')
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function goToAdminDocuments() {
  if (location.pathname !== '/documentos') history.pushState({}, '', '/documentos')
  window.dispatchEvent(new PopStateEvent('popstate'))
}
</script>

<template>
  <nav class="session-bar viewer-top-menu" aria-label="Menu principal">
    <span class="session-user">{{ auth.displayName }}</span>
    <h1 class="session-title">Neural PDF</h1>
    <div class="button-group">
      <button type="button" :class="{ active: props.activeRoute === 'available' }" @click="goToAvailable">
        Documentos disponíveis
      </button>
      <button type="button" :class="{ active: props.activeRoute === 'submissions' }" @click="goToSubmissions">
        Documentos submetidos
      </button>
      <button v-if="auth.isAdmin" type="button" @click="goToAdminDocuments">Administração</button>
      <button type="button" @click="auth.logout()">Sair</button>
    </div>
  </nav>
</template>
