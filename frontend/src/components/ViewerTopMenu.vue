<script setup lang="ts">
// A navegação e as ações de sessão vivem no AppSidebar; aqui fica só o
// cabeçalho da página: título, contexto, chips e ações próprias da tela.
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

    <div v-if="props.title || props.context || props.chips?.length || $slots.actions" class="app-context-row">
      <div class="app-breadcrumbs" aria-label="Contexto atual">
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
