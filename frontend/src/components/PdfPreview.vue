<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDocumentStore } from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'
import { usePreviewRuntime } from '../composables/usePreviewRuntime'
import { useTextEditing } from '../composables/useTextEditing'

const docStore = useDocumentStore()
const fieldEditor = useFieldEditorStore()
const runtime = usePreviewRuntime()
const textEditing = useTextEditing()
const iframe = ref<HTMLIFrameElement | null>(null)
const props = withDefaults(defineProps<{ fitContentWidth?: boolean; readonlyGeometry?: boolean; readonlyValues?: boolean }>(), {
  fitContentWidth: false,
  readonlyGeometry: false,
  readonlyValues: false,
})
let fitResizeObserver: ResizeObserver | null = null
let fitContentResizeObserver: ResizeObserver | null = null

onMounted(() => {
  if (iframe.value) iframe.value.srcdoc = docStore.previewHtml
})

onUnmounted(() => {
  fitResizeObserver?.disconnect()
  fitContentResizeObserver?.disconnect()
})

function contentDocument(): Document | null {
  return iframe.value?.contentDocument || null
}

function resizePagesToContentWidth(doc: Document | null) {
  if (!doc || !props.fitContentWidth) return
  doc.querySelectorAll<HTMLElement>('.pdf-page-shell').forEach((shell) => {
    const page = shell.querySelector<HTMLElement>('.pdf-page')
    const pageWidth = Number(shell.dataset.pageWidth)
    if (!page || !Number.isFinite(pageWidth) || pageWidth <= 0) return
    page.style.setProperty('--page-scale', String(shell.getBoundingClientRect().width / pageWidth))
  })
}

function fitIframeContentWidth(doc: Document | null) {
  if (!doc || !props.fitContentWidth) return
  const styleId = 'pdf-neural-fit-content-width'
  if (!doc.getElementById(styleId)) {
    const style = doc.createElement('style')
    style.id = styleId
    style.textContent = `
html,body{width:100%;min-width:0}
.document{width:100%!important;max-width:none!important;padding:0!important;align-items:center!important}
.pdf-page-shell{width:100%!important;max-width:none!important}
`
    doc.head.appendChild(style)
  }
  requestAnimationFrame(() => {
    resizePagesToContentWidth(doc)
    requestAnimationFrame(() => resizePagesToContentWidth(doc))
  })
}

function observePreviewWidth() {
  fitResizeObserver?.disconnect()
  fitContentResizeObserver?.disconnect()
  fitResizeObserver = null
  fitContentResizeObserver = null
  if (!props.fitContentWidth || !iframe.value) return
  fitResizeObserver = new ResizeObserver(() => resizePagesToContentWidth(contentDocument()))
  fitResizeObserver.observe(iframe.value)

  const doc = contentDocument()
  const target = doc?.querySelector<HTMLElement>('.document')
  if (!doc || !target) return
  fitContentResizeObserver = new ResizeObserver(() => resizePagesToContentWidth(doc))
  fitContentResizeObserver.observe(target)
  doc.querySelectorAll<HTMLElement>('.pdf-page-shell').forEach((shell) => {
    fitContentResizeObserver?.observe(shell)
  })
  doc.defaultView?.addEventListener('resize', () => resizePagesToContentWidth(doc))
}

function prepareRuntime() {
  const doc = contentDocument()
  fitIframeContentWidth(doc)
  observePreviewWidth()
  doc?.documentElement.removeAttribute('data-field-editor-ready')
  runtime.renderPreviewFields(doc, { readonlyGeometry: props.readonlyGeometry, readonlyValues: props.readonlyValues })
  runtime.renderFormValues(doc)
  if (!props.readonlyGeometry) runtime.installDrawingHandlers(doc)
  if (!props.readonlyValues) textEditing.installTextEditing(doc, requestSave)
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
    runtime.renderPreviewFields(contentDocument(), { readonlyGeometry: props.readonlyGeometry, readonlyValues: props.readonlyValues })
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

watch(
  () => [fieldEditor.addingField, fieldEditor.pendingRadioBoxes?.length || 0],
  () => runtime.renderPreviewFields(contentDocument(), { readonlyGeometry: props.readonlyGeometry, readonlyValues: props.readonlyValues }),
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

function printDocument() {
  const frameWindow = iframe.value?.contentWindow
  if (!frameWindow) throw new Error('Prévia do documento indisponível para impressão.')
  runtime.renderFormValues(contentDocument())
  frameWindow.focus()
  frameWindow.print()
}

function scrollToElement(id: string) {
  const doc = contentDocument()
  if (!iframe.value || !doc) return
  iframe.value.contentWindow!.location.hash = id
  const el = doc.getElementById(id)
  el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToField(fieldName: string, optionValue?: string) {
  const doc = contentDocument()
  if (!iframe.value || !doc) return
  const fields = Array.from(doc.querySelectorAll<HTMLElement>('.pdf-field'))
  const el = fields.find((element) => (
    element.dataset.name === fieldName
    && (!optionValue || element.dataset.optionValue === optionValue)
  )) || doc.getElementById(fieldName)
  if (!el) return
  if (el.id) iframe.value.contentWindow!.location.hash = el.id
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function openFieldValue(index: number) {
  runtime.openFieldValue(contentDocument(), index)
}

defineExpose({
  toggleTextEdit,
  discardTextEdits,
  serializeForSave,
  requestFullscreen,
  printDocument,
  scrollToElement,
  scrollToField,
  openFieldValue,
})

watch(
  () => docStore.resultVisible,
  async (visible) => {
    if (visible) await nextTick()
  },
)
</script>

<template>
  <iframe ref="iframe" class="preview" title="Prévia do documento convertido" sandbox="allow-same-origin allow-scripts allow-forms allow-fullscreen allow-modals" allowfullscreen @load="prepareRuntime"></iframe>
</template>
