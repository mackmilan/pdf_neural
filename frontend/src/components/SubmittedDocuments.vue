<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import ViewerTopMenu from './ViewerTopMenu.vue'

interface SubmissionListItem {
  submission_id: string
  document_name: string
  document_id?: string
  job_id?: string
  version?: number
  created_at?: string
  email?: string
}

const auth = useAuthStore()
const loading = ref(true)
const error = ref('')
const submissions = ref<SubmissionListItem[]>([])

const title = computed(() => auth.displayName || 'Usuário')
const topbarChips = computed(() => [
  `${submissions.value.length} submiss${submissions.value.length === 1 ? 'ão' : 'ões'}`,
])

function formatDate(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function loadSubmissions() {
  loading.value = true
  error.value = ''
  try {
    const response = await auth.apiFetch('/api/viewer/submissions')
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
      throw new Error(data?.error || `Não foi possível carregar os documentos submetidos. HTTP ${response.status}`)
    }
    if (!Array.isArray(data)) {
      throw new Error('Resposta inválida ao carregar documentos submetidos.')
    }
    submissions.value = data
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

function openSubmission(submissionId: string) {
  history.pushState({}, '', `/submissao/${submissionId}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

onMounted(loadSubmissions)
</script>

<template>
  <main class="submitted-page">
    <ViewerTopMenu
      :active-route="auth.isAdmin ? 'filled' : 'submissions'"
      eyebrow="Documentos submetidos"
      :title="title"
      context="Histórico"
      :chips="topbarChips"
    >
      <template #actions>
        <button type="button" class="button-secondary" @click="loadSubmissions">Atualizar</button>
      </template>
    </ViewerTopMenu>

    <section class="card submitted-list">
      <p v-if="loading" class="viewer-message">Carregando documentos submetidos...</p>
      <p v-else-if="error" class="viewer-message viewer-error">{{ error }}</p>
      <p v-else-if="!submissions.length" class="viewer-message">Nenhum documento submetido encontrado.</p>
      <template v-else>
        <button
          v-for="submission in submissions"
          :key="submission.submission_id"
          type="button"
          class="submitted-item"
          @click="openSubmission(submission.submission_id)"
        >
          <span>
            <strong>{{ submission.document_name }}</strong>
            <small>Protocolo: {{ submission.submission_id }}</small>
          </span>
          <small>{{ formatDate(submission.created_at) }}</small>
        </button>
      </template>
    </section>
  </main>
</template>
