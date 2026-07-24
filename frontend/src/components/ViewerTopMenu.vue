<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import UiIcon from './UiIcon.vue'
import UserMenu from './UserMenu.vue'

const props = defineProps<{
  activeRoute?: 'documents' | 'available' | 'filled' | 'users' | 'submissions'
  eyebrow?: string
  title?: string
  context?: string
  chips?: string[]
}>()
const auth = useAuthStore()
const contextStore = useContextStore()

const brandTitle = computed(() => {
  if (auth.isAdmin) return 'Neural PDF'
  return contextStore.tenants.find((tenant) => tenant.tenant_id === contextStore.tenantId)?.name
    || contextStore.tenants[0]?.name
    || 'Sem tenant'
})
const brandSubtitle = computed(() => {
  if (auth.isAdmin) return 'PDF Admin'
  return contextStore.groups.find((group) => group.group_id === contextStore.groupId)?.name
    || contextStore.groups[0]?.name
    || 'Sem grupo'
})

onMounted(async () => {
  if (auth.isAdmin) return
  if (!contextStore.tenants.length) await contextStore.loadTenants()
  if (!contextStore.tenantId && contextStore.tenants.length) {
    contextStore.tenantId = contextStore.tenants[0].tenant_id
  }
  if (contextStore.tenantId && !contextStore.groups.length) {
    await contextStore.loadGroups(contextStore.groupId)
  }
  if (!contextStore.groupId && contextStore.groups.length) {
    contextStore.groupId = contextStore.groups[0].group_id
  }
})

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
  <header class="app-topbar viewer-top-menu">
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

      <nav class="app-nav" aria-label="Menu principal">
        <button
          v-if="auth.isAdmin"
          type="button"
          :class="{ active: props.activeRoute === 'documents' }"
          @click="goToAdminDocuments"
        >
          Documentos
        </button>
        <button type="button" :class="{ active: props.activeRoute === 'available' }" @click="goToAvailable">
          Disponíveis
        </button>
        <button
          v-if="!auth.isAdmin"
          type="button"
          :class="{ active: props.activeRoute === 'submissions' }"
          @click="goToSubmissions"
        >
          Submetidos
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
      </nav>

      <div class="app-session-actions">
        <UserMenu />
      </div>
    </div>

    <div v-if="props.title || props.context || props.chips?.length || $slots.actions" class="app-context-row">
      <div class="app-breadcrumbs" aria-label="Contexto atual">
        <span v-if="props.eyebrow">{{ props.eyebrow }}</span>
        <span v-if="props.eyebrow && props.title" aria-hidden="true">/</span>
        <strong v-if="props.title">{{ props.title }}</strong>
        <span v-if="props.context" aria-hidden="true">/</span>
        <span v-if="props.context">{{ props.context }}</span>
      </div>

      <div v-if="props.chips?.length" class="app-context-chips" aria-label="Resumo">
        <span v-for="chip in props.chips" :key="chip">{{ chip }}</span>
      </div>

      <div v-if="$slots.actions" class="app-context-actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>
