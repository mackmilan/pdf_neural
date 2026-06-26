import { defineStore } from 'pinia'
import { useDocumentStore } from './document'
import { normalizedFieldHeight, optionalNumber } from './document'
import type { Field, FieldAlign, FieldType } from '../types'

export interface FieldFormState {
  label: string
  type: FieldType
  mask: string
  align: FieldAlign
  required: boolean
  min: string
  max: string
}

const DIACRITICS_PATTERN = new RegExp(
  `[${String.fromCharCode(0x0300)}-${String.fromCharCode(0x036f)}]`,
  'g',
)

function emptyForm(): FieldFormState {
  return { label: '', type: 'text', mask: '', align: 'left', required: false, min: '', max: '' }
}

function slug(value: string): string {
  return (
    value
      .normalize('NFD')
      .replace(DIACRITICS_PATTERN, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 64) || 'campo'
  )
}

export const useFieldEditorStore = defineStore('fieldEditor', {
  state: () => ({
    addingField: false,
    editingFieldIndex: null as number | null,
    form: emptyForm(),
    hint: 'Arraste sobre a página para marcar a área do novo campo.',
  }),
  actions: {
    uniqueName(label: string, ignoredIndex: number | null = null): string {
      const docStore = useDocumentStore()
      const base = slug(label)
      let name = base
      let suffix = 2
      const used = new Set(docStore.currentFields.filter((_field, index) => index !== ignoredIndex).map((field) => field.name))
      while (used.has(name)) name = `${base}_${suffix++}`
      return name
    },
    startAdd() {
      this.addingField = true
      this.editingFieldIndex = null
      this.form = emptyForm()
      this.hint = 'Arraste sobre a página para marcar a área do novo campo.'
    },
    startEdit(index: number) {
      const docStore = useDocumentStore()
      const field = docStore.currentFields[index]
      if (!field) return
      this.addingField = false
      this.editingFieldIndex = index
      this.form = {
        label: field.label,
        type: field.type,
        mask: field.mask || '',
        align: (field.align as FieldAlign) || 'left',
        required: Boolean(field.required),
        min: field.type === 'number' && field.min !== undefined ? String(field.min) : '',
        max: field.type === 'number' && field.max !== undefined ? String(field.max) : '',
      }
      this.hint = 'Altere o nome ou o tipo e aplique a edição.'
    },
    stop() {
      this.addingField = false
      this.editingFieldIndex = null
      this.hint = 'Arraste sobre a página para marcar a área do novo campo.'
    },
    onAlignChange() {
      const docStore = useDocumentStore()
      if (this.editingFieldIndex === null) return
      docStore.currentFields[this.editingFieldIndex].align = this.form.align
    },
    applyEditingField(): boolean {
      const docStore = useDocumentStore()
      if (this.editingFieldIndex === null) return false
      const label = this.form.label.trim()
      if (!label) {
        docStore.status = 'Informe o nome do campo.'
        return false
      }
      const minValue = optionalNumber(this.form.min)
      const maxValue = optionalNumber(this.form.max)
      if (this.form.type === 'number' && Number.isFinite(minValue) && Number.isFinite(maxValue) && (minValue as number) > (maxValue as number)) {
        docStore.status = 'O valor mínimo deve ser menor ou igual ao valor máximo.'
        return false
      }
      const field = docStore.currentFields[this.editingFieldIndex]
      const previousName = field.name
      field.label = label
      field.name = this.uniqueName(label, this.editingFieldIndex)
      field.type = this.form.type
      field.mask = this.form.mask.trim()
      field.align = this.form.align
      field.required = this.form.required
      if (this.form.type === 'number') {
        if (Number.isFinite(minValue)) field.min = minValue as number
        else delete field.min
        if (Number.isFinite(maxValue)) field.max = maxValue as number
        else delete field.max
      } else {
        delete field.min
        delete field.max
      }
      field.height = normalizedFieldHeight(field)
      if (previousName !== field.name && Object.prototype.hasOwnProperty.call(docStore.formValues, previousName)) {
        docStore.formValues[field.name] = docStore.formValues[previousName]
        delete docStore.formValues[previousName]
      }
      return true
    },
    buildDraftField(label: string, page: number, box: { x: number; y: number; width: number; height: number }): Field | null {
      const minValue = optionalNumber(this.form.min)
      const maxValue = optionalNumber(this.form.max)
      if (this.form.type === 'number' && Number.isFinite(minValue) && Number.isFinite(maxValue) && (minValue as number) > (maxValue as number)) {
        return null
      }
      const field: Field = {
        name: this.uniqueName(label),
        label,
        type: this.form.type,
        mask: this.form.mask.trim(),
        align: this.form.align,
        page,
        ...box,
        source: 'manual',
        required: this.form.required,
      }
      if (this.form.type === 'number') {
        if (Number.isFinite(minValue)) field.min = minValue as number
        if (Number.isFinite(maxValue)) field.max = maxValue as number
      }
      return field
    },
  },
})
