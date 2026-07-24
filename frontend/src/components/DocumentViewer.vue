<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDocumentStore } from '../stores/document'
import { buildFieldTree } from '../composables/fieldTree'
import PdfPreview from './PdfPreview.vue'
import ViewerTopMenu from './ViewerTopMenu.vue'
import type { Field } from '../types'

const props = defineProps<{ documentId: string }>()
const auth = useAuthStore()
const documentStore = useDocumentStore()
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const success = ref('')
const preview = ref<{ scrollToField: (fieldName: string, optionValue?: string) => void } | null>(null)

const documentName = computed(() => documentStore.currentDocumentName || 'Documento convertido')
const fieldTreeNodes = computed(() => buildFieldTree(documentStore.currentFields))
const topbarChips = computed(() => [
  `${documentStore.currentFields.length} campo${documentStore.currentFields.length === 1 ? '' : 's'}`,
  documentStore.currentSingleSubmissionPerUser ? 'Preenchimento único' : 'Múltiplos envios',
])

function inputType(field: Field): string {
  if (field.mask || field.type === 'select' || field.type === 'textarea') return 'text'
  return field.type
}

function scrollToField(field: Field, optionValue?: string) {
  void nextTick(() => {
    preview.value?.scrollToField(field.name, optionValue)
  })
}

function openSubmission(submissionId: string) {
  history.pushState({}, '', `/submissao/${submissionId}`)
  window.dispatchEvent(new PopStateEvent('popstate'))
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
    openSubmission(data.submission_id)
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
    <ViewerTopMenu
      eyebrow="Documento"
      :title="documentName"
      context="Preenchimento"
      :chips="topbarChips"
    />

    <p v-if="loading" class="viewer-message">Carregando documento…</p>
    <p v-else-if="error && !documentStore.previewHtml" class="viewer-message viewer-error">{{ error }}</p>

    <form v-else class="viewer-layout" @submit.prevent="submitResult">
      <section class="viewer-document card">
        <PdfPreview ref="preview" readonly-geometry />
      </section>
      <aside class="viewer-fields card">
        <h2>Preenchimento</h2>
        <p class="status">Preencha os campos e salve o resultado.</p>
        <p v-if="documentStore.currentSingleSubmissionPerUser" class="status">
          Este documento permite apenas um preenchimento por usuário.
        </p>
        <div v-if="!documentStore.currentFields.length" class="viewer-message">Este documento não possui campos.</div>
        <template v-for="node in fieldTreeNodes" :key="node.kind === 'group' ? node.groupId : node.field.name">
          <div v-if="node.kind === 'group'" class="viewer-field-group">
            <div class="viewer-field-group-header">
              <strong>{{ node.label }}</strong>
              <small>{{ node.fields.length }} campo(s)</small>
            </div>
            <div class="viewer-field-group-children">
              <div v-for="{ field } in node.fields" :key="field.name" class="viewer-control viewer-control-child" @focusin="scrollToField(field)">
                <label v-if="field.type === 'checkbox'" class="viewer-checkbox">
                  <input
                    v-model="documentStore.formValues[field.name]"
                    type="checkbox"
                    :required="field.required"
                    @change="scrollToField(field)"
                  />
                  {{ field.label }}<span v-if="field.required"> *</span>
                </label>
                <div
                  v-else-if="field.type === 'radio'"
                  class="viewer-radio-group"
                  role="group"
                  :aria-label="field.label"
                >
                  <p class="viewer-radio-title">
                    {{ field.label }}<span v-if="field.required" aria-hidden="true"> *</span>
                  </p>
                  <label v-for="option in field.options || []" :key="option" class="viewer-radio-option">
                    <input
                      v-model="documentStore.formValues[field.name]"
                      type="radio"
                      :name="field.name"
                      :value="option"
                      :required="field.required"
                      @change="scrollToField(field, option)"
                    />
                    <span>{{ option }}</span>
                  </label>
                </div>
                <label v-else>
                  {{ field.label }}<span v-if="field.required"> *</span>
                  <textarea
                    v-if="field.type === 'textarea'"
                    v-model="documentStore.formValues[field.name]"
                    :required="field.required"
                    @input="scrollToField(field)"
                  ></textarea>
                  <input
                    v-else
                    v-model="documentStore.formValues[field.name]"
                    :type="inputType(field)"
                    :required="field.required"
                    :min="field.min"
                    :max="field.max"
                    @input="scrollToField(field)"
                  />
                </label>
              </div>
            </div>
          </div>
          <div v-else class="viewer-control" @focusin="scrollToField(node.field)">
            <label v-if="node.field.type === 'checkbox'" class="viewer-checkbox">
              <input
                v-model="documentStore.formValues[node.field.name]"
                type="checkbox"
                :required="node.field.required"
                @change="scrollToField(node.field)"
              />
              {{ node.field.label }}<span v-if="node.field.required"> *</span>
            </label>
            <div
              v-else-if="node.field.type === 'radio'"
              class="viewer-radio-group"
              role="group"
              :aria-label="node.field.label"
            >
              <p class="viewer-radio-title">
                {{ node.field.label }}<span v-if="node.field.required" aria-hidden="true"> *</span>
              </p>
              <label v-for="option in node.field.options || []" :key="option" class="viewer-radio-option">
                <input
                  v-model="documentStore.formValues[node.field.name]"
                  type="radio"
                  :name="node.field.name"
                  :value="option"
                  :required="node.field.required"
                  @change="scrollToField(node.field, option)"
                />
                <span>{{ option }}</span>
              </label>
            </div>
            <label v-else>
              {{ node.field.label }}<span v-if="node.field.required"> *</span>
              <textarea
                v-if="node.field.type === 'textarea'"
                v-model="documentStore.formValues[node.field.name]"
                :required="node.field.required"
                @input="scrollToField(node.field)"
              ></textarea>
              <input
                v-else
                v-model="documentStore.formValues[node.field.name]"
                :type="inputType(node.field)"
                :required="node.field.required"
                :min="node.field.min"
                :max="node.field.max"
                @input="scrollToField(node.field)"
              />
            </label>
          </div>
        </template>
        <button type="submit" :disabled="saving || !documentStore.currentFields.length">
          {{ saving ? 'Salvando…' : 'Salvar resultado' }}
        </button>
        <p v-if="success" class="viewer-success">{{ success }}</p>
        <p v-if="error" class="viewer-error">{{ error }}</p>
      </aside>
    </form>
  </main>
</template>
