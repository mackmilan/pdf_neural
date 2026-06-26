import { useDocumentStore } from '../stores/document'

function textEditorStyle(doc: Document): HTMLStyleElement {
  let style = doc.getElementById('pdf-neural-text-editor-style') as HTMLStyleElement | null
  if (!style) {
    style = doc.createElement('style')
    style.id = 'pdf-neural-text-editor-style'
    style.textContent = `
      [data-pdf-text-editable="true"] {
        outline: 1px dashed rgba(22, 119, 255, .65);
        outline-offset: 2px;
        cursor: text;
      }
      [data-pdf-text-editable="true"]:focus {
        outline: 2px solid #1677ff;
        background: rgba(255,255,255,.72);
      }
    `
    doc.head.appendChild(style)
  }
  return style
}

function isEditableTextElement(element: Element): boolean {
  if (!element || !element.childNodes) return false
  if (element.closest('.pdf-field, .pdf-field-value, script, style, noscript')) return false
  if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'INPUT', 'TEXTAREA', 'SELECT', 'OPTION', 'BUTTON'].includes(element.tagName)) return false
  return Array.from(element.childNodes).some((node) => node.nodeType === Node.TEXT_NODE && Boolean(node.textContent?.trim()))
}

export function useTextEditing() {
  const docStore = useDocumentStore()

  function setTextEditMode(doc: Document | null, enabled: boolean, onSave: () => void) {
    if (!doc) return
    docStore.textEditMode = enabled
    doc.documentElement.dataset.pdfTextEditMode = enabled ? 'true' : 'false'
    doc.querySelectorAll<HTMLElement>('[data-pdf-text-editable="true"]').forEach((element) => {
      element.contentEditable = enabled ? 'true' : 'false'
      if (!enabled) element.blur()
    })
    if (enabled) textEditorStyle(doc)
    docStore.status = enabled
      ? 'Clique em qualquer texto da prévia para editar.'
      : docStore.textEditDirty
        ? 'Edição pausada. Salve ou descarte as alterações.'
        : 'Edição de texto encerrada.'
    void onSave
  }

  function installTextEditing(doc: Document | null, onRequestSave: () => void) {
    if (!doc) return
    doc.querySelectorAll<HTMLElement>('[data-pdf-text-editable="true"]').forEach((element) => {
      element.removeAttribute('data-pdf-text-editable')
      element.contentEditable = 'false'
    })
    Array.from(doc.body?.querySelectorAll('*') || [])
      .filter(isEditableTextElement)
      .forEach((element) => {
        const el = element as HTMLElement
        el.dataset.pdfTextEditable = 'true'
        el.contentEditable = docStore.textEditMode ? 'true' : 'false'
        el.spellcheck = true
      })
    if (!doc.documentElement.dataset.pdfTextEditorReady) {
      doc.documentElement.dataset.pdfTextEditorReady = '1'
      doc.addEventListener('input', (event) => {
        if (!(event.target as Element)?.closest('[data-pdf-text-editable="true"]')) return
        docStore.textEditDirty = true
      })
      doc.addEventListener('keydown', (event) => {
        const keyboardEvent = event as KeyboardEvent
        if (!docStore.textEditMode || !(event.target as Element)?.closest('[data-pdf-text-editable="true"]')) return
        if ((keyboardEvent.metaKey || keyboardEvent.ctrlKey) && keyboardEvent.key.toLowerCase() === 's') {
          keyboardEvent.preventDefault()
          onRequestSave()
        }
        if (keyboardEvent.key === 'Escape') setTextEditMode(doc, false, onRequestSave)
      })
    }
    if (docStore.textEditMode) textEditorStyle(doc)
  }

  function serializedPreviewHtml(doc: Document | null): string {
    if (!doc) return ''
    const clone = doc.documentElement.cloneNode(true) as HTMLElement
    clone.querySelectorAll('.pdf-field, .pdf-field-value, .pdf-alignment-guide, #pdf-neural-text-editor-style').forEach((element) =>
      element.remove(),
    )
    clone.querySelectorAll('[data-pdf-text-editable]').forEach((element) => {
      element.removeAttribute('data-pdf-text-editable')
      element.removeAttribute('contenteditable')
      element.removeAttribute('spellcheck')
    })
    clone.removeAttribute('data-pdf-text-editor-ready')
    clone.removeAttribute('data-pdf-text-edit-mode')
    clone.removeAttribute('data-field-editor-ready')
    return `<!doctype html>\n${clone.outerHTML}`
  }

  return { setTextEditMode, installTextEditing, serializedPreviewHtml }
}
