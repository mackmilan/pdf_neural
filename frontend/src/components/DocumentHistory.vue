<script setup lang="ts">
import { computed } from 'vue'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import { useModalsStore } from '../stores/modals'
import type { DocumentHistoryItem } from '../types'

const context = useContextStore()
const doc = useDocumentStore()
const modals = useModalsStore()

const visible = computed(() => context.tenantId)

function search() {
  context.historyPage = 1
  context.loadHistory()
}

function clearFilter() {
  context.historyNameFilter = ''
  context.historyPage = 1
  context.loadHistory()
}

function previousPage() {
  if (context.historyPage > 1) {
    context.historyPage -= 1
    context.loadHistory()
  }
}

function nextPage() {
  context.historyPage += 1
  context.loadHistory()
}

function open(item: DocumentHistoryItem) {
  doc.loadJob(item.document_id || item.job_id)
}

async function remove(item: DocumentHistoryItem) {
  const confirmed = await modals.showConfirm({
    title: 'Excluir documento?',
    message: 'O documento e todos os dados associados serão removidos. Esta ação não pode ser desfeita.',
    confirmLabel: 'Excluir documento',
    danger: true,
  })
  if (!confirmed) return
  await doc.deleteDocument(item.document_id || item.job_id)
}

async function rename(item: DocumentHistoryItem) {
  if (!item.document_id) return
  const name = await modals.showTextInput({
    title: 'Renomear documento',
    message: 'Informe o novo nome do documento.',
    label: 'Nome do documento',
    value: item.metadata?.filename || '',
    confirmLabel: 'Renomear',
  })
  if (name !== null) await doc.saveDocumentName(item.document_id, name)
}

function title(item: DocumentHistoryItem): string {
  return item.metadata?.filename || item.metadata?.pdf_url || item.job_id
}
</script>

<template>
  <details v-if="visible" class="card collapsible-card" open>
    <summary><h3>Documentos</h3></summary>
    <div class="collapsible-content">
      <form class="history-toolbar" @submit.prevent="search">
        <label>Filtrar por nome
          <input v-model="context.historyNameFilter" maxlength="255" placeholder="Digite o nome do documento" autocomplete="off">
        </label>
        <button type="submit">Buscar</button>
        <button type="button" class="button-secondary" @click="clearFilter">Limpar</button>
      </form>
      <div class="history-list">
        <template v-if="context.historyError">
          <p class="history-empty">Erro ao carregar documentos: {{ context.historyError }}</p>
        </template>
        <template v-else-if="context.historyItems.length">
          <div v-for="item in context.historyItems" :key="item.document_id || item.job_id" class="history-item" @click="open(item)">
            <button type="button" class="history-action history-delete" @click.stop="remove(item)" :aria-label="`Excluir ${title(item)}`">Excluir</button>
            <button v-if="item.document_id" type="button" class="history-action history-rename" @click.stop="rename(item)" :aria-label="`Renomear ${title(item)}`">Renomear</button>
            <h4>{{ title(item) }}</h4>
            <small>{{ new Date(item.created_at).toLocaleString() }}</small><br>
            <small>{{ context.groupName(item.group_id) }}</small><br>
            <small>{{ context.categoryName(item.category_id) }}</small><br>
            <small>v{{ item.current_version || item.version || 1 }} · {{ item.fields.length }} campos · {{ item.tables.length }} tabelas</small>
          </div>
        </template>
        <template v-else-if="context.historyLoaded">
          <p class="history-empty">{{ context.historyNameFilter.trim() ? 'Nenhum documento corresponde ao nome informado.' : 'Nenhum documento encontrado neste contexto.' }}</p>
        </template>
      </div>
      <div class="pagination" v-if="context.historyTotalPages > 1">
        <button type="button" class="button-secondary" :disabled="context.historyPage <= 1" @click="previousPage">Anterior</button>
        <span class="pagination-status">Página {{ context.historyPage }} de {{ context.historyTotalPages }} · {{ context.historyTotal }} documento(s)</span>
        <button type="button" class="button-secondary" :disabled="context.historyPage >= context.historyTotalPages" @click="nextPage">Próxima</button>
      </div>
    </div>
  </details>
</template>
