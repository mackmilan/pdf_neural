<script setup lang="ts">
import { useAuthStore } from '../stores/auth'

const props = defineProps<{
  activeRoute?: 'documents' | 'available' | 'filled' | 'users' | 'submissions'
}>()
const auth = useAuthStore()

function navigate(path: string) {
  if (location.pathname !== path) history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function goToAvailable() {
  navigate('/documentos-disponiveis')
}

function goToSubmissions() {
  navigate('/submissoes')
}

function goToAdminDocuments() {
  navigate('/documentos')
}

function goToFilledDocuments() {
  navigate('/preenchidos')
}

function goToUsers() {
  navigate('/usuarios')
}
</script>

<template>
  <nav class="session-bar viewer-top-menu" aria-label="Menu principal">
    <span class="session-user">{{ auth.displayName }}</span>
    <div class="button-group">
      <button
        v-if="auth.isAdmin"
        type="button"
        :class="{ active: props.activeRoute === 'documents' }"
        @click="goToAdminDocuments"
      >
        Documentos
      </button>
      <button type="button" :class="{ active: props.activeRoute === 'available' }" @click="goToAvailable">
        Documentos disponíveis
      </button>
      <button
        v-if="!auth.isAdmin"
        type="button"
        :class="{ active: props.activeRoute === 'submissions' }"
        @click="goToSubmissions"
      >
        Documentos submetidos
      </button>
      <button
        v-if="auth.isAdmin"
        type="button"
        :class="{ active: props.activeRoute === 'filled' }"
        @click="goToFilledDocuments"
      >
        Preenchidos
      </button>
      <button
        v-if="auth.isAdmin"
        type="button"
        :class="{ active: props.activeRoute === 'users' }"
        @click="goToUsers"
      >
        Usuários
      </button>
      <button type="button" @click="auth.logout()">Sair</button>
    </div>
  </nav>
</template>
