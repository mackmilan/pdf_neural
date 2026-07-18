import { FIELD_CHOICE_HEIGHT, FIELD_CHOICE_WIDTH, useDocumentStore, normalizedFieldHeight } from '../stores/document'
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

interface RenderPreviewFieldsOptions {
  readonlyGeometry?: boolean
  readonlyValues?: boolean
}

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
  const ARROW_KEYS = new Set(['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'])
  const TEXTAREA_DISPLAY_MAX_FONT_SIZE = 12
  const TEXTAREA_DISPLAY_MIN_FONT_SIZE = 6
  const TEXTAREA_DISPLAY_LINE_HEIGHT = 1.2
  let activeSelection: { fieldName: string; optionIndex: number | null } | null = null

  function textareaDisplayFits(display: HTMLElement): boolean {
    return display.scrollHeight <= display.clientHeight + 1 && display.scrollWidth <= display.clientWidth + 1
  }

  function fitTextareaDisplay(display: HTMLElement) {
    display.style.fontSize = `${TEXTAREA_DISPLAY_MAX_FONT_SIZE}px`
    display.style.lineHeight = String(TEXTAREA_DISPLAY_LINE_HEIGHT)
    display.style.overflow = 'hidden'
    if (!display.textContent?.trim() || display.clientWidth <= 0 || display.clientHeight <= 0) return
    if (textareaDisplayFits(display)) return

    let low = TEXTAREA_DISPLAY_MIN_FONT_SIZE
    let high = TEXTAREA_DISPLAY_MAX_FONT_SIZE
    let best = TEXTAREA_DISPLAY_MIN_FONT_SIZE
    for (let i = 0; i < 8; i++) {
      const candidate = (low + high) / 2
      display.style.fontSize = `${candidate}px`
      if (textareaDisplayFits(display)) {
        best = candidate
        low = candidate
      } else {
        high = candidate
      }
    }
    display.style.fontSize = `${best}px`
  }

  function fitTextareaDisplays(doc: Document | null) {
    if (!doc) return
    doc.querySelectorAll<HTMLElement>('.pdf-field[data-type="textarea"] .pdf-field-display').forEach(fitTextareaDisplay)
  }

  function emitFieldSelected(doc: Document, fieldIndex: number, optionIndex: number | null) {
    const field = docStore.currentFields[fieldIndex]
    if (!field) return
    doc.dispatchEvent(new CustomEvent('pdf-field-selected', {
      detail: {
        fieldName: field.name,
        fieldIndex,
        optionIndex,
        optionValue: optionIndex !== null ? field.option_boxes?.[optionIndex]?.value : undefined,
      },
    }))
  }

  function optionIndexFrom(element: HTMLElement | null): number | null {
    const value = element?.dataset.optionIndex
    return value === undefined ? null : Number(value)
  }

  function previewFieldElement(doc: Document, fieldName: string, optionValue?: string): HTMLElement | null {
    const fields = Array.from(doc.querySelectorAll<HTMLElement>('.pdf-field'))
    return fields.find((element) => (
      element.dataset.name === fieldName
      && (!optionValue || element.dataset.optionValue === optionValue)
    )) || null
  }

  function selectPreviewField(doc: Document | null, fieldName: string, optionValue?: string): HTMLElement | null {
    if (!doc) return null
    const element = previewFieldElement(doc, fieldName, optionValue)
    const fieldIndex = docStore.currentFields.findIndex((field) => field.name === fieldName)
    if (!element || fieldIndex < 0) return null

    doc.querySelectorAll<HTMLElement>('.pdf-field').forEach((fieldElement) => {
      if (fieldElement !== element) fieldElement.style.outline = ''
    })
    const optionIndex = optionIndexFrom(element)
    activeSelection = { fieldName, optionIndex }
    element.style.outline = '2px solid #1677ff'
    element.focus({ preventScroll: true })
    emitFieldSelected(doc, fieldIndex, optionIndex)
    return element
  }

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

  function visibleFieldValue(field: Field, radioOption?: string): string {
    if (!Object.prototype.hasOwnProperty.call(docStore.formValues, field.name)) return ''
    const value = docStore.formValues[field.name]
    if (field.type === 'checkbox') return value ? '✓' : ''
    if (field.type === 'radio') return value === radioOption ? '✓' : ''
    return value === null || value === undefined ? '' : String(value)
  }

  function syncVisibleFieldValues(doc: Document | null) {
    if (!doc) return
    doc.querySelectorAll<HTMLElement>('.pdf-field-display').forEach((display) => {
      const field = docStore.currentFields.find((item) => item.name === display.dataset.fieldName)
      if (!field) return
      display.textContent = visibleFieldValue(field, display.dataset.fieldOption)
    })
    fitTextareaDisplays(doc)
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

  function openFieldValue(doc: Document | null, index: number, radioOption?: string) {
    const field = docStore.currentFields[index]
    if (!field || !doc) return
    const fieldElement = Array.from(doc.querySelectorAll<HTMLElement>('.pdf-field')).find(
      (element) => element.dataset.name === field.name,
    )
    if (!fieldElement) return
    closeInlineFieldValue(doc)
    if (field.type === 'radio') {
      if (!radioOption || !field.options?.includes(radioOption)) {
        docStore.status = 'Dê duplo clique na área desenhada da opção desejada.'
        return
      }
      docStore.formValues[field.name] = radioOption
      renderFormValues(doc)
      docStore.status = 'Opção selecionada no JSON em memória.'
      return
    }
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
        width: `${FIELD_CHOICE_WIDTH}px`,
        height: `${FIELD_CHOICE_HEIGHT}px`,
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

  function renderPreviewFields(doc: Document | null, options: RenderPreviewFieldsOptions = {}) {
    if (!doc) return
    const readonlyGeometry = Boolean(options.readonlyGeometry)
    const readonlyValues = Boolean(options.readonlyValues)
    closeInlineFieldValue(doc)
    clearAlignmentGuides(doc)
    doc.querySelectorAll('.pdf-field').forEach((element) => element.remove())
    doc.querySelectorAll('.pdf-field-draft').forEach((element) => element.remove())
    doc.querySelectorAll('.pdf-radio-pending').forEach((element) => element.remove())
    docStore.currentFields.forEach((field) => {
      const renderBoxes = field.type === 'radio' && field.option_boxes?.length
        ? field.option_boxes
        : [{ value: undefined, page: field.page, x: field.x, y: field.y, width: field.width, height: normalizedFieldHeight(field) }]
      renderBoxes.forEach((box, optionIndex) => {
        const page = doc.querySelector<HTMLElement>(`.pdf-page[data-page="${box.page}"]`)
        if (!page) return
        const element = doc.createElement('div')
        if (optionIndex === 0) element.id = field.name
        element.className = 'pdf-field'
        element.tabIndex = readonlyGeometry ? -1 : 0
        element.dataset.name = field.name
        element.dataset.type = field.type
        element.dataset.manual = field.source === 'manual' ? 'true' : 'false'
        if (field.type === 'radio') {
          element.dataset.optionIndex = String(optionIndex)
          if (box.value) element.dataset.optionValue = box.value
        }
        if (activeSelection?.fieldName === field.name && activeSelection.optionIndex === (field.type === 'radio' ? optionIndex : null)) {
          element.style.outline = '2px solid #1677ff'
          requestAnimationFrame(() => {
            if (element.isConnected) element.focus({ preventScroll: true })
          })
        }
        element.title = field.type === 'radio' ? `${field.label}: ${box.value}` : field.label
        const isFixedChoice = field.type === 'checkbox' || field.type === 'radio'
        const fieldHeight = isFixedChoice ? FIELD_CHOICE_HEIGHT : normalizedFieldHeight(field)
        const fieldWidth = isFixedChoice ? FIELD_CHOICE_WIDTH : box.width
        if (field.type !== 'radio') {
          field.height = fieldHeight
          if (field.type === 'checkbox') field.width = FIELD_CHOICE_WIDTH
        }
        Object.assign(element.style, {
          left: `${box.x}px`,
          top: `${box.y}px`,
          width: `${fieldWidth}px`,
          height: `${fieldHeight}px`,
          cursor: readonlyGeometry ? 'text' : 'move',
        })
        if (readonlyValues) {
          Object.assign(element.style, {
            border: '0',
            background: 'transparent',
            boxShadow: 'none',
            outline: '0',
            cursor: 'default',
            pointerEvents: 'none',
          } as Partial<CSSStyleDeclaration>)
          element.removeAttribute('title')
        }
        const display = doc.createElement('span')
        display.className = 'pdf-field-display'
        display.dataset.fieldName = field.name
        if (field.type === 'radio' && box.value) display.dataset.fieldOption = box.value
        display.textContent = visibleFieldValue(field, box.value)
        const isMark = field.type === 'checkbox' || field.type === 'radio'
        const isMultiline = field.type === 'textarea'
        Object.assign(display.style, {
          position: 'absolute', inset: '0', zIndex: '90', display: isMultiline ? 'block' : 'flex',
          alignItems: isMultiline ? 'flex-start' : 'center',
          justifyContent: isMark ? 'center' : 'flex-start', padding: isMark ? '0' : '2px 4px',
          color: '#111827', font: '12px/1.2 Arial, sans-serif',
          textAlign: fieldTextAlign(field), whiteSpace: isMultiline ? 'pre-wrap' : 'nowrap',
          overflow: 'hidden', overflowWrap: isMultiline ? 'anywhere' : 'normal',
          textOverflow: isMultiline ? 'clip' : 'ellipsis', pointerEvents: 'none',
        } as Partial<CSSStyleDeclaration>)
        if (!isMark && field.align === 'center') display.style.justifyContent = 'center'
        if (!isMark && field.align === 'right') display.style.justifyContent = 'flex-end'
        if (!isMark && field.align === 'justify') {
          display.style.display = 'block'
          display.style.textAlignLast = 'justify'
        }
        element.appendChild(display)
        if (!readonlyGeometry && !isFixedChoice) {
          const handles: HTMLElement[] = []
          const directions = field.type === 'textarea'
            ? (['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se'] as const)
            : (['w', 'e'] as const)
          directions.forEach((direction) => {
            const handle = doc.createElement('span')
            handle.dataset.resize = direction
            const vertical = direction.includes('n') || direction.includes('s')
            const horizontal = direction.includes('w') || direction.includes('e')
            Object.assign(handle.style, {
              position: 'absolute', width: '9px', height: '9px', border: '1px solid white', borderRadius: '2px',
              background: '#1677ff', zIndex: '100', opacity: '0',
              top: direction.includes('n') ? '-5px' : direction.includes('s') ? 'auto' : '50%',
              bottom: direction.includes('s') ? '-5px' : 'auto',
              left: direction.includes('w') ? '-5px' : direction.includes('e') ? 'auto' : '50%',
              right: direction.includes('e') ? '-5px' : 'auto',
              transform: vertical && !horizontal ? 'translateX(-50%)' : horizontal && !vertical ? 'translateY(-50%)' : 'none',
              cursor: vertical && horizontal ? `${direction}-resize` : vertical ? 'ns-resize' : 'ew-resize',
              pointerEvents: 'auto',
            } as Partial<CSSStyleDeclaration>)
            handles.push(handle)
            element.appendChild(handle)
          })
          element.addEventListener('mouseenter', () => handles.forEach((handle) => (handle.style.opacity = '1')))
          element.addEventListener('mouseleave', () => handles.forEach((handle) => (handle.style.opacity = '0')))
        }
        if (!readonlyValues) {
          element.addEventListener('click', () => {
            emitFieldSelected(doc, docStore.currentFields.findIndex((item) => item.name === field.name), field.type === 'radio' ? optionIndex : null)
          })
          element.addEventListener('dblclick', (event) => {
            event.preventDefault()
            event.stopPropagation()
            openFieldValue(doc, docStore.currentFields.findIndex((item) => item.name === field.name), box.value)
          })
        }
        page.appendChild(element)
      })
    })
    fitTextareaDisplays(doc)
    if (readonlyGeometry) return
    ;(fieldEditor.pendingRadioBoxes || []).forEach((box) => {
      const page = doc.querySelector<HTMLElement>(`.pdf-page[data-page="${box.page}"]`)
      if (!page) return
      const marker = doc.createElement('div')
      marker.className = 'pdf-radio-pending'
      Object.assign(marker.style, {
        position: 'absolute', left: `${box.x}px`, top: `${box.y}px`, width: `${FIELD_CHOICE_WIDTH}px`, height: `${FIELD_CHOICE_HEIGHT}px`,
        zIndex: '89', border: '2px dashed #1677ff', background: '#1677ff22', pointerEvents: 'none',
      })
      page.appendChild(marker)
    })
  }

  function installDrawingHandlers(doc: Document | null) {
    if (!doc || (doc.documentElement.dataset as any).fieldEditorReady) return
    ;(doc.documentElement.dataset as any).fieldEditorReady = '1'
    let start: { page: HTMLElement; rect: DOMRect; scale: number; x: number; y: number } | null = null
    let draft: HTMLElement | null = null
    let moving: {
      fieldIndex: number
      optionIndex: number | null
      element: HTMLElement
      page: HTMLElement
      rect: DOMRect
      scale: number
      offsetX: number
      offsetY: number
    } | null = null
    let resizing: {
      fieldIndex: number
      optionIndex: number | null
      element: HTMLElement
      direction: string
      page: HTMLElement
      rect: DOMRect
      scale: number
      pageWidth: number
      pageHeight: number
      pointerX: number
      pointerY: number
      original: Field
    } | null = null
    let activeField: {
      fieldIndex: number
      optionIndex: number | null
      element: HTMLElement
    } | null = null

    const editableGeometry = (fieldIndex: number, optionIndex: number | null): Field => {
      const field = docStore.currentFields[fieldIndex]
      if (optionIndex === null || !field.option_boxes?.[optionIndex]) return { ...field }
      return { ...field, ...field.option_boxes[optionIndex], width: FIELD_CHOICE_WIDTH, height: FIELD_CHOICE_HEIGHT }
    }

    const saveGeometry = (fieldIndex: number, optionIndex: number | null, element: HTMLElement) => {
      const field = docStore.currentFields[fieldIndex]
      const isFixedChoice = field.type === 'checkbox' || field.type === 'radio'
      const geometry = {
        x: parseFloat(element.style.left), y: parseFloat(element.style.top),
        width: isFixedChoice ? FIELD_CHOICE_WIDTH : parseFloat(element.style.width),
        height: isFixedChoice ? FIELD_CHOICE_HEIGHT : field.type === 'textarea' ? parseFloat(element.style.height) : normalizedFieldHeight(field),
      }
      if (optionIndex !== null && field.option_boxes?.[optionIndex]) Object.assign(field.option_boxes[optionIndex], geometry)
      else Object.assign(field, geometry)
      if (field.type === 'radio' && field.option_boxes?.length) {
        const first = field.option_boxes[0]
        Object.assign(field, { page: first.page, x: first.x, y: first.y, width: first.width, height: first.height })
      }
    }

    const pageBounds = (page: HTMLElement) => {
      const rect = page.getBoundingClientRect()
      const shell = page.closest('.pdf-page-shell') as HTMLElement | null
      const pageWidth = Number(shell?.dataset.pageWidth) || rect.width
      const pageHeight = Number(shell?.dataset.pageHeight) || rect.height
      return { pageWidth, pageHeight }
    }

    const selectFieldElement = (fieldIndex: number, optionIndex: number | null, element: HTMLElement) => {
      if (activeField?.element && activeField.element !== element) activeField.element.style.outline = ''
      activeField = { fieldIndex, optionIndex, element }
      activeSelection = { fieldName: docStore.currentFields[fieldIndex].name, optionIndex }
      element.style.outline = '2px solid #1677ff'
      element.focus({ preventScroll: true })
      emitFieldSelected(doc, fieldIndex, optionIndex)
    }

    const currentActiveField = () => {
      if (
        activeField?.element.isConnected
        && activeSelection
        && activeField.element.dataset.name === activeSelection?.fieldName
        && activeField.optionIndex === activeSelection.optionIndex
      ) return activeField
      if (!activeSelection) return null
      const fieldIndex = docStore.currentFields.findIndex((field) => field.name === activeSelection?.fieldName)
      if (fieldIndex < 0) return null
      const element = Array.from(doc.querySelectorAll<HTMLElement>('.pdf-field')).find((fieldElement) => {
        const optionIndex = optionIndexFrom(fieldElement)
        return fieldElement.dataset.name === activeSelection?.fieldName && optionIndex === activeSelection?.optionIndex
      })
      if (!element) return null
      activeField = { fieldIndex, optionIndex: activeSelection.optionIndex, element }
      element.style.outline = '2px solid #1677ff'
      return activeField
    }

    const moveActiveFieldByKeyboard = (event: KeyboardEvent) => {
      const selected = currentActiveField()
      if (!selected || !ARROW_KEYS.has(event.key) || event.altKey || event.ctrlKey || event.metaKey) return
      if (closestFromEvent(event, '.pdf-field-value')) return
      const field = editableGeometry(selected.fieldIndex, selected.optionIndex)
      const page = selected.element.closest('.pdf-page') as HTMLElement | null
      if (!page) return
      event.preventDefault()
      event.stopPropagation()
      const step = event.shiftKey ? 10 : 1
      const deltaX = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0
      const deltaY = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0
      const { pageWidth, pageHeight } = pageBounds(page)
      const x = Math.max(0, Math.min(field.x + deltaX, pageWidth - field.width))
      const y = Math.max(0, Math.min(field.y + deltaY, pageHeight - field.height))
      selected.element.style.left = `${x}px`
      selected.element.style.top = `${y}px`
      saveGeometry(selected.fieldIndex, selected.optionIndex, selected.element)
      docStore.status = 'Campo movido com o teclado. Clique em Salvar alterações.'
    }

    doc.addEventListener('pointerdown', (event) => {
      if (closestFromEvent(event, '.pdf-field-value')) return
      const resizeHandle = closestFromEvent(event, '[data-resize]') as HTMLElement | null
      if (!fieldEditor.addingField && resizeHandle) {
        doc.querySelectorAll('.pdf-field-draft').forEach((element) => element.remove())
        const fieldElement = resizeHandle.closest('.pdf-field') as HTMLElement | null
        const fieldIndex = docStore.currentFields.findIndex((field) => field.name === fieldElement?.dataset.name)
        const optionIndex = optionIndexFrom(fieldElement)
        const page = fieldElement?.closest('.pdf-page') as HTMLElement | null
        if (fieldIndex < 0 || !page) return
        event.preventDefault()
        event.stopPropagation()
        capturePointer(event as PointerEvent)
        const rect = page.getBoundingClientRect()
        const shell = page.closest('.pdf-page-shell') as HTMLElement | null
        const pageWidth = Number(shell?.dataset.pageWidth) || rect.width
        const pageHeight = Number(shell?.dataset.pageHeight) || rect.height
        const scale = pageWidth / rect.width
        resizing = {
          fieldIndex,
          optionIndex,
          element: fieldElement as HTMLElement,
          direction: resizeHandle.dataset.resize!,
          page,
          rect,
          scale,
          pageWidth,
          pageHeight,
          pointerX: ((event as PointerEvent).clientX - rect.left) * scale,
          pointerY: ((event as PointerEvent).clientY - rect.top) * scale,
          original: editableGeometry(fieldIndex, optionIndex),
        }
        selectFieldElement(fieldIndex, optionIndex, fieldElement!)
        return
      }
      const fieldElement = closestFromEvent(event, '.pdf-field') as HTMLElement | null
      if (!fieldEditor.addingField && fieldElement) {
        doc.querySelectorAll('.pdf-field-draft').forEach((element) => element.remove())
        const fieldIndex = docStore.currentFields.findIndex((field) => field.name === fieldElement.dataset.name)
        const optionIndex = optionIndexFrom(fieldElement)
        const page = fieldElement.closest('.pdf-page') as HTMLElement | null
        if (fieldIndex < 0 || !page) return
        event.preventDefault()
        capturePointer(event as PointerEvent)
        const rect = page.getBoundingClientRect()
        const pageWidth = Number((page.closest('.pdf-page-shell') as HTMLElement)?.dataset.pageWidth) || rect.width
        const scale = pageWidth / rect.width
        moving = {
          fieldIndex,
          optionIndex,
          element: fieldElement,
          page,
          rect,
          scale,
          offsetX: ((event as PointerEvent).clientX - rect.left) * scale - editableGeometry(fieldIndex, optionIndex).x,
          offsetY: ((event as PointerEvent).clientY - rect.top) * scale - editableGeometry(fieldIndex, optionIndex).y,
        }
        selectFieldElement(fieldIndex, optionIndex, fieldElement)
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
      draft.className = 'pdf-field-draft'
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
        const pointerY = (pointerEvent.clientY - resizing.rect.top) * resizing.scale
        const dx = pointerX - resizing.pointerX
        const dy = pointerY - resizing.pointerY
        const original = resizing.original
        const direction = resizing.direction
        let x = original.x
        let y = original.y
        let width = original.width
        let height = normalizedFieldHeight(original)
        if (direction.includes('e')) width = Math.max(5, Math.min(original.width + dx, resizing.pageWidth - original.x))
        if (direction.includes('w')) {
          x = Math.max(0, Math.min(original.x + dx, original.x + original.width - 5))
          width = original.width + (original.x - x)
        }
        if (direction.includes('s')) height = Math.max(5, Math.min(normalizedFieldHeight(original) + dy, resizing.pageHeight - original.y))
        if (direction.includes('n')) {
          y = Math.max(0, Math.min(original.y + dy, original.y + normalizedFieldHeight(original) - 5))
          height = normalizedFieldHeight(original) + (original.y - y)
        }
        const snapped = direction.includes('e') || direction.includes('w')
          ? snapHorizontalResize(
            { x, y, width, height },
            original.page,
            direction,
            docStore.currentFields,
            resizing.fieldIndex,
          )
          : { box: { x, y, width, height }, guides: [] }
        x = Math.max(0, Math.min(snapped.box.x, resizing.pageWidth - 5))
        width = Math.max(5, Math.min(snapped.box.width, resizing.pageWidth - x))
        Object.assign(resizing.element.style, { left: `${x}px`, top: `${y}px`, width: `${width}px`, height: `${height}px` })
        showAlignmentGuides(resizing.page, snapped.guides)
        return
      }
      if (moving) {
        const field = editableGeometry(moving.fieldIndex, moving.optionIndex)
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
      const y = (pointerEvent.clientY - start.rect.top) * start.scale
      const fieldType = fieldEditor.form.type
      const isMultiline = fieldType === 'textarea'
      const rawBox = {
        x: Math.min(start.x, x),
        y: isMultiline ? Math.min(start.y, y) : start.y,
        width: Math.abs(x - start.x),
        height: isMultiline ? Math.abs(y - start.y) : normalizedFieldHeight({ type: fieldType }),
      }
      const snapped = snapFieldBox(rawBox, Number(start.page.dataset.page), docStore.currentFields)
      Object.assign(draft.style, { left: `${snapped.box.x}px`, top: `${snapped.box.y}px`, width: `${snapped.box.width}px`, height: `${snapped.box.height}px` })
      showAlignmentGuides(start.page, snapped.guides)
    })

    doc.addEventListener('pointerup', (event) => {
      const pointerEvent = event as PointerEvent
      if (resizing) {
        saveGeometry(resizing.fieldIndex, resizing.optionIndex, resizing.element)
        selectFieldElement(resizing.fieldIndex, resizing.optionIndex, resizing.element)
        resizing = null
        clearAlignmentGuides(doc)
        docStore.status = 'Campo redimensionado. Clique em Salvar alterações.'
        return
      }
      if (moving) {
        saveGeometry(moving.fieldIndex, moving.optionIndex, moving.element)
        selectFieldElement(moving.fieldIndex, moving.optionIndex, moving.element)
        moving = null
        clearAlignmentGuides(doc)
        docStore.status = 'Campo movido. Clique em Salvar alterações.'
        return
      }
      if (!start || !draft) return
      const x = (pointerEvent.clientX - start.rect.left) * start.scale
      const y = (pointerEvent.clientY - start.rect.top) * start.scale
      const fieldType = fieldEditor.form.type
      const isMultiline = fieldType === 'textarea'
      const rawBox = {
        x: Math.min(start.x, x),
        y: isMultiline ? Math.min(start.y, y) : start.y,
        width: Math.abs(x - start.x),
        height: isMultiline ? Math.abs(y - start.y) : normalizedFieldHeight({ type: fieldType }),
      }
      const box = snapFieldBox(rawBox, Number(start.page.dataset.page), docStore.currentFields).box
      const labelValue = fieldEditor.form.label.trim()
      if (box.width >= 3 && box.height >= 3 && labelValue) {
        const newField = fieldEditor.buildDraftField(labelValue, Number(start.page.dataset.page), box)
        if (!newField) {
          draft.remove()
          draft = null
          start = null
          if (fieldType === 'radio' && (fieldEditor.pendingRadioBoxes?.length || 0)) {
            docStore.status = fieldEditor.hint
            renderPreviewFields(doc)
            clearAlignmentGuides(doc)
            return
          }
          docStore.status = fieldType === 'radio'
            ? 'Informe de 2 a 100 opções diferentes para o campo radio.'
            : 'O valor mínimo deve ser menor ou igual ao valor máximo.'
          clearAlignmentGuides(doc)
          return
        }
        docStore.currentFields.push(newField)
        fieldEditor.stop()
        docStore.status = 'Campo adicionado. Clique em Salvar alterações.'
        draft.remove()
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

    doc.addEventListener('keydown', moveActiveFieldByKeyboard)
  }

  return {
    renderPreviewFields,
    renderFormValues,
    installDrawingHandlers,
    openFieldValue,
    closeInlineFieldValue,
    selectPreviewField,
  }
}
