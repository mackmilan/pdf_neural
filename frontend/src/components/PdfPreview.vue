<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useDocumentStore } from '../stores/document'
import { usePreviewRuntime } from '../composables/usePreviewRuntime'
import { useTextEditing } from '../composables/useTextEditing'

const docStore = useDocumentStore()
const runtime = usePreviewRuntime()
const textEditing = useTextEditing()
const iframe = ref<HTMLIFrameElement | null>(null)

function contentDocument(): Document | null {
  return iframe.value?.contentDocument || null
}

function prepareRuntime() {
  const doc = contentDocument()
  doc?.documentElement.removeAttribute('data-field-editor-ready')
  runtime.renderPreviewFields(doc)
  runtime.installDrawingHandlers(doc)
  textEditing.installTextEditing(doc, requestSave)
}

function requestSave() {
  emitSaveRequest()
}

const emit = defineEmits<{ saveTextRequested: [] }>()
function emitSaveRequest() {
  emit('saveTextRequested')
}

watch(
  () => docStore.previewHtml,
  (html) => {
    if (iframe.value) iframe.value.srcdoc = html
  },
)

watch(
  () => docStore.currentFields,
  () => {
    runtime.renderPreviewFields(contentDocument())
  },
  { deep: true },
)

watch(
  () => docStore.formValues,
  () => {
    runtime.renderFormValues(contentDocument())
  },
  { deep: true },
)

function toggleTextEdit() {
  textEditing.setTextEditMode(contentDocument(), !docStore.textEditMode, requestSave)
}

function discardTextEdits() {
  docStore.textEditDirty = false
  docStore.textEditMode = false
  if (iframe.value) iframe.value.srcdoc = docStore.previewHtml
}

function serializeForSave(): string {
  return textEditing.serializedPreviewHtml(contentDocument())
}

async function requestFullscreen() {
  if (document.fullscreenElement) {
    await document.exitFullscreen()
    return
  }
  if (iframe.value?.requestFullscreen) {
    await iframe.value.requestFullscreen()
  } else {
    throw new Error('Tela cheia não é suportada neste navegador.')
  }
}

function scrollToElement(id: string) {
  const doc = contentDocument()
  if (!iframe.value || !doc) return
  iframe.value.contentWindow!.location.hash = id
  const el = doc.getElementById(id)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function openFieldValue(index: number) {
  runtime.openFieldValue(contentDocument(), index)
}

defineExpose({ toggleTextEdit, discardTextEdits, serializeForSave, requestFullscreen, scrollToElement, openFieldValue })

watch(
  () => docStore.resultVisible,
  async (visible) => {
    if (visible) await nextTick()
  },
)
</script>

<template>
  <iframe ref="iframe" class="preview" title="Prévia do documento convertido" allowfullscreen @load="prepareRuntime"></iframe>
</template>
