<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDocumentStore } from '../stores/document'
import PdfPreview from './PdfPreview.vue'
import ViewerTopMenu from './ViewerTopMenu.vue'

const props = defineProps<{ submissionId: string }>()
const auth = useAuthStore()
const documentStore = useDocumentStore()
const loading = ref(true)
const generatingPdf = ref(false)
const error = ref('')
const pdfError = ref('')
const preview = ref<{ generatePdf: (filename?: string) => Promise<void> } | null>(null)
const submission = ref<{
  submission_id: string
  values: Record<string, unknown>
  created_at?: string
  subject?: string
  email?: string
} | null>(null)

const documentName = computed(() => documentStore.currentDocumentName || 'Documento preenchido')
function filenamePart(value: string, fallback: string): string {
  const normalized = value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return normalized || fallback
}

function localDatePart(value?: string): string {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return new Date().toISOString().slice(0, 10)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const pdfFilename = computed(() => {
  const user = filenamePart(
    submission.value?.email || auth.displayName || submission.value?.subject || '',
    'usuario',
  )
  const date = localDatePart(submission.value?.created_at)
  const document = filenamePart(documentName.value.replace(/\.pdf$/i, ''), 'documento')
  return `${user}_${date}_${document}.pdf`
})
const createdAt = computed(() => {
  if (!submission.value?.created_at) return ''
  const date = new Date(submission.value.created_at)
  return Number.isNaN(date.getTime()) ? submission.value.created_at : date.toLocaleString()
})
const filledFields = computed(() =>
  documentStore.currentFields.map((field) => ({
    name: field.name,
    label: field.label,
    value: documentStore.formValues[field.name],
  })),
)

function displayValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não'
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

async function generateSubmissionPdf() {
  pdfError.value = ''
  generatingPdf.value = true
  try {
    await preview.value?.generatePdf(pdfFilename.value)
  } catch (cause) {
    pdfError.value = (cause as Error).message
  } finally {
    generatingPdf.value = false
  }
}

async function loadSubmission() {
  loading.value = true
  error.value = ''
  documentStore.reset()
  try {
    const response = await auth.apiFetch(`/api/viewer/submissions/${encodeURIComponent(props.submissionId)}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || 'Não foi possível carregar a submissão.')
    submission.value = data.submission
    documentStore.displayResult(data, { refreshVersions: false })
    documentStore.formValues = { ...(data.submission?.values || {}) }
    await documentStore.loadPreview()
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(loadSubmission)
</script>

<template>
  <main class="viewer-page">
    <ViewerTopMenu :active-route="auth.isAdmin ? 'filled' : 'submissions'" />

    <header class="viewer-header">
      <div>
        <span class="viewer-kicker">Submissão</span>
        <h1>{{ documentName }}</h1>
      </div>
      <div class="viewer-session">
        <span>{{ auth.displayName }}</span>
        <button type="button" class="button-secondary" :disabled="loading || generatingPdf || !documentStore.previewHtml" @click="generateSubmissionPdf">
          {{ generatingPdf ? 'Gerando...' : 'Gerar PDF' }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="viewer-message">Carregando submissão...</p>
    <p v-else-if="error && !documentStore.previewHtml" class="viewer-message viewer-error">{{ error }}</p>

    <div v-else class="viewer-layout">
      <section class="viewer-document card">
        <PdfPreview ref="preview" readonly-geometry readonly-values />
      </section>
      <aside class="viewer-fields card">
        <h2>Dados salvos</h2>
        <p v-if="pdfError" class="viewer-error">{{ pdfError }}</p>
        <p class="status">Protocolo: {{ submission?.submission_id }}</p>
        <p v-if="createdAt" class="status">Enviado em: {{ createdAt }}</p>
        <p v-if="submission?.email" class="status">Responsável: {{ submission.email }}</p>

        <div v-if="!filledFields.length" class="viewer-message">Esta submissão não possui campos.</div>
        <dl v-else class="submission-values">
          <div v-for="field in filledFields" :key="field.name" class="submission-value">
            <dt>{{ field.label }}</dt>
            <dd>{{ displayValue(field.value) }}</dd>
          </div>
        </dl>
      </aside>
    </div>
  </main>
</template>
