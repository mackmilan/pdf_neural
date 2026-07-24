<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useThemeStore } from '../stores/theme'
import ApiKeyManager from './ApiKeyManager.vue'
import UiIcon from './UiIcon.vue'

const auth = useAuthStore()
const theme = useThemeStore()

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const apiKeyManager = ref<InstanceType<typeof ApiKeyManager> | null>(null)

const themeLabel = computed(() => theme.theme === 'dark' ? 'Tema claro' : 'Tema escuro')

function close() {
  open.value = false
}

function toggle() {
  open.value = !open.value
}

function onDocumentPointerDown(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) close()
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

// Os listeners só existem enquanto o popup está aberto.
watch(open, (isOpen) => {
  if (isOpen) {
    document.addEventListener('pointerdown', onDocumentPointerDown)
    document.addEventListener('keydown', onDocumentKeydown)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown)
    document.removeEventListener('keydown', onDocumentKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})

function toggleTheme() {
  theme.toggle()
  close()
}

function openApiKeys() {
  close()
  apiKeyManager.value?.open()
}

function logout() {
  close()
  auth.logout()
}
</script>

<template>
  <div ref="root" class="app-user-menu">
    <button
      type="button"
      class="app-session-user"
      :title="auth.displayName"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click="toggle"
    >
      <UiIcon name="user" />
      <span>{{ auth.displayName }}</span>
      <UiIcon name="chevron-down" class="app-user-menu-caret" />
    </button>

    <div v-if="open" class="app-user-menu-popup" role="menu">
      <button type="button" role="menuitem" @click="toggleTheme">
        <UiIcon :name="theme.theme === 'dark' ? 'sun' : 'moon'" />
        {{ themeLabel }}
      </button>
      <button v-if="auth.isAdmin" type="button" role="menuitem" @click="openApiKeys">
        <UiIcon name="key" />
        API Key
      </button>
      <button type="button" role="menuitem" class="app-user-menu-danger" @click="logout">
        <UiIcon name="log-out" />
        Sair
      </button>
    </div>
  </div>

  <ApiKeyManager v-if="auth.isAdmin" ref="apiKeyManager" />
</template>
