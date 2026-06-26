<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import { useModalsStore } from '../stores/modals'
import PdfPreview from './PdfPreview.vue'
import FieldsSidebar from './FieldsSidebar.vue'

const context = useContextStore()
const docStore = useDocumentStore()
const modals = useModalsStore()
const preview = ref<InstanceType<typeof PdfPreview> | null>(null)
const fullscreenLabel = ref('⛶ Tela cheia')
const documentName = ref('')
const categoryValue = ref('')

watch(
  () => docStore.currentDocumentName,
  (name) => (documentName.value = name),
)
watch(
  () => docStore.currentCategoryId,
  (id) => (categoryValue.value = id || ''),
)

watch(
  () => docStore.previewUrl,
  (url) => {
    if (url) docStore.loadPreview().catch((error) => (docStore.status = (error as Error).message))
  },
)

onMounted(() => {
  document.addEventListener('fullscreenchange', () => {
    fullscreenLabel.value = document.fullscreenElement ? 'Sair da tela cheia' : '⛶ Tela cheia'
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

async function saveDocumentName() {
  if (!docStore.currentDocumentId) return
  await docStore.saveDocumentName(docStore.currentDocumentId, documentName.value)
}

async function applyCategory() {
  await docStore.applyCategory(categoryValue.value || null)
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

function scrollTo(id: string) {
  preview.value?.scrollToElement(id)
}

function openValue(index: number) {
  preview.value?.openFieldValue(index)
}
</script>

<template>
  <section class="card result" :class="{ show: docStore.resultVisible }">
    <div class="result-heading">
      <div><small>Resultado</small><h2>{{ docStore.currentDocumentName || 'Documento' }}</h2></div>
      <button type="button" class="text-edit-button" :class="{ active: docStore.textEditMode }" :disabled="!docStore.currentDocumentId" @click="toggleTextEdit">
        {{ docStore.textEditMode ? 'Finalizar edição' : 'Editar textos' }}
      </button>
      <button type="button" class="text-save-button" :disabled="!docStore.currentDocumentId || !docStore.textEditDirty" @click="saveText">Salvar textos</button>
      <button type="button" class="text-discard-button" :disabled="!docStore.textEditDirty" @click="discardText">Descartar textos</button>
      <button type="button" class="fullscreen-button" :disabled="!docStore.previewUrl" @click="toggleFullscreen">{{ fullscreenLabel }}</button>
    </div>
    <div class="document-controls">
      <label>Nome do documento
        <input v-model="documentName" maxlength="255" aria-label="Nome do documento" :disabled="!docStore.isEditableDocument" @keydown.enter.prevent="saveDocumentName">
      </label>
      <button type="button" :disabled="!docStore.isEditableDocument" @click="saveDocumentName">Alterar nome</button>
      <label>Categoria
        <select v-model="categoryValue" aria-label="Categoria do documento" :disabled="!docStore.isEditableDocument">
          <option value="">Sem categoria</option>
          <option v-for="category in context.categories" :key="category.category_id" :value="category.category_id">{{ category.name }}</option>
        </select>
      </label>
      <button type="button" :disabled="!docStore.isEditableDocument" @click="applyCategory">Alterar categoria</button>
    </div>
    <div class="version-controls" :class="{ show: docStore.availableVersions.length > 0 }">
      <label>Versão
        <select :value="docStore.currentVersion" aria-label="Selecionar versão do documento" @change="onVersionChange(Number(($event.target as HTMLSelectElement).value))">
          <option v-for="item in docStore.availableVersions" :key="item.version" :value="item.version">
            v{{ item.version }}{{ item.is_current ? ' (padrão)' : '' }}{{ item.deprecated ? ' (deprecated)' : '' }}
          </option>
        </select>
      </label>
      <button type="button" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current || selectedVersionInfo.deprecated" @click="setCurrentVersion(docStore.currentVersion!)">Definir como padrão</button>
      <button type="button" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current" @click="toggleDeprecated(docStore.currentVersion!, !selectedVersionInfo?.deprecated)">
        {{ selectedVersionInfo?.deprecated ? 'Restaurar versão' : 'Marcar como deprecated' }}
      </button>
      <button type="button" class="button-danger" :disabled="!selectedVersionInfo || selectedVersionInfo.is_current || docStore.availableVersions.length <= 1" @click="deleteVersion(docStore.currentVersion!)">Excluir versão</button>
      <span class="version-note">{{ versionNote }}</span>
    </div>
    <div class="layout">
      <PdfPreview ref="preview" @save-text-requested="saveText" />
      <FieldsSidebar @scroll-to="scrollTo" @open-value="openValue" />
    </div>
  </section>
</template>
