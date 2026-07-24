<script setup lang="ts">
// A navegação e as ações de sessão vivem no AppSidebar; aqui fica só o
// cabeçalho da página: seletor de contexto, título, chips e ações da tela.
import ContextSelector from './ContextSelector.vue'

const props = defineProps<{
  eyebrow?: string
  title?: string
  context?: string
  chips?: string[]
}>()
</script>

<template>
  <header class="app-topbar viewer-top-menu">
    <div class="app-topbar-main">
      <h2 class="app-page-title">{{ props.eyebrow || props.title }}</h2>
      <p class="app-topbar-description">
        Extraia campos, tipos, imagens e logotipos em documentos.
      </p>
    </div>

    <div class="app-context-row">
      <ContextSelector />

      <div v-if="props.title || props.context" class="app-breadcrumbs" aria-label="Contexto atual">
        <strong v-if="props.title">{{ props.title }}</strong>
        <span v-if="props.title && props.context" aria-hidden="true">/</span>
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
