<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import ViewerTopMenu from './ViewerTopMenu.vue'
import type { AvailableDocument } from '../types'

const auth = useAuthStore()
const loading = ref(true)
const error = ref('')
const documents = ref<AvailableDocument[]>([])

const title = computed(() => auth.displayName || 'Usuário')
const topbarChips = computed(() => [
  `${documents.value.length} documento${documents.value.length === 1 ? '' : 's'}`,
])

function documentKey(document: AvailableDocument): string {
  return document.document_id || document.job_id || document.current_job_id || ''
}

function documentName(document: AvailableDocument): string {
  return document.metadata?.filename || 'Documento disponível'
}

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function loadDocuments() {
  loading.value = true
  error.value = ''
  try {
    const response = await auth.apiFetch('/api/viewer/documents')
    const text = await response.text()
    let data: any = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        const summary = text.trim().replace(/\s+/g, ' ').slice(0, 120)
        throw new Error(`A API não retornou JSON. HTTP ${response.status}: ${summary}`)
      }
    }
    if (!response.ok) {
      throw new Error(data?.error || `Não foi possível carregar os documentos disponíveis. HTTP ${response.status}`)
    }
    if (!Array.isArray(data)) {
      throw new Error('Resposta inválida ao carregar documentos disponíveis.')
    }
    documents.value = data
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

function openDocument(document: AvailableDocument) {
  const id = documentKey(document)
  if (!id) return
  history.pushState({}, '', `/documento/${id}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

onMounted(loadDocuments)
</script>

<template>
  <main class="submitted-page">
    <ViewerTopMenu
      eyebrow="Documentos disponíveis"
      :title="title"
      context="Para preenchimento"
      :chips="topbarChips"
    >
      <template #actions>
        <button type="button" class="button-secondary" @click="loadDocuments">Atualizar</button>
      </template>
    </ViewerTopMenu>

    <section class="card submitted-list">
      <p v-if="loading" class="viewer-message">Carregando documentos disponíveis...</p>
      <p v-else-if="error" class="viewer-message viewer-error">{{ error }}</p>
      <p v-else-if="!documents.length" class="viewer-message">Nenhum documento disponível para submissão.</p>
      <template v-else>
        <button
          v-for="document in documents"
          :key="documentKey(document)"
          type="button"
          class="submitted-item"
          @click="openDocument(document)"
        >
          <span>
            <strong>{{ documentName(document) }}</strong>
            <small>{{ (document.fields || []).length }} campo(s) para preencher</small>
          </span>
          <small>{{ formatDate(document.updated_at || document.created_at) }}</small>
        </button>
      </template>
    </section>
  </main>
</template>
