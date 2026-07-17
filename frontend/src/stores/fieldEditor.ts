import { defineStore } from 'pinia'
import { useDocumentStore } from './document'
import { FIELD_CHOICE_HEIGHT, FIELD_CHOICE_WIDTH, normalizedFieldHeight, optionalNumber } from './document'
import type { Field, FieldAlign, FieldFormState, RadioOptionBox } from '../types'

const DIACRITICS_PATTERN = new RegExp(
  `[${String.fromCharCode(0x0300)}-${String.fromCharCode(0x036f)}]`,
  'g',
)

function emptyForm(): FieldFormState {
  return { label: '', type: 'text', mask: '', align: 'left', required: false, min: '', max: '', options: '' }
}

function parsedOptions(value: string): string[] {
  return value.split(/\r?\n/).map((option) => option.trim()).filter(Boolean)
}

function validRadioOptions(options: string[]): boolean {
  return options.length >= 2 && options.length <= 100 && options.every((option) => option.length <= 160) && new Set(options).size === options.length
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
    pendingRadioBoxes: [] as RadioOptionBox[],
    targetCheckboxGroup: null as { groupId: string; label: string } | null,
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
      this.pendingRadioBoxes = []
      this.targetCheckboxGroup = null
      this.hint = 'Arraste sobre a página para marcar a área do novo campo.'
    },
    startAddCheckboxInGroup(groupId: string, label: string) {
      this.addingField = true
      this.editingFieldIndex = null
      this.form = { ...emptyForm(), type: 'checkbox' }
      this.pendingRadioBoxes = []
      this.targetCheckboxGroup = { groupId, label }
      this.hint = `Informe o nome e arraste sobre a página para adicionar um checkbox ao grupo "${label}".`
    },
    startEdit(index: number) {
      const docStore = useDocumentStore()
      const field = docStore.currentFields[index]
      if (!field) return
      this.addingField = false
      this.editingFieldIndex = index
      this.pendingRadioBoxes = []
      this.targetCheckboxGroup = null
      this.form = {
        label: field.label,
        type: field.type,
        mask: field.mask || '',
        align: (field.align as FieldAlign) || 'left',
        required: Boolean(field.required),
        min: field.type === 'number' && field.min !== undefined ? String(field.min) : '',
        max: field.type === 'number' && field.max !== undefined ? String(field.max) : '',
        options: field.type === 'radio' ? (field.options || []).join('\n') : '',
      }
      this.hint = 'Altere o nome ou o tipo e aplique a edição.'
    },
    stop() {
      this.addingField = false
      this.editingFieldIndex = null
      this.pendingRadioBoxes = []
      this.targetCheckboxGroup = null
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
      const options = parsedOptions(this.form.options)
      if (this.form.type === 'number' && Number.isFinite(minValue) && Number.isFinite(maxValue) && (minValue as number) > (maxValue as number)) {
        docStore.status = 'O valor mínimo deve ser menor ou igual ao valor máximo.'
        return false
      }
      if (this.form.type === 'radio' && !validRadioOptions(options)) {
        docStore.status = 'Informe de 2 a 100 opções diferentes (até 160 caracteres cada) para o campo radio.'
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
      if (this.form.type === 'radio') {
        const previousBoxes = Array.isArray(field.option_boxes) ? field.option_boxes : []
        field.options = options
        field.option_boxes = options.map((value, index) => ({
          ...(previousBoxes.find((box) => box.value === value) || previousBoxes[index] || {
            page: field.page, x: field.x + index * 22, y: field.y, width: FIELD_CHOICE_WIDTH, height: FIELD_CHOICE_HEIGHT,
          }),
          value,
          width: FIELD_CHOICE_WIDTH,
          height: FIELD_CHOICE_HEIGHT,
        }))
      } else {
        delete field.options
        delete field.option_boxes
      }
      field.height = normalizedFieldHeight(field)
      if (previousName !== field.name && Object.prototype.hasOwnProperty.call(docStore.formValues, previousName)) {
        docStore.formValues[field.name] = docStore.formValues[previousName]
        delete docStore.formValues[previousName]
      }
      if (field.type === 'radio' && !field.options?.includes(docStore.formValues[field.name])) {
        delete docStore.formValues[field.name]
      }
      return true
    },
    buildDraftField(label: string, page: number, box: { x: number; y: number; width: number; height: number }): Field | null {
      const minValue = optionalNumber(this.form.min)
      const maxValue = optionalNumber(this.form.max)
      const options = parsedOptions(this.form.options)
      if (this.form.type === 'number' && Number.isFinite(minValue) && Number.isFinite(maxValue) && (minValue as number) > (maxValue as number)) {
        return null
      }
      if (this.form.type === 'radio' && !validRadioOptions(options)) return null
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
      if (field.type === 'checkbox' || field.type === 'radio') {
        field.width = FIELD_CHOICE_WIDTH
        field.height = FIELD_CHOICE_HEIGHT
      }
      if (field.type === 'checkbox' && this.targetCheckboxGroup) {
        field.group_id = this.targetCheckboxGroup.groupId
        field.group_label = this.targetCheckboxGroup.label
      }
      if (this.form.type === 'number') {
        if (Number.isFinite(minValue)) field.min = minValue as number
        if (Number.isFinite(maxValue)) field.max = maxValue as number
      }
      if (this.form.type === 'radio') {
        const optionIndex = this.pendingRadioBoxes.length
        this.pendingRadioBoxes.push({ value: options[optionIndex], page, ...box, width: FIELD_CHOICE_WIDTH, height: FIELD_CHOICE_HEIGHT })
        if (this.pendingRadioBoxes.length < options.length) {
          this.hint = `Desenhe a área da opção “${options[this.pendingRadioBoxes.length]}” (${this.pendingRadioBoxes.length + 1}/${options.length}).`
          return null
        }
        field.options = options
        field.option_boxes = this.pendingRadioBoxes.map((item) => ({ ...item }))
        const first = field.option_boxes[0]
        Object.assign(field, { page: first.page, x: first.x, y: first.y, width: first.width, height: first.height })
      }
      return field
    },
  },
})
