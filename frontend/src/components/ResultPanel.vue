<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import { useModalsStore } from '../stores/modals'
import type { FormatNorm } from '../types'
import PdfPreview from './PdfPreview.vue'
import FieldsSidebar from './FieldsSidebar.vue'
import UiIcon from './UiIcon.vue'

const context = useContextStore()
const docStore = useDocumentStore()
const modals = useModalsStore()
const preview = ref<InstanceType<typeof PdfPreview> | null>(null)
const activePreviewFieldName = ref<string | null>(null)
const fullscreenLabel = ref('Tela cheia')
const documentName = ref('')
const categoryValue = ref('')
const formatNormValue = ref<FormatNorm | ''>('')
const documentRenderUrl = computed(() =>
  docStore.currentDocumentId ? `/documento/${encodeURIComponent(docStore.currentDocumentId)}` : '',
)

watch(
  () => docStore.currentDocumentName,
  (name) => (documentName.value = name),
)
watch(
  () => docStore.currentCategoryId,
  (id) => (categoryValue.value = id || ''),
)
watch(
  () => docStore.currentFormatNorm,
  (norm) => (formatNormValue.value = norm || ''),
)

watch(
  () => docStore.previewUrl,
  (url) => {
    if (url) docStore.loadPreview().catch((error) => (docStore.status = (error as Error).message))
  },
)

onMounted(() => {
  document.addEventListener('fullscreenchange', () => {
    fullscreenLabel.value = document.fullscreenElement ? 'Sair da tela cheia' : 'Tela cheia'
  })
})

async function toggleFullscreen() {
  try {
    await preview.value?.requestFullscreen()
  } catch (error) {
    docStore.status = (error as Error).message
  }
}

function toggleTextEdit() {
  preview.value?.toggleTextEdit()
}

async function saveText() {
  if (!docStore.currentDocumentId || !docStore.textEditDirty) return
  const html = preview.value?.serializeForSave() || ''
  docStore.textEditMode = false
  await docStore.saveHtmlText(html)
}

async function discardText() {
  if (!docStore.textEditDirty) return
  const confirmed = await modals.showConfirm({
    title: 'Descartar textos editados?',
    message: 'As alterações de texto ainda não salvas serão perdidas.',
    confirmLabel: 'Descartar textos',
    danger: true,
  })
  if (!confirmed) return
  preview.value?.discardTextEdits()
  docStore.status = 'Alterações de texto descartadas.'
}

async function toggleDocumentPageSubmission(event: Event) {
  if (!docStore.currentDocumentId) return
  const enabled = (event.target as HTMLInputElement).checked
  await docStore.setDocumentPageSubmissionAllowed(docStore.currentDocumentId, enabled)
}

async function toggleSingleSubmission(event: Event) {
  if (!docStore.currentDocumentId) return
  const enabled = (event.target as HTMLInputElement).checked
  await docStore.setSingleSubmissionPerUser(docStore.currentDocumentId, enabled)
}

async function onVersionChange(version: number) {
  await docStore.loadVersion(version)
}

async function setCurrentVersion(version: number) {
  const confirmed = await modals.showConfirm({
    title: 'Definir versão padrão?',
    message: `A versão ${version} passará a abrir automaticamente para este documento.`,
    confirmLabel: 'Definir como padrão',
  })
  if (!confirmed) return
  await docStore.setCurrentVersion(version)
}

async function toggleDeprecated(version: number, marking: boolean) {
  const confirmed = await modals.showConfirm({
    title: marking ? 'Marcar versão como deprecated?' : 'Restaurar versão?',
    message: marking
      ? `A versão ${version} continuará no histórico, mas não poderá ser definida como padrão.`
      : `A versão ${version} voltará a poder ser definida como padrão.`,
    confirmLabel: marking ? 'Marcar como deprecated' : 'Restaurar versão',
    danger: marking,
  })
  if (!confirmed) return
  await docStore.toggleDeprecatedVersion(version, marking)
}

async function deleteVersion(version: number) {
  const confirmed = await modals.showConfirm({
    title: 'Excluir versão?',
    message: `A versão ${version} será removida do histórico. Esta ação não pode ser desfeita.`,
    confirmLabel: 'Excluir versão',
    danger: true,
  })
  if (!confirmed) return
  await docStore.deleteVersion(version)
}

const selectedVersionInfo = computed(() => docStore.availableVersions.find((item) => item.version === docStore.currentVersion))
const versionNote = computed(() => {
  const selected = selectedVersionInfo.value
  return selected?.deprecated ? 'Versão obsoleta' : selected?.is_current ? 'Versão padrão atual' : 'Visualizando uma versão anterior'
})
const metadataDirty = computed(
  () =>
    documentName.value !== docStore.currentDocumentName ||
    (categoryValue.value || '') !== (docStore.currentCategoryId || '') ||
    (formatNormValue.value || '') !== (docStore.currentFormatNorm || ''),
)

async function saveDocumentMetadata() {
  if (!docStore.isEditableDocument || !docStore.currentDocumentId) return
  const tasks: Promise<unknown>[] = []
  if (documentName.value !== docStore.currentDocumentName) {
    tasks.push(docStore.saveDocumentName(docStore.currentDocumentId, documentName.value))
  }
  if ((categoryValue.value || '') !== (docStore.currentCategoryId || '')) {
    tasks.push(docStore.applyCategory(categoryValue.value || null))
  }
  if ((formatNormValue.value || '') !== (docStore.currentFormatNorm || '')) {
    tasks.push(docStore.applyFormatNorm(formatNormValue.value || null))
  }
  await Promise.all(tasks)
}

function scrollTo(id: string) {
  preview.value?.scrollToElement(id)
}

function openValue(index: number) {
  preview.value?.openFieldValue(index)
}

function onPreviewFieldSelected(detail: { fieldName: string }) {
  if (activePreviewFieldName.value === detail.fieldName) {
    activePreviewFieldName.value = null
    void nextTick(() => {
      activePreviewFieldName.value = detail.fieldName
    })
    return
  }
  activePreviewFieldName.value = detail.fieldName
}

function openDocumentRender() {
  if (!documentRenderUrl.value) return
  const renderWindow = window.open(documentRenderUrl.value, '_blank')
  if (!renderWindow) {
    docStore.status = 'O navegador bloqueou a nova aba. Permita pop-ups para abrir a renderização.'
    return
  }
  renderWindow.opener = null
}
</script>

<template>
  <section class="card result" :class="{ show: docStore.resultVisible }">
    <div class="result-heading">
      <div><small>Resultado</small><h2>{{ docStore.currentDocumentName || 'Documento' }}</h2></div>
      <button type="button" class="render-page-button button-with-icon" :disabled="!documentRenderUrl" aria-label="Abrir renderização do documento em nova aba" @click="openDocumentRender">
        <UiIcon name="external-link" />
        Abrir renderização
      </button>
      <details class="result-actions-menu">
        <summary aria-label="Mais ações"><UiIcon name="more-horizontal" /></summary>
        <div class="result-actions-popover">
          <button type="button" class="text-edit-button button-with-icon" :class="{ active: docStore.textEditMode }" :disabled="!docStore.currentDocumentId" @click="toggleTextEdit">
            <UiIcon name="edit" />
            {{ docStore.textEditMode ? 'Finalizar edição' : 'Editar textos' }}
          </button>
          <button type="button" class="text-save-button button-with-icon" :disabled="!docStore.currentDocumentId || !docStore.textEditDirty" @click="saveText">
            <UiIcon name="save" />
            Salvar textos
          </button>
          <button type="button" class="text-discard-button button-with-icon" :disabled="!docStore.textEditDirty" @click="discardText">
            <UiIcon name="refresh" />
            Descartar textos
          </button>
          <button type="button" class="fullscreen-button button-with-icon" :disabled="!docStore.previewUrl" @click="toggleFullscreen">
            <UiIcon name="maximize" />
            {{ fullscreenLabel }}
          </button>
        </div>
      </details>
    </div>

    <div class="metadata-panel">
      <label>Nome do documento
        <input v-model="documentName" maxlength="255" aria-label="Nome do documento" :disabled="!docStore.isEditableDocument" @keydown.enter.prevent="saveDocumentMetadata">
      </label>
      <label>Categoria
        <select v-model="categoryValue" aria-label="Categoria do documento" :disabled="!docStore.isEditableDocument">
          <option value="">Sem categoria</option>
          <option v-for="category in context.categories" :key="category.category_id" :value="category.category_id">{{ category.name }}</option>
        </select>
      </label>
      <label>Norma de formatação
        <select v-model="formatNormValue" aria-label="Norma de formatação do documento" :disabled="!docStore.isEditableDocument">
          <option value="">Nenhuma</option>
          <option value="abnt">ABNT (NBR 14724)</option>
          <option value="apa">APA (7th edition)</option>
        </select>
      </label>

      <div class="version-controls" :class="{ show: docStore.availableVersions.length > 0 }">
        <label>Versão
          <select :value="docStore.currentVersion" aria-label="Selecionar versão do documento" @change="onVersionChange(Number(($event.target as HTMLSelectElement).value))">
            <option v-for="item in docStore.availableVersions" :key="item.version" :value="item.version">
              v{{ item.version }}{{ item.is_current ? ' (padrão)' : '' }}{{ item.deprecated ? ' (deprecated)' : '' }}
            </option>
          </select>
        </label>
        <span class="version-note">{{ versionNote }}</span>
        <details class="version-actions-menu">
          <summary aria-label="Ações da versão"><UiIcon name="more-horizontal" /></summary>
          <div class="version-actions-popover">
            <button type="button" class="button-with-icon" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current || selectedVersionInfo.deprecated" @click="setCurrentVersion(docStore.currentVersion!)">
              <UiIcon name="check" />
              Definir como padrão
            </button>
            <button type="button" class="button-with-icon" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current" @click="toggleDeprecated(docStore.currentVersion!, !selectedVersionInfo?.deprecated)">
              <UiIcon name="archive" />
              {{ selectedVersionInfo?.deprecated ? 'Restaurar versão' : 'Marcar como deprecated' }}
            </button>
            <button type="button" class="button-danger button-with-icon" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current || docStore.availableVersions.length <= 1" @click="deleteVersion(docStore.currentVersion!)">
              <UiIcon name="trash" />
              Excluir versão
            </button>
          </div>
        </details>
      </div>

      <button type="button" class="metadata-save-button button-with-icon" :disabled="!docStore.isEditableDocument || !metadataDirty" @click="saveDocumentMetadata">
        <UiIcon name="save" />
        Salvar alterações
      </button>

      <div class="submission-controls">
        <label>
          <input
            type="checkbox"
            :checked="docStore.currentAllowDocumentPageSubmission"
            :disabled="!docStore.isEditableDocument"
            @change="toggleDocumentPageSubmission"
          >
          Permitir preenchimento pela página do documento
        </label>
        <label>
          <input
            type="checkbox"
            :checked="docStore.currentSingleSubmissionPerUser"
            :disabled="!docStore.isEditableDocument"
            @change="toggleSingleSubmission"
          >
          Preenchimento único por usuário
        </label>
      </div>
    </div>

    <div class="layout">
      <PdfPreview ref="preview" @save-text-requested="saveText" @field-selected="onPreviewFieldSelected" />
      <FieldsSidebar :active-field-name="activePreviewFieldName" @scroll-to="scrollTo" @open-value="openValue" />
    </div>
  </section>
</template>
