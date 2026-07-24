<script setup lang="ts">
import { computed } from 'vue'
import { useThemeStore } from '../stores/theme'
import UiIcon from './UiIcon.vue'

const theme = useThemeStore()
const label = computed(() => theme.theme === 'dark' ? 'Tema claro' : 'Tema escuro')
</script>

<template>
  <button
    type="button"
    class="app-icon-button theme-toggle"
    :title="label"
    :aria-label="label"
    :aria-pressed="theme.theme === 'light'"
    @click="theme.toggle()"
  >
    <UiIcon :name="theme.theme === 'dark' ? 'sun' : 'moon'" />
  </button>
</template>
