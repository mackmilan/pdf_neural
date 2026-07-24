<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useContextStore } from '../stores/context'
import { useThemeStore } from '../stores/theme'
import ApiKeyManager from './ApiKeyManager.vue'
import UiIcon, { type IconName } from './UiIcon.vue'

type Route = 'documents' | 'available' | 'submissions' | 'filled' | 'users'

const auth = useAuthStore()
const contextStore = useContextStore()
const theme = useThemeStore()

const COLLAPSED_KEY = 'pdf-neural-sidebar-collapsed'

const routePath = ref(location.pathname)
const collapsed = ref(localStorage.getItem(COLLAPSED_KEY) === '1')
const apiKeyManager = ref<InstanceType<typeof ApiKeyManager> | null>(null)
const userMenuOpen = ref(false)
const userMenu = ref<HTMLElement | null>(null)

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

// A rota ativa vem do próprio pathname: as telas de visualização (/documento/,
// /submissao/) marcam o item de lista de onde partiram.
const activeRoute = computed<Route | ''>(() => {
  const path = routePath.value.replace(/\/+$/, '')
  if (path === '/usuarios') return 'users'
  if (path === '/preenchidos') return 'filled'
  if (path === '/documentos-disponiveis') return 'available'
  if (path === '/submissoes') return auth.isAdmin ? 'filled' : 'submissions'
  if (path.startsWith('/documento/')) return auth.isAdmin ? 'documents' : 'available'
  if (path.startsWith('/submissao/')) return auth.isAdmin ? 'filled' : 'submissions'
  if (path === '/documentos') return 'documents'
  return auth.isAdmin ? 'documents' : 'available'
})

const items = computed(() => {
  const all: { route: Route; label: string; icon: IconName; path: string; visible: boolean }[] = [
    { route: 'documents', label: 'Documentos', icon: 'file-text', path: '/documentos', visible: auth.isAdmin },
    { route: 'available', label: 'Disponíveis', icon: 'inbox', path: '/documentos-disponiveis', visible: true },
    { route: 'submissions', label: 'Submetidos', icon: 'send', path: '/submissoes', visible: !auth.isAdmin },
    { route: 'filled', label: 'Preenchidos', icon: 'check-square', path: '/preenchidos', visible: auth.isAdmin },
    { route: 'users', label: 'Usuários', icon: 'users', path: '/usuarios', visible: auth.isAdmin },
  ]
  return all.filter((item) => item.visible)
})

const themeLabel = computed(() => theme.theme === 'dark' ? 'Tema claro' : 'Tema escuro')
const collapseLabel = computed(() => collapsed.value ? 'Expandir menu' : 'Recolher menu')

function syncRoute() {
  routePath.value = location.pathname
}

function navigate(path: string) {
  if (location.pathname !== path) history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  localStorage.setItem(COLLAPSED_KEY, collapsed.value ? '1' : '0')
  userMenuOpen.value = false
}

function closeUserMenu() {
  userMenuOpen.value = false
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!userMenu.value?.contains(event.target as Node)) closeUserMenu()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeUserMenu()
}

// Os listeners globais só existem enquanto o submenu está aberto.
watch(userMenuOpen, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

function toggleTheme() {
  theme.toggle()
  closeUserMenu()
}

function openApiKeys() {
  closeUserMenu()
  apiKeyManager.value?.open()
}

onMounted(async () => {
  window.addEventListener('popstate', syncRoute)
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

onBeforeUnmount(() => {
  window.removeEventListener('popstate', syncRoute)
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<template>
  <aside class="app-sidebar" :class="{ collapsed }" aria-label="Menu principal">
    <div class="app-sidebar-brand">
      <span class="app-brand-mark" aria-hidden="true"><UiIcon name="file-text" /></span>
      <span v-if="!collapsed" class="app-brand-copy">
        <h1 class="app-brand-title">{{ brandTitle }}</h1>
        <span class="app-brand-subtitle">{{ brandSubtitle }}</span>
      </span>
    </div>

    <button
      type="button"
      class="app-sidebar-collapse"
      :title="collapseLabel"
      :aria-label="collapseLabel"
      :aria-expanded="!collapsed"
      @click="toggleCollapsed"
    >
      <UiIcon :name="collapsed ? 'chevron-right' : 'chevron-left'" />
      <span v-if="!collapsed">Recolher</span>
    </button>

    <nav class="app-sidebar-nav" aria-label="Navegação">
      <button
        v-for="item in items"
        :key="item.route"
        type="button"
        :class="{ active: activeRoute === item.route }"
        :title="collapsed ? item.label : undefined"
        :aria-current="activeRoute === item.route ? 'page' : undefined"
        @click="navigate(item.path)"
      >
        <UiIcon :name="item.icon" />
        <span v-if="!collapsed">{{ item.label }}</span>
      </button>
    </nav>

    <div class="app-sidebar-footer">
      <div ref="userMenu" class="app-sidebar-user-menu">
        <button
          type="button"
          class="app-sidebar-user"
          :title="auth.displayName"
          aria-haspopup="menu"
          :aria-expanded="userMenuOpen"
          @click="userMenuOpen = !userMenuOpen"
        >
          <UiIcon name="user" />
          <span v-if="!collapsed">{{ auth.displayName }}</span>
          <UiIcon v-if="!collapsed" name="chevron-down" class="app-sidebar-user-caret" />
        </button>

        <div v-if="userMenuOpen" class="app-sidebar-user-popup" role="menu">
          <button type="button" role="menuitem" @click="toggleTheme">
            <UiIcon :name="theme.theme === 'dark' ? 'sun' : 'moon'" />
            <span>{{ themeLabel }}</span>
          </button>
          <button v-if="auth.isAdmin" type="button" role="menuitem" @click="openApiKeys">
            <UiIcon name="key" />
            <span>API Key</span>
          </button>
        </div>
      </div>

      <button
        type="button"
        class="app-sidebar-danger"
        :title="collapsed ? 'Sair' : undefined"
        @click="auth.logout()"
      >
        <UiIcon name="log-out" />
        <span v-if="!collapsed">Sair</span>
      </button>
    </div>

    <ApiKeyManager v-if="auth.isAdmin" ref="apiKeyManager" />
  </aside>
</template>
