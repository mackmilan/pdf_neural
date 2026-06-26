import { useDocumentStore, normalizedFieldHeight } from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'
import {
  capturePointer,
  clearAlignmentGuides,
  closestFromEvent,
  fieldTextAlign,
  showAlignmentGuides,
  snapFieldBox,
  snapHorizontalResize,
} from './fieldGeometry'
import type { Field } from '../types'

function optionalNumber(value: unknown): number | null {
  return value === '' || value === null || value === undefined ? null : Number(value)
}

export function maskValue(value: string, mask: string): string {
  if (!mask) return value
  const source = String(value).replace(/[^a-zA-ZÀ-ÿ0-9]/g, '')
  let result = ''
  let position = 0
  const matches = (character: string, token: string) =>
    token === '0' ? /[0-9]/.test(character) : token === 'A' ? /[a-zA-ZÀ-ÿ]/.test(character) : /[a-zA-ZÀ-ÿ0-9]/.test(character)
  for (const token of mask) {
    if (!['0', 'A', '*'].includes(token)) {
      if (position < source.length) result += token
      continue
    }
    while (position < source.length && !matches(source[position], token)) position++
    if (position >= source.length) break
    result += source[position++]
  }
  return result
}

export function usePreviewRuntime() {
  const docStore = useDocumentStore()
  const fieldEditor = useFieldEditorStore()

  function valueInputType(field: Field): string {
    return field.mask || field.type === 'select' ? 'text' : field.type
  }

  function readFieldControlValue(field: Field, control: HTMLInputElement | HTMLTextAreaElement) {
    if (field.type === 'checkbox') return (control as HTMLInputElement).checked
    if (field.type === 'number' && !field.mask && control.value !== '') return Number(control.value)
    return control.value
  }

  function writeFieldControlValue(field: Field, control: HTMLInputElement | HTMLTextAreaElement, value: unknown) {
    if (field.type === 'checkbox') (control as HTMLInputElement).checked = Boolean(value)
    else control.value = (value as string) ?? ''
  }

  function applyFieldValidationAttributes(field: Field, control: HTMLInputElement | HTMLTextAreaElement) {
    control.required = Boolean(field.required)
    if (field.type === 'number' && !field.mask) {
      const min = optionalNumber(field.min)
      const max = optionalNumber(field.max)
      const input = control as HTMLInputElement
      if (Number.isFinite(min)) input.min = String(min)
      else input.removeAttribute('min')
      if (Number.isFinite(max)) input.max = String(max)
      else input.removeAttribute('max')
      input.step = 'any'
    } else {
      control.removeAttribute('min')
      control.removeAttribute('max')
      control.removeAttribute('step')
    }
  }

  function validateFieldControl(field: Field, control: HTMLInputElement | HTMLTextAreaElement): boolean {
    control.setCustomValidity('')
    if (field.required && field.type !== 'checkbox' && !String(control.value || '').trim()) {
      control.setCustomValidity('Campo obrigatório.')
    }
    if (field.required && field.type === 'checkbox' && !(control as HTMLInputElement).checked) {
      control.setCustomValidity('Campo obrigatório.')
    }
    if (field.type === 'number' && !field.mask && control.value !== '') {
      const value = Number(control.value)
      const min = optionalNumber(field.min)
      const max = optionalNumber(field.max)
      if (!Number.isFinite(value)) control.setCustomValidity('Informe um número válido.')
      else if (Number.isFinite(min) && value < (min as number)) control.setCustomValidity(`Valor mínimo: ${min}.`)
      else if (Number.isFinite(max) && value > (max as number)) control.setCustomValidity(`Valor máximo: ${max}.`)
    }
    return control.reportValidity()
  }

  function visibleFieldValue(field: Field): string {
    if (!Object.prototype.hasOwnProperty.call(docStore.formValues, field.name)) return ''
    const value = docStore.formValues[field.name]
    if (field.type === 'checkbox') return value ? '✓' : ''
    return value === null || value === undefined ? '' : String(value)
  }

  function syncVisibleFieldValues(doc: Document | null) {
    if (!doc) return
    doc.querySelectorAll<HTMLElement>('.pdf-field-display').forEach((display) => {
      const field = docStore.currentFields.find((item) => item.name === display.dataset.fieldName)
      if (!field) return
      display.textContent = visibleFieldValue(field)
    })
  }

  function syncInlineFieldValues(doc: Document | null) {
    if (!doc) return
    doc.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('.pdf-field-value').forEach((control) => {
      if (doc.activeElement === control) return
      const field = docStore.currentFields.find((item) => item.name === control.dataset.fieldName)
      if (!field) return
      writeFieldControlValue(field, control, docStore.formValues[field.name])
    })
  }

  function renderFormValues(doc: Document | null) {
    syncInlineFieldValues(doc)
    syncVisibleFieldValues(doc)
  }

  function closeInlineFieldValue(doc: Document | null) {
    if (!doc) return
    doc.querySelectorAll('.pdf-field-value').forEach((control) => control.remove())
  }

  function saveInlineFieldValue(field: Field, control: HTMLInputElement | HTMLTextAreaElement, doc: Document | null): boolean {
    if (field.type !== 'checkbox' && field.mask) {
      control.value = maskValue(control.value, field.mask)
    }
    if (!validateFieldControl(field, control)) {
      docStore.status = control.validationMessage
      return false
    }
    docStore.formValues[field.name] = readFieldControlValue(field, control)
    renderFormValues(doc)
    docStore.status = 'Valor guardado no JSON em memória.'
    return true
  }

  function openFieldValue(doc: Document | null, index: number) {
    const field = docStore.currentFields[index]
    if (!field || !doc) return
    const fieldElement = Array.from(doc.querySelectorAll<HTMLElement>('.pdf-field')).find(
      (element) => element.dataset.name === field.name,
    )
    if (!fieldElement) return
    closeInlineFieldValue(doc)
    let input: HTMLInputElement | HTMLTextAreaElement
    if (field.type === 'textarea') input = doc.createElement('textarea')
    else {
      input = doc.createElement('input')
      ;(input as HTMLInputElement).type = valueInputType(field)
    }
    input.className = 'pdf-field-value'
    input.name = field.name
    input.dataset.fieldName = field.name
    input.setAttribute('aria-label', field.label)
    input.title = field.label
    applyFieldValidationAttributes(field, input)
    writeFieldControlValue(field, input, docStore.formValues[field.name])
    Object.assign(input.style, {
      position: 'absolute',
      inset: '0',
      width: '100%',
      height: '100%',
      zIndex: '95',
      border: '0',
      borderRadius: '2px',
      background: 'rgba(255,255,255,.88)',
      color: '#111827',
      padding: field.type === 'checkbox' ? '0' : '2px 4px',
      font: '12px/1.2 Arial, sans-serif',
      resize: 'none',
      outline: '2px solid #e05260',
      textAlign: fieldTextAlign(field),
      textAlignLast: fieldTextAlign(field) === 'justify' ? 'justify' : 'auto',
      boxShadow: '0 0 0 1px rgba(255,255,255,.75) inset',
      pointerEvents: 'auto',
    } as Partial<CSSStyleDeclaration>)
    if (field.type === 'checkbox') {
      Object.assign(input.style, {
        width: '18px',
        height: '18px',
        inset: '50% auto auto 50%',
        transform: 'translate(-50%, -50%)',
      } as Partial<CSSStyleDeclaration>)
    }
    const store = () => saveInlineFieldValue(field, input, doc)
    input.addEventListener(field.type === 'checkbox' ? 'change' : 'input', () => {
      input.setCustomValidity('')
      if (!field.required || field.type === 'checkbox' || String(input.value || '').trim()) store()
    })
    input.addEventListener('blur', store)
    input.addEventListener('keydown', (event: Event) => {
      if ((event as KeyboardEvent).key === 'Escape') {
        event.preventDefault()
        closeInlineFieldValue(doc)
      }
    })
    ;['click', 'dblclick', 'pointerdown'].forEach((type) => {
      input.addEventListener(type, (event) => event.stopPropagation())
    })
    fieldElement.appendChild(input)
    requestAnimationFrame(() => {
      input.focus()
      if (field.type !== 'checkbox' && (input as HTMLInputElement).select) (input as HTMLInputElement).select()
    })
  }

  function renderPreviewFields(doc: Document | null) {
    if (!doc) return
    closeInlineFieldValue(doc)
    clearAlignmentGuides(doc)
    doc.querySelectorAll('.pdf-field').forEach((element) => element.remove())
    docStore.currentFields.forEach((field) => {
      const page = doc.querySelector<HTMLElement>(`.pdf-page[data-page="${field.page}"]`)
      if (!page) return
      const element = doc.createElement('div')
      element.id = field.name
      element.className = 'pdf-field'
      element.dataset.name = field.name
      element.dataset.type = field.type
      element.dataset.manual = field.source === 'manual' ? 'true' : 'false'
      element.title = field.label
      const fieldHeight = normalizedFieldHeight(field)
      field.height = fieldHeight
      Object.assign(element.style, {
        left: `${field.x}px`,
        top: `${field.y}px`,
        width: `${field.width}px`,
        height: `${fieldHeight}px`,
        cursor: 'move',
      })
      const display = doc.createElement('span')
      display.className = 'pdf-field-display'
      display.dataset.fieldName = field.name
      display.textContent = visibleFieldValue(field)
      Object.assign(display.style, {
        position: 'absolute',
        inset: '0',
        zIndex: '90',
        display: 'flex',
        alignItems: field.type === 'textarea' ? 'flex-start' : 'center',
        justifyContent: field.type === 'checkbox' ? 'center' : 'flex-start',
        padding: field.type === 'checkbox' ? '0' : '2px 4px',
        color: '#111827',
        font: '12px/1.2 Arial, sans-serif',
        textAlign: fieldTextAlign(field),
        whiteSpace: field.type === 'textarea' ? 'pre-wrap' : 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        pointerEvents: 'none',
      } as Partial<CSSStyleDeclaration>)
      if (field.type !== 'checkbox' && field.align === 'center') display.style.justifyContent = 'center'
      if (field.type !== 'checkbox' && field.align === 'right') display.style.justifyContent = 'flex-end'
      if (field.type !== 'checkbox' && field.align === 'justify') {
        display.style.display = 'block'
        display.style.textAlignLast = 'justify'
      }
      element.appendChild(display)
      const handles: HTMLElement[] = []
      ;(['w', 'e'] as const).forEach((direction) => {
        const handle = doc.createElement('span')
        handle.dataset.resize = direction
        const left = direction === 'w' ? '-5px' : 'auto'
        const right = direction === 'e' ? '-5px' : 'auto'
        Object.assign(handle.style, {
          position: 'absolute',
          width: '9px',
          height: '9px',
          border: '1px solid white',
          borderRadius: '2px',
          background: '#1677ff',
          zIndex: '100',
          opacity: '0',
          top: '50%',
          bottom: 'auto',
          left,
          right,
          transform: 'translateY(-50%)',
          cursor: 'ew-resize',
          pointerEvents: 'auto',
        } as Partial<CSSStyleDeclaration>)
        handles.push(handle)
        element.appendChild(handle)
      })
      element.addEventListener('mouseenter', () => handles.forEach((handle) => (handle.style.opacity = '1')))
      element.addEventListener('mouseleave', () => handles.forEach((handle) => (handle.style.opacity = '0')))
      element.addEventListener('dblclick', (event) => {
        event.preventDefault()
        event.stopPropagation()
        openFieldValue(doc, docStore.currentFields.findIndex((item) => item.name === field.name))
      })
      page.appendChild(element)
    })
  }

  function installDrawingHandlers(doc: Document | null) {
    if (!doc || (doc.documentElement.dataset as any).fieldEditorReady) return
    ;(doc.documentElement.dataset as any).fieldEditorReady = '1'
    let start: { page: HTMLElement; rect: DOMRect; scale: number; x: number; y: number } | null = null
    let draft: HTMLElement | null = null
    let moving: {
      fieldIndex: number
      element: HTMLElement
      page: HTMLElement
      rect: DOMRect
      scale: number
      offsetX: number
      offsetY: number
    } | null = null
    let resizing: {
      fieldIndex: number
      element: HTMLElement
      direction: string
      page: HTMLElement
      rect: DOMRect
      scale: number
      pageWidth: number
      pointerX: number
      original: Field
    } | null = null

    doc.addEventListener('pointerdown', (event) => {
      if (closestFromEvent(event, '.pdf-field-value')) return
      const resizeHandle = closestFromEvent(event, '[data-resize]') as HTMLElement | null
      if (!fieldEditor.addingField && resizeHandle) {
        const fieldElement = resizeHandle.closest('.pdf-field') as HTMLElement | null
        const fieldIndex = docStore.currentFields.findIndex((field) => field.name === fieldElement?.dataset.name)
        const page = fieldElement?.closest('.pdf-page') as HTMLElement | null
        if (fieldIndex < 0 || !page) return
        event.preventDefault()
        event.stopPropagation()
        capturePointer(event as PointerEvent)
        const rect = page.getBoundingClientRect()
        const pageWidth = Number((page.closest('.pdf-page-shell') as HTMLElement)?.dataset.pageWidth) || rect.width
        const scale = pageWidth / rect.width
        resizing = {
          fieldIndex,
          element: fieldElement as HTMLElement,
          direction: resizeHandle.dataset.resize!,
          page,
          rect,
          scale,
          pageWidth,
          pointerX: ((event as PointerEvent).clientX - rect.left) * scale,
          original: { ...docStore.currentFields[fieldIndex] },
        }
        fieldElement!.style.outline = '2px solid #1677ff'
        return
      }
      const fieldElement = closestFromEvent(event, '.pdf-field') as HTMLElement | null
      if (!fieldEditor.addingField && fieldElement) {
        const fieldIndex = docStore.currentFields.findIndex((field) => field.name === fieldElement.dataset.name)
        const page = fieldElement.closest('.pdf-page') as HTMLElement | null
        if (fieldIndex < 0 || !page) return
        event.preventDefault()
        capturePointer(event as PointerEvent)
        const rect = page.getBoundingClientRect()
        const pageWidth = Number((page.closest('.pdf-page-shell') as HTMLElement)?.dataset.pageWidth) || rect.width
        const scale = pageWidth / rect.width
        moving = {
          fieldIndex,
          element: fieldElement,
          page,
          rect,
          scale,
          offsetX: ((event as PointerEvent).clientX - rect.left) * scale - docStore.currentFields[fieldIndex].x,
          offsetY: ((event as PointerEvent).clientY - rect.top) * scale - docStore.currentFields[fieldIndex].y,
        }
        fieldElement.style.outline = '2px solid #1677ff'
        return
      }
      if (!fieldEditor.addingField) return
      const page = closestFromEvent(event, '.pdf-page') as HTMLElement | null
      if (!page) return
      event.preventDefault()
      capturePointer(event as PointerEvent)
      const rect = page.getBoundingClientRect()
      const pageWidth = Number((page.closest('.pdf-page-shell') as HTMLElement)?.dataset.pageWidth) || rect.width
      const scale = pageWidth / rect.width
      start = { page, rect, scale, x: ((event as PointerEvent).clientX - rect.left) * scale, y: ((event as PointerEvent).clientY - rect.top) * scale }
      draft = doc.createElement('div')
      Object.assign(draft.style, {
        position: 'absolute',
        zIndex: '90',
        border: '2px dashed #1677ff',
        background: '#1677ff22',
        pointerEvents: 'none',
      })
      page.appendChild(draft)
    })

    doc.addEventListener('pointermove', (event) => {
      const pointerEvent = event as PointerEvent
      if (resizing) {
        const pointerX = (pointerEvent.clientX - resizing.rect.left) * resizing.scale
        const dx = pointerX - resizing.pointerX
        const original = resizing.original
        const direction = resizing.direction
        let x = original.x
        let width = original.width
        if (direction.includes('e')) width = Math.max(5, Math.min(original.width + dx, resizing.pageWidth - original.x))
        if (direction.includes('w')) {
          x = Math.max(0, Math.min(original.x + dx, original.x + original.width - 5))
          width = original.width + (original.x - x)
        }
        const snapped = snapHorizontalResize(
          { x, y: original.y, width, height: normalizedFieldHeight(original) },
          original.page,
          direction,
          docStore.currentFields,
          resizing.fieldIndex,
        )
        x = Math.max(0, Math.min(snapped.box.x, resizing.pageWidth - 5))
        width = Math.max(5, Math.min(snapped.box.width, resizing.pageWidth - x))
        Object.assign(resizing.element.style, { left: `${x}px`, width: `${width}px`, height: `${normalizedFieldHeight(original)}px` })
        showAlignmentGuides(resizing.page, snapped.guides)
        return
      }
      if (moving) {
        const field = docStore.currentFields[moving.fieldIndex]
        const pageHeight =
          Number((moving.page.closest('.pdf-page-shell') as HTMLElement)?.dataset.pageHeight) || moving.rect.height * moving.scale
        const rawX = Math.max(
          0,
          Math.min((pointerEvent.clientX - moving.rect.left) * moving.scale - moving.offsetX, moving.rect.width * moving.scale - field.width),
        )
        const rawY = Math.max(0, Math.min((pointerEvent.clientY - moving.rect.top) * moving.scale - moving.offsetY, pageHeight - field.height))
        const snapped = snapFieldBox(
          { x: rawX, y: rawY, width: field.width, height: normalizedFieldHeight(field) },
          field.page,
          docStore.currentFields,
          moving.fieldIndex,
        )
        const x = Math.max(0, Math.min(snapped.box.x, moving.rect.width * moving.scale - field.width))
        const y = Math.max(0, Math.min(snapped.box.y, pageHeight - field.height))
        moving.element.style.left = `${x}px`
        moving.element.style.top = `${y}px`
        showAlignmentGuides(moving.page, snapped.guides)
        return
      }
      if (!start || !draft) return
      const x = (pointerEvent.clientX - start.rect.left) * start.scale
      const fieldType = fieldEditor.form.type
      const rawBox = { x: Math.min(start.x, x), y: start.y, width: Math.abs(x - start.x), height: normalizedFieldHeight({ type: fieldType }) }
      const snapped = snapFieldBox(rawBox, Number(start.page.dataset.page), docStore.currentFields)
      Object.assign(draft.style, { left: `${snapped.box.x}px`, top: `${snapped.box.y}px`, width: `${snapped.box.width}px`, height: `${snapped.box.height}px` })
      showAlignmentGuides(start.page, snapped.guides)
    })

    doc.addEventListener('pointerup', (event) => {
      const pointerEvent = event as PointerEvent
      if (resizing) {
        const field = docStore.currentFields[resizing.fieldIndex]
        field.x = parseFloat(resizing.element.style.left)
        field.y = parseFloat(resizing.element.style.top)
        field.width = parseFloat(resizing.element.style.width)
        field.height = normalizedFieldHeight(field)
        resizing.element.style.outline = ''
        resizing = null
        clearAlignmentGuides(doc)
        docStore.status = 'Campo redimensionado. Clique em Salvar alterações.'
        return
      }
      if (moving) {
        const field = docStore.currentFields[moving.fieldIndex]
        field.x = parseFloat(moving.element.style.left)
        field.y = parseFloat(moving.element.style.top)
        moving.element.style.outline = ''
        moving = null
        clearAlignmentGuides(doc)
        docStore.status = 'Campo movido. Clique em Salvar alterações.'
        return
      }
      if (!start || !draft) return
      const x = (pointerEvent.clientX - start.rect.left) * start.scale
      const fieldType = fieldEditor.form.type
      const rawBox = { x: Math.min(start.x, x), y: start.y, width: Math.abs(x - start.x), height: normalizedFieldHeight({ type: fieldType }) }
      const box = snapFieldBox(rawBox, Number(start.page.dataset.page), docStore.currentFields).box
      const labelValue = fieldEditor.form.label.trim()
      if (box.width >= 3 && labelValue) {
        const newField = fieldEditor.buildDraftField(labelValue, Number(start.page.dataset.page), box)
        if (!newField) {
          draft.remove()
          draft = null
          start = null
          docStore.status = 'O valor mínimo deve ser menor ou igual ao valor máximo.'
          clearAlignmentGuides(doc)
          return
        }
        docStore.currentFields.push(newField)
        fieldEditor.stop()
        docStore.status = 'Campo adicionado. Clique em Salvar alterações.'
        renderPreviewFields(doc)
      } else {
        draft.remove()
        docStore.status = labelValue ? 'A área desenhada é muito pequena.' : 'Informe o nome antes de desenhar.'
      }
      draft = null
      start = null
      clearAlignmentGuides(doc)
    })

    doc.addEventListener('pointercancel', () => {
      start = null
      moving = null
      resizing = null
      if (draft) draft.remove()
      draft = null
      clearAlignmentGuides(doc)
    })
  }

  return {
    renderPreviewFields,
    renderFormValues,
    installDrawingHandlers,
    openFieldValue,
    closeInlineFieldValue,
  }
}
