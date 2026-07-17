<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDocumentStore } from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'
import { usePreviewRuntime } from '../composables/usePreviewRuntime'
import { useTextEditing } from '../composables/useTextEditing'

const docStore = useDocumentStore()
const auth = useAuthStore()
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

function pdfDocumentTitle(filename?: string): string {
  const name = (filename || docStore.currentDocumentName || 'documento-preenchido').trim()
  return name.toLowerCase().endsWith('.pdf') ? name.slice(0, -4) : name
}

function pdfFilename(filename?: string): string {
  const name = (filename || docStore.currentDocumentName || 'documento-preenchido.pdf').trim()
  return name.toLowerCase().endsWith('.pdf') ? name : `${name}.pdf`
}

function pageSizeCss(doc: Document): string {
  const firstPage = doc.querySelector<HTMLElement>('.pdf-page-shell')
  const width = Number(firstPage?.dataset.pageWidth)
  const height = Number(firstPage?.dataset.pageHeight)
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return ''
  return `
@page { size: ${width}pt ${height}pt; margin: 0; }
@media print {
  * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
  html, body { margin: 0 !important; padding: 0 !important; width: ${width}pt !important; background: #fff !important; }
  .document { margin: 0 !important; padding: 0 !important; gap: 0 !important; width: ${width}pt !important; align-items: flex-start !important; }
  .pdf-page-shell { width: ${width}pt !important; height: ${height}pt !important; max-width: none !important; aspect-ratio: auto !important; break-after: page !important; page-break-after: always !important; overflow: hidden !important; }
  .pdf-page { --page-scale: 1 !important; box-shadow: none !important; transform: scale(1.3333333333) !important; transform-origin: top left !important; }
}`
}

function normalizePdfTextFonts(root: HTMLElement) {
  root.querySelectorAll<HTMLElement>('.pdf-text').forEach((element) => {
    const font = element.style.fontFamily || ''
    if (/bold|black|heavy/i.test(font)) element.style.fontWeight = '700'
    if (/italic|oblique/i.test(font)) element.style.fontStyle = 'italic'
    element.style.fontFamily = '"Liberation Serif", "Times New Roman", Times, serif'
  })
}

function serializedHtmlForPdf(doc: Document, filename?: string): string {
  const root = doc.documentElement.cloneNode(true) as HTMLElement
  const title = root.querySelector('title') || doc.createElement('title')
  title.textContent = pdfDocumentTitle(filename)
  if (!title.parentElement) root.querySelector('head')?.appendChild(title)
  root.querySelectorAll('.pdf-field-value, .pdf-alignment-guide, .pdf-radio-pending').forEach((element) => element.remove())
  normalizePdfTextFonts(root)
  const style = doc.createElement('style')
  style.id = 'pdf-neural-gotenberg-page-style'
  style.textContent = pageSizeCss(doc)
  root.querySelector(`#${style.id}`)?.remove()
  root.querySelector('head')?.appendChild(style)
  return `<!doctype html>\n${root.outerHTML}`
}

function downloadBlob(blob: Blob, filename?: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = pdfFilename(filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function generatePdf(filename?: string) {
  const doc = contentDocument()
  if (!doc) throw new Error('Prévia do documento indisponível para gerar PDF.')
  runtime.renderFormValues(contentDocument())
  await nextTick()
  const response = await auth.apiFetch('/api/pdf/html', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename: pdfFilename(filename),
      html_content: serializedHtmlForPdf(doc, filename),
    }),
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.error || 'Não foi possível gerar o PDF no Gotenberg.')
  }
  downloadBlob(await response.blob(), filename)
}

function printDocument() {
  void generatePdf()
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
  generatePdf,
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
