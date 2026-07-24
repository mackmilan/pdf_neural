<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDocumentStore } from '../stores/document'
import { buildPageFieldTree } from '../composables/fieldTree'
import PdfPreview from './PdfPreview.vue'
import ViewerTopMenu from './ViewerTopMenu.vue'
import type { FieldTreeGroup, SubmissionDetail } from '../types'

const props = defineProps<{ submissionId: string }>()
const auth = useAuthStore()
const documentStore = useDocumentStore()
const loading = ref(true)
const generatingPdf = ref(false)
const error = ref('')
const pdfError = ref('')
const preview = ref<{ generatePdf: (filename?: string) => Promise<void> } | null>(null)
const submission = ref<SubmissionDetail | null>(null)

const documentName = computed(() => documentStore.currentDocumentName || 'Documento preenchido')
const topbarChips = computed(() => [
  submission.value?.submission_id ? `Protocolo ${submission.value.submission_id}` : '',
  createdAt.value ? `Enviado em ${createdAt.value}` : '',
].filter(Boolean))
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
const pageTreeNodes = computed(() => buildPageFieldTree(documentStore.currentFields))

function displayValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não'
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function isSelectedValue(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1
  if (typeof value !== 'string') return false
  return ['true', '1', 'sim', 'yes', 'on'].includes(value.trim().toLowerCase())
}

function visibleGroupFields(group: FieldTreeGroup) {
  if (!group.fields.every(({ field }) => field.type === 'checkbox')) return group.fields
  return group.fields.filter(({ field }) => isSelectedValue(documentStore.formValues[field.name]))
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
    <ViewerTopMenu
      eyebrow="Submissão"
      :title="documentName"
      context="Dados salvos"
      :chips="topbarChips"
    >
      <template #actions>
        <button type="button" class="button-secondary" :disabled="loading || generatingPdf || !documentStore.previewHtml" @click="generateSubmissionPdf">
          {{ generatingPdf ? 'Gerando...' : 'Gerar PDF' }}
        </button>
      </template>
    </ViewerTopMenu>

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
        <div v-else class="submission-values">
          <div v-for="pageGroup in pageTreeNodes" :key="`page-${pageGroup.page}`" class="viewer-page-section">
            <div class="viewer-page-header">
              <h3>Página {{ pageGroup.page }}</h3>
              <span class="viewer-page-count">{{ pageGroup.totalCount }} campo(s)</span>
            </div>
            <dl>
              <template v-for="node in pageGroup.nodes" :key="node.kind === 'group' ? node.groupId : node.field.name">
                <div v-if="node.kind === 'group'" class="submission-value-group">
                  <dt class="submission-value-group-title">
                    <strong>{{ node.label }}</strong>
                    <small>{{ visibleGroupFields(node).length || 0 }} selecionado(s)</small>
                  </dt>
                  <dd class="submission-value-group-children">
                    <dl v-if="visibleGroupFields(node).length">
                      <div v-for="{ field } in visibleGroupFields(node)" :key="field.name" class="submission-value submission-value-child">
                        <dt>{{ field.label }}</dt>
                        <dd v-if="field.type === 'checkbox'">Selecionado</dd>
                        <dd v-else>{{ displayValue(documentStore.formValues[field.name]) }}</dd>
                      </div>
                    </dl>
                    <span v-else class="submission-value-empty">-</span>
                  </dd>
                </div>
                <div v-else class="submission-value">
                  <dt>{{ node.field.label }}</dt>
                  <dd>{{ displayValue(documentStore.formValues[node.field.name]) }}</dd>
                </div>
              </template>
            </dl>
          </div>
        </div>
      </aside>
    </div>
  </main>
</template>
