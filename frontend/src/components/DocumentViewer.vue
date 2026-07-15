<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDocumentStore } from '../stores/document'
import PdfPreview from './PdfPreview.vue'
import type { Field } from '../types'

const props = defineProps<{ documentId: string }>()
const auth = useAuthStore()
const documentStore = useDocumentStore()
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref('')

const documentName = computed(() => documentStore.currentDocumentName || 'Documento convertido')

function inputType(field: Field): string {
  if (field.mask || field.type === 'select' || field.type === 'textarea') return 'text'
  return field.type
}

async function loadDocument() {
  loading.value = true
  error.value = ''
  documentStore.reset()
  try {
    const response = await auth.apiFetch(`/api/viewer/documents/${encodeURIComponent(props.documentId)}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || 'Não foi possível carregar o documento.')
    documentStore.displayResult(data, { refreshVersions: false })
    await documentStore.loadPreview()
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    loading.value = false
  }
}

async function submitResult() {
  saving.value = true
  error.value = ''
  success.value = ''
  try {
    const response = await auth.apiFetch(
      `/api/viewer/documents/${encodeURIComponent(props.documentId)}/submissions`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values: documentStore.formValues }),
      },
    )
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || 'Não foi possível salvar o resultado.')
    success.value = `Resultado salvo com sucesso. Protocolo: ${data.submission_id}`
  } catch (cause) {
    error.value = (cause as Error).message
  } finally {
    saving.value = false
  }
}

onMounted(loadDocument)
</script>

<template>
  <main class="viewer-page">
    <header class="viewer-header">
      <div>
        <span class="viewer-kicker">Documento</span>
        <h1>{{ documentName }}</h1>
      </div>
      <div class="viewer-session">
        <span>{{ auth.displayName }}</span>
        <button type="button" class="button-secondary" @click="auth.logout()">Sair</button>
      </div>
    </header>

    <p v-if="loading" class="viewer-message">Carregando documento…</p>
    <p v-else-if="error && !documentStore.previewHtml" class="viewer-message viewer-error">{{ error }}</p>

    <form v-else class="viewer-layout" @submit.prevent="submitResult">
      <section class="viewer-document card">
        <PdfPreview />
      </section>
      <aside class="viewer-fields card">
        <h2>Preenchimento</h2>
        <p class="status">Preencha os campos e salve o resultado.</p>
        <div v-if="!documentStore.currentFields.length" class="viewer-message">Este documento não possui campos.</div>
        <div v-for="field in documentStore.currentFields" :key="field.name" class="viewer-control">
          <label v-if="field.type === 'checkbox'" class="viewer-checkbox">
            <input v-model="documentStore.formValues[field.name]" type="checkbox" :required="field.required" />
            {{ field.label }}<span v-if="field.required"> *</span>
          </label>
          <label v-else>
            {{ field.label }}<span v-if="field.required"> *</span>
            <textarea
              v-if="field.type === 'textarea'"
              v-model="documentStore.formValues[field.name]"
              :required="field.required"
            ></textarea>
            <input
              v-else
              v-model="documentStore.formValues[field.name]"
              :type="inputType(field)"
              :required="field.required"
              :min="field.min"
              :max="field.max"
            />
          </label>
        </div>
        <button type="submit" :disabled="saving || !documentStore.currentFields.length">
          {{ saving ? 'Salvando…' : 'Salvar resultado' }}
        </button>
        <p v-if="success" class="viewer-success">{{ success }}</p>
        <p v-if="error" class="viewer-error">{{ error }}</p>
      </aside>
    </form>
  </main>
</template>
