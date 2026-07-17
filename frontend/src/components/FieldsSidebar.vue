<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import {
  FIELD_CHOICE_HEIGHT,
  FIELD_CHOICE_WIDTH,
  fieldTextAlign,
  fieldValidationSummary,
  normalizeFieldBox,
  useDocumentStore,
} from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'
import { useModalsStore } from '../stores/modals'
import type { Field, FieldAlign, FieldType } from '../types'

interface FieldEntry {
  field: Field
  index: number
  label?: string
  optionIndex?: number
  optionValue?: string
}

interface FieldTreeGroup {
  kind: 'group'
  groupType: 'checkbox' | 'radio'
  groupId: string
  label: string
  index?: number
  field?: Field
  fields: FieldEntry[]
}

interface FieldTreeField {
  kind: 'field'
  field: Field
  index: number
}

type FieldTreeNode = FieldTreeGroup | FieldTreeField

const docStore = useDocumentStore()
const fieldEditor = useFieldEditorStore()
const modals = useModalsStore()

const props = defineProps<{ activeFieldName?: string | null }>()
const emit = defineEmits<{ scrollTo: [string]; openValue: [number] }>()

const isNumber = computed(() => fieldEditor.form.type === 'number')
const isRadio = computed(() => fieldEditor.form.type === 'radio')
const draggedFieldName = ref<string | null>(null)
const dragOverFieldName = ref<string | null>(null)
const selectedFieldNames = ref<string[]>([])
const fieldsScroll = ref<HTMLElement | null>(null)
const fieldRowElements = new Map<string, HTMLElement>()
const collapsedGroupIds = ref<string[]>([])
const checkboxFields = computed(() => docStore.currentFields.filter((field) => field.type === 'checkbox'))
const selectedCheckboxFields = computed(() => {
  const selected = new Set(selectedFieldNames.value)
  return docStore.currentFields.filter((field) => field.type === 'checkbox' && selected.has(field.name))
})
const selectedGroupedCheckboxFields = computed(() => selectedCheckboxFields.value.filter((field) => Boolean(field.group_id)))
const selectedRadioFields = computed(() => {
  const selected = new Set(selectedFieldNames.value)
  return docStore.currentFields.filter((field) => field.type === 'radio' && selected.has(field.name))
})
const selectedFieldCount = computed(() => {
  const selected = new Set(selectedFieldNames.value)
  return docStore.currentFields.filter((field) => selected.has(field.name)).length
})
const canMoveSelectedUp = computed(() => canMoveSelection('up'))
const canMoveSelectedDown = computed(() => canMoveSelection('down'))
const allCheckboxesSelected = computed(() => (
  checkboxFields.value.length > 0
  && checkboxFields.value.every((field) => selectedFieldNames.value.includes(field.name))
))
const canGroupSelectedCheckboxes = computed(() => selectedCheckboxFields.value.length >= 2)
const canUngroupSelectedCheckboxes = computed(() => selectedGroupedCheckboxFields.value.length > 0)
const fieldTreeNodes = computed<FieldTreeNode[]>(() => {
  const nodes: FieldTreeNode[] = []
  const groups = new Map<string, FieldTreeGroup>()
  docStore.currentFields.forEach((field, index) => {
    if (field.type === 'radio') {
      nodes.push({
        kind: 'group',
        groupType: 'radio',
        groupId: `radio:${field.name}`,
        label: field.label,
        index,
        field,
        fields: (field.options || []).map((option, optionIndex) => ({
          field,
          index,
          label: option,
          optionIndex,
          optionValue: option,
        })),
      })
      return
    }

    const groupId = field.type === 'checkbox' ? String(field.group_id || '').trim() : ''
    if (!groupId) {
      nodes.push({ kind: 'field', field, index })
      return
    }
    let group = groups.get(groupId)
    if (!group) {
      group = { kind: 'group', groupType: 'checkbox', groupId, label: String(field.group_label || 'Grupo de checkboxes'), fields: [] }
      groups.set(groupId, group)
      nodes.push(group)
    }
    group.fields.push({ field, index })
  })
  return nodes
})
const radioDrawingHint = computed(() => {
  if (!isRadio.value) return fieldEditor.hint
  const options = fieldEditor.form.options.split(/\r?\n/).map((option) => option.trim()).filter(Boolean)
  const index = fieldEditor.pendingRadioBoxes?.length || 0
  return options[index]
    ? `Desenhe a área da opção “${options[index]}” (${index + 1}/${options.length}).`
    : 'Informe as opções antes de desenhar as áreas.'
})

function groupFieldNames(group: FieldTreeGroup): string[] {
  return Array.from(new Set(group.fields.map(({ field }) => field.name)))
}

function groupSummary(group: FieldTreeGroup): string {
  return group.groupType === 'radio'
    ? `${group.fields.length} opção(ões)`
    : `${group.fields.length} checkbox(es)`
}

function groupChildLabel(entry: FieldEntry): string {
  return entry.label || entry.field.label
}

function groupChildSummary(entry: FieldEntry): string {
  const box = entry.optionIndex !== undefined ? entry.field.option_boxes?.[entry.optionIndex] : null
  const page = Number(box?.page) || entry.field.page
  const parts = [entry.field.type, `pagina ${page}`, entry.field.source, fieldTextAlign(entry.field)]
  if (entry.field.type === 'radio') parts.push('opção')
  return parts.filter(Boolean).join(' · ')
}

function isGroupCollapsed(groupId: string): boolean {
  return collapsedGroupIds.value.includes(groupId)
}

function toggleGroup(groupId: string) {
  const collapsed = new Set(collapsedGroupIds.value)
  if (collapsed.has(groupId)) collapsed.delete(groupId)
  else collapsed.add(groupId)
  collapsedGroupIds.value = Array.from(collapsed)
}

function isGroupSelected(group: FieldTreeGroup): boolean {
  const selected = new Set(selectedFieldNames.value)
  return group.fields.length > 0 && group.fields.every(({ field }) => selected.has(field.name))
}

function setGroupSelected(group: FieldTreeGroup, checked: boolean) {
  const selected = new Set(selectedFieldNames.value)
  group.fields.forEach(({ field }) => {
    if (checked) selected.add(field.name)
    else selected.delete(field.name)
  })
  selectedFieldNames.value = Array.from(selected)
}

function uniqueGroupId(label: string): string {
  const base = (
    label
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 48) || 'grupo'
  )
  const used = new Set(docStore.currentFields.map((field) => String(field.group_id || '')).filter(Boolean))
  let groupId = `checkbox_${base}`
  let suffix = 2
  while (used.has(groupId)) groupId = `checkbox_${base}_${suffix++}`
  return groupId
}

async function groupSelectedCheckboxes() {
  if (!canGroupSelectedCheckboxes.value) {
    docStore.status = 'Selecione pelo menos 2 checkboxes para agrupar.'
    return
  }
  const label = await modals.showTextInput({
    title: 'Agrupar checkboxes',
    message: `${selectedCheckboxFields.value.length} checkbox(es) serão exibidos como filhos do grupo.`,
    label: 'Nome do grupo',
    value: selectedCheckboxFields.value[0]?.group_label || 'Grupo de checkboxes',
    confirmLabel: 'Agrupar',
  })
  if (!label) return
  const groupId = uniqueGroupId(label)
  const selected = new Set(selectedCheckboxFields.value.map((field) => field.name))
  docStore.currentFields.forEach((field) => {
    if (field.type === 'checkbox' && selected.has(field.name)) {
      field.group_id = groupId
      field.group_label = label
    }
  })
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== groupId)
  docStore.status = `${selected.size} checkbox(es) agrupado(s). Clique em Salvar alterações.`
}

async function renameGroup(group: FieldTreeGroup) {
  const label = await modals.showTextInput({
    title: 'Renomear grupo',
    label: 'Nome do grupo',
    value: group.label,
    confirmLabel: 'Renomear',
  })
  if (!label) return
  if (group.groupType === 'radio' && group.field) {
    const previousName = group.field.name
    group.field.label = label
    group.field.name = fieldEditor.uniqueName(label, group.index ?? null)
    if (previousName !== group.field.name) {
      if (Object.prototype.hasOwnProperty.call(docStore.formValues, previousName)) {
        docStore.formValues[group.field.name] = docStore.formValues[previousName]
        delete docStore.formValues[previousName]
      }
      selectedFieldNames.value = selectedFieldNames.value.map((name) => (name === previousName ? group.field!.name : name))
    }
  } else {
    docStore.currentFields.forEach((field) => {
      if (field.group_id === group.groupId) field.group_label = label
    })
  }
  docStore.status = 'Grupo renomeado. Clique em Salvar alterações.'
}

function ungroupFieldNames(fieldNames: string[]) {
  const names = new Set(fieldNames)
  docStore.currentFields.forEach((field) => {
    if (field.type === 'checkbox' && names.has(field.name)) {
      delete field.group_id
      delete field.group_label
    }
  })
}

function ungroupSelectedCheckboxes() {
  if (!canUngroupSelectedCheckboxes.value) {
    docStore.status = 'Selecione checkbox(es) agrupado(s) para desagrupar.'
    return
  }
  const count = selectedGroupedCheckboxFields.value.length
  ungroupFieldNames(selectedGroupedCheckboxFields.value.map((field) => field.name))
  docStore.status = `${count} checkbox(es) removido(s) do grupo. Clique em Salvar alterações.`
}

function ungroupTreeGroup(group: FieldTreeGroup) {
  if (group.groupType === 'radio') return
  ungroupFieldNames(groupFieldNames(group))
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
  docStore.status = `Grupo "${group.label}" desfeito. Clique em Salvar alterações.`
}

function addRadioOptionToGroup(group: FieldTreeGroup) {
  if (group.index === undefined) return
  editField(group.index)
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
  docStore.status = `Edite as opções do grupo radio "${group.label}".`
}

function addGroupItem(group: FieldTreeGroup) {
  if (group.groupType === 'radio') addRadioOptionToGroup(group)
  else addCheckboxToGroup(group)
}

function deleteGroup(group: FieldTreeGroup) {
  if (group.groupType === 'radio' && group.index !== undefined) {
    deleteField(group.index)
    collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
    return
  }
  ungroupTreeGroup(group)
}

function addCheckboxToGroup(group: FieldTreeGroup) {
  if (!docStore.currentJobId) return
  fieldEditor.startAddCheckboxInGroup(group.groupId, group.label)
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
  docStore.status = `Informe o nome e desenhe o novo checkbox do grupo "${group.label}".`
}

function removeFieldFromGroup(field: Field) {
  if (field.type !== 'checkbox' || !field.group_id) return
  const groupLabel = String(field.group_label || 'grupo')
  delete field.group_id
  delete field.group_label
  selectedFieldNames.value = selectedFieldNames.value.filter((name) => name !== field.name)
  docStore.status = `"${field.label}" removido de "${groupLabel}". Clique em Salvar alterações.`
}

function removeRadioOption(entry: FieldEntry) {
  if (entry.field.type !== 'radio' || entry.optionIndex === undefined) return
  const options = [...(entry.field.options || [])]
  if (options.length <= 2) {
    docStore.status = 'Campo radio deve manter pelo menos 2 opções.'
    return
  }
  const [removed] = options.splice(entry.optionIndex, 1)
  const previousBoxes = entry.field.option_boxes || []
  entry.field.options = options
  entry.field.option_boxes = options.map((option, index) => {
    const box = previousBoxes.find((item) => item.value === option) || previousBoxes[index]
    return {
      value: option,
      page: Number(box?.page) || entry.field.page,
      x: Number.isFinite(Number(box?.x)) ? Number(box!.x) : entry.field.x + index * 22,
      y: Number.isFinite(Number(box?.y)) ? Number(box!.y) : entry.field.y,
      width: FIELD_CHOICE_WIDTH,
      height: FIELD_CHOICE_HEIGHT,
    }
  })
  if (docStore.formValues[entry.field.name] === removed) delete docStore.formValues[entry.field.name]
  docStore.status = `Opção "${removed}" removida do grupo radio. Clique em Salvar alterações.`
}

function deleteGroupChild(group: FieldTreeGroup, entry: FieldEntry) {
  if (group.groupType === 'radio') removeRadioOption(entry)
  else deleteField(entry.index)
}

function groupDropCandidates(sourceName: string | undefined, group: FieldTreeGroup): Field[] {
  if (!sourceName) return []
  const selected = new Set(selectedFieldNames.value)
  const sourceIsSelected = selected.has(sourceName) && selected.size > 1
  const candidates = sourceIsSelected
    ? docStore.currentFields.filter((field) => selected.has(field.name))
    : docStore.currentFields.filter((field) => field.name === sourceName)
  return candidates.filter((field) => (
    field.type === 'checkbox'
    && (group.groupType === 'radio' || field.group_id !== group.groupId)
  ))
}

function addCheckboxesToRadioGroup(group: FieldTreeGroup, checkboxes: Field[]) {
  if (group.groupType !== 'radio' || !group.field || !checkboxes.length) return
  const usedOptions = new Set(group.field.options || [])
  const nextOptions = [...(group.field.options || [])]
  const nextBoxes = [...(group.field.option_boxes || [])]
  let radioHasValue = Object.prototype.hasOwnProperty.call(docStore.formValues, group.field.name)

  checkboxes.forEach((field) => {
    const option = uniqueOptionLabel(field.label, usedOptions)
    nextOptions.push(option)
    nextBoxes.push({
      value: option,
      page: field.page,
      x: field.x,
      y: field.y,
      width: FIELD_CHOICE_WIDTH,
      height: FIELD_CHOICE_HEIGHT,
    })
    if (!radioHasValue && Boolean(docStore.formValues[field.name])) {
      docStore.formValues[group.field!.name] = option
      radioHasValue = true
    }
    delete docStore.formValues[field.name]
  })

  const removed = new Set(checkboxes.map((field) => field.name))
  group.field.options = nextOptions
  group.field.option_boxes = nextBoxes
  docStore.currentFields = docStore.currentFields.filter((field) => !removed.has(field.name))
  selectedFieldNames.value = selectedFieldNames.value.filter((name) => !removed.has(name))
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
  docStore.status = `${checkboxes.length} checkbox(es) convertido(s) em opção(ões) do grupo radio "${group.label}". Clique em Salvar alterações.`
}

function dragOverGroup(event: DragEvent, group: FieldTreeGroup) {
  const sourceName = draggedFieldName.value || event.dataTransfer?.getData('text/plain')
  if (!groupDropCandidates(sourceName, group).length) return
  event.preventDefault()
  dragOverFieldName.value = `group:${group.groupId}`
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function dropFieldOnGroup(event: DragEvent, group: FieldTreeGroup) {
  event.preventDefault()
  const sourceName = draggedFieldName.value || event.dataTransfer?.getData('text/plain')
  const candidates = groupDropCandidates(sourceName, group)
  if (!candidates.length) {
    endFieldDrag()
    return
  }
  if (group.groupType === 'radio') {
    addCheckboxesToRadioGroup(group, candidates)
    endFieldDrag()
    return
  }
  candidates.forEach((field) => {
    field.group_id = group.groupId
    field.group_label = group.label
  })
  collapsedGroupIds.value = collapsedGroupIds.value.filter((id) => id !== group.groupId)
  docStore.status = `${candidates.length} checkbox(es) adicionado(s) ao grupo "${group.label}". Clique em Salvar alterações.`
  endFieldDrag()
}

function setFieldRowRef(fieldName: string, element: unknown) {
  if (element instanceof HTMLElement) fieldRowElements.set(fieldName, element)
  else fieldRowElements.delete(fieldName)
}

async function scrollFieldRowIntoView(fieldName?: string | null) {
  if (!fieldName) return
  const field = docStore.currentFields.find((item) => item.name === fieldName)
  const groupId = field?.type === 'radio' ? `radio:${field.name}` : field?.group_id ? String(field.group_id) : ''
  if (groupId && isGroupCollapsed(groupId)) toggleGroup(groupId)
  await nextTick()
  const panel = fieldsScroll.value
  const row = fieldRowElements.get(fieldName)
  if (!panel || !row) return
  const panelRect = panel.getBoundingClientRect()
  const rowRect = row.getBoundingClientRect()
  const top = rowRect.top - panelRect.top + panel.scrollTop - (panel.clientHeight / 2) + (row.clientHeight / 2)
  panel.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}

watch(
  () => props.activeFieldName,
  (fieldName) => {
    void scrollFieldRowIntoView(fieldName)
  },
)

function addField() {
  if (!docStore.currentJobId) return
  fieldEditor.startAdd()
  docStore.status = 'Informe o nome e arraste sobre a página.'
}

function editField(index: number) {
  fieldEditor.startEdit(index)
}

function deleteField(index: number) {
  const field = docStore.currentFields[index]
  if (field) delete docStore.formValues[field.name]
  if (field) selectedFieldNames.value = selectedFieldNames.value.filter((name) => name !== field.name)
  docStore.currentFields.splice(index, 1)
  docStore.status = 'Campo excluído. Clique em Salvar alterações.'
}

function setFieldSelected(fieldName: string, checked: boolean) {
  const selected = new Set(selectedFieldNames.value)
  if (checked) selected.add(fieldName)
  else selected.delete(fieldName)
  selectedFieldNames.value = Array.from(selected)
}

function selectAllCheckboxFields() {
  selectedFieldNames.value = checkboxFields.value.map((field) => field.name)
  docStore.status = checkboxFields.value.length
    ? `${checkboxFields.value.length} checkbox(es) selecionado(s).`
    : 'Nenhum campo checkbox encontrado.'
}

function clearFieldSelection() {
  selectedFieldNames.value = []
}

function uniqueOptionLabel(label: string, used: Set<string>): string {
  const base = (label.trim() || 'Opção').slice(0, 160)
  let value = base
  let suffix = 2
  while (used.has(value)) {
    const ending = ` ${suffix++}`
    value = `${base.slice(0, Math.max(1, 160 - ending.length))}${ending}`
  }
  used.add(value)
  return value
}

function uniqueFieldName(label: string, used: Set<string>): string {
  const base = fieldEditor.uniqueName(label)
  let name = base
  let suffix = 2
  while (used.has(name)) name = `${base}_${suffix++}`
  used.add(name)
  return name
}

function convertSelectedCheckboxesToRadio() {
  const selected = new Set(selectedFieldNames.value)
  const entries = docStore.currentFields
    .map((field, index) => ({ field, index }))
    .filter(({ field }) => field.type === 'checkbox' && selected.has(field.name))

  if (entries.length < 2) {
    docStore.status = 'Selecione pelo menos 2 checkboxes para converter em radio.'
    return
  }

  const usedOptions = new Set<string>()
  const options = entries.map(({ field }) => uniqueOptionLabel(field.label, usedOptions))
  const first = entries[0].field
  const radioField: Field = normalizeFieldBox({
    ...first,
    name: fieldEditor.uniqueName('Grupo de opções'),
    label: 'Grupo de opções',
    type: 'radio',
    mask: '',
    align: first.align || 'left',
    required: entries.some(({ field }) => Boolean(field.required)),
    source: 'manual',
    page: first.page,
    x: first.x,
    y: first.y,
    width: FIELD_CHOICE_WIDTH,
    height: FIELD_CHOICE_HEIGHT,
    options,
    option_boxes: entries.map(({ field }, index) => ({
      value: options[index],
      page: field.page,
      x: field.x,
      y: field.y,
      width: FIELD_CHOICE_WIDTH,
      height: FIELD_CHOICE_HEIGHT,
    })),
  })
  delete radioField.min
  delete radioField.max

  let inserted = false
  docStore.currentFields = docStore.currentFields.flatMap((field) => {
    if (field.type !== 'checkbox' || !selected.has(field.name)) return [field]
    delete docStore.formValues[field.name]
    if (inserted) return []
    inserted = true
    return [radioField]
  })
  clearFieldSelection()
  fieldEditor.stop()
  docStore.status = `${entries.length} checkbox(es) convertido(s) em um grupo radio. Clique em Salvar alterações.`
}

function convertSelectedRadiosToCheckboxes() {
  const selected = new Set(selectedFieldNames.value)
  const radios = docStore.currentFields.filter((field) => field.type === 'radio' && selected.has(field.name))

  if (!radios.length) {
    docStore.status = 'Selecione um grupo radio para converter em checkboxes.'
    return
  }

  const usedNames = new Set(docStore.currentFields.map((field) => field.name))
  let convertedOptions = 0
  docStore.currentFields = docStore.currentFields.flatMap((field) => {
    if (field.type !== 'radio' || !selected.has(field.name)) return [field]

    const options = Array.isArray(field.options) ? field.options : []
    const boxes = Array.isArray(field.option_boxes) ? field.option_boxes : []
    const selectedValue = docStore.formValues[field.name]
    delete docStore.formValues[field.name]

    const checkboxes = options.map((option, index): Field => {
      const box = boxes.find((item) => item.value === option) || boxes[index]
      const checkbox = normalizeFieldBox({
        ...field,
        name: uniqueFieldName(option, usedNames),
        label: option,
        type: 'checkbox',
        mask: '',
        source: 'manual',
        page: Number(box?.page) || field.page,
        x: Number.isFinite(Number(box?.x)) ? Number(box!.x) : field.x + index * 22,
        y: Number.isFinite(Number(box?.y)) ? Number(box!.y) : field.y,
        width: FIELD_CHOICE_WIDTH,
        height: FIELD_CHOICE_HEIGHT,
      })
      delete checkbox.options
      delete checkbox.option_boxes
      delete checkbox.min
      delete checkbox.max
      if (selectedValue === option) docStore.formValues[checkbox.name] = true
      return checkbox
    })

    convertedOptions += checkboxes.length
    return checkboxes.length ? checkboxes : [field]
  })

  clearFieldSelection()
  fieldEditor.stop()
  docStore.status = convertedOptions
    ? `${radios.length} grupo(s) radio convertido(s) em ${convertedOptions} checkbox(es). Clique em Salvar alterações.`
    : 'Nenhuma opção radio encontrada para converter.'
}

function canMoveSelection(direction: 'up' | 'down'): boolean {
  const selected = new Set(selectedFieldNames.value)
  if (!selected.size) return false
  return direction === 'up'
    ? docStore.currentFields.some((field, index) => selected.has(field.name) && index > 0 && !selected.has(docStore.currentFields[index - 1].name))
    : docStore.currentFields.some((field, index) => selected.has(field.name) && index < docStore.currentFields.length - 1 && !selected.has(docStore.currentFields[index + 1].name))
}

function syncEditingIndexAfterReorder(editingFieldName: string | null) {
  if (!editingFieldName) return
  const nextIndex = docStore.currentFields.findIndex((field) => field.name === editingFieldName)
  fieldEditor.editingFieldIndex = nextIndex >= 0 ? nextIndex : null
}

function moveSelectedFields(direction: 'up' | 'down') {
  if (!canMoveSelection(direction)) return
  const selected = new Set(selectedFieldNames.value)
  const editingFieldName = fieldEditor.editingFieldIndex !== null
    ? docStore.currentFields[fieldEditor.editingFieldIndex]?.name || null
    : null

  if (direction === 'up') {
    for (let index = 1; index < docStore.currentFields.length; index += 1) {
      if (selected.has(docStore.currentFields[index].name) && !selected.has(docStore.currentFields[index - 1].name)) {
        const [field] = docStore.currentFields.splice(index, 1)
        docStore.currentFields.splice(index - 1, 0, field)
      }
    }
  } else {
    for (let index = docStore.currentFields.length - 2; index >= 0; index -= 1) {
      if (selected.has(docStore.currentFields[index].name) && !selected.has(docStore.currentFields[index + 1].name)) {
        const [field] = docStore.currentFields.splice(index, 1)
        docStore.currentFields.splice(index + 1, 0, field)
      }
    }
  }

  syncEditingIndexAfterReorder(editingFieldName)
  docStore.status = `${selectedFieldCount.value} campo(s) selecionado(s) movido(s). Clique em Salvar alterações.`
}

function reorderFieldOrSelection(index: number, direction: 'up' | 'down') {
  const field = docStore.currentFields[index]
  if (field && selectedFieldNames.value.includes(field.name) && selectedFieldCount.value > 1) {
    moveSelectedFields(direction)
    return
  }
  reorderField(index, direction === 'up' ? index - 1 : index + 1)
}

function moveSelectedFieldsToTarget(targetName: string) {
  const selected = new Set(selectedFieldNames.value)
  if (selected.size < 2 || selected.has(targetName)) return false

  const editingFieldName = fieldEditor.editingFieldIndex !== null
    ? docStore.currentFields[fieldEditor.editingFieldIndex]?.name || null
    : null
  const movingFields = docStore.currentFields.filter((field) => selected.has(field.name))
  const remainingFields = docStore.currentFields.filter((field) => !selected.has(field.name))
  const targetIndex = remainingFields.findIndex((field) => field.name === targetName)
  if (targetIndex < 0 || !movingFields.length) return false

  remainingFields.splice(targetIndex, 0, ...movingFields)
  docStore.currentFields = remainingFields
  syncEditingIndexAfterReorder(editingFieldName)
  docStore.status = `${movingFields.length} campo(s) selecionado(s) movido(s). Clique em Salvar alterações.`
  return true
}

function reorderField(fromIndex: number, toIndex: number) {
  if (
    fromIndex === toIndex
    || fromIndex < 0
    || toIndex < 0
    || fromIndex >= docStore.currentFields.length
    || toIndex >= docStore.currentFields.length
  ) return

  const editingIndex = fieldEditor.editingFieldIndex
  const [field] = docStore.currentFields.splice(fromIndex, 1)
  docStore.currentFields.splice(toIndex, 0, field)

  if (editingIndex !== null) {
    if (editingIndex === fromIndex) fieldEditor.editingFieldIndex = toIndex
    else if (fromIndex < editingIndex && toIndex >= editingIndex) fieldEditor.editingFieldIndex = editingIndex - 1
    else if (fromIndex > editingIndex && toIndex <= editingIndex) fieldEditor.editingFieldIndex = editingIndex + 1
  }

  docStore.status = 'Ordem dos campos alterada. Clique em Salvar alterações.'
}

function startFieldDrag(event: DragEvent, index: number) {
  const field = docStore.currentFields[index]
  if (!field) return
  draggedFieldName.value = field.name
  event.dataTransfer?.setData('text/plain', field.name)
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function dragOverField(event: DragEvent, fieldName: string) {
  if (!draggedFieldName.value || draggedFieldName.value === fieldName) return
  event.preventDefault()
  dragOverFieldName.value = fieldName
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function dropField(event: DragEvent, targetName: string) {
  event.preventDefault()
  const sourceName = draggedFieldName.value || event.dataTransfer?.getData('text/plain')
  if (sourceName && selectedFieldNames.value.includes(sourceName) && selectedFieldCount.value > 1) {
    moveSelectedFieldsToTarget(targetName)
    endFieldDrag()
    return
  }
  const fromIndex = docStore.currentFields.findIndex((field) => field.name === sourceName)
  const toIndex = docStore.currentFields.findIndex((field) => field.name === targetName)
  reorderField(fromIndex, toIndex)
  endFieldDrag()
}

function endFieldDrag() {
  draggedFieldName.value = null
  dragOverFieldName.value = null
}

function cancelEdit() {
  fieldEditor.stop()
}

function onTypeChange() {
  if (fieldEditor.form.type !== 'number') {
    fieldEditor.form.min = ''
    fieldEditor.form.max = ''
  }
}

async function saveFields() {
  if (fieldEditor.editingFieldIndex !== null && !fieldEditor.applyEditingField()) return
  await docStore.saveFields()
}

async function discardFields() {
  if (!docStore.fieldsChanged) return
  const confirmed = await modals.showConfirm({
    title: 'Descartar alterações?',
    message: 'Todas as alterações ainda não salvas nos campos deste documento serão perdidas.',
    confirmLabel: 'Descartar alterações',
    danger: true,
  })
  if (!confirmed) return
  fieldEditor.stop()
  clearFieldSelection()
  docStore.discardFields()
}

function fieldSummary(field: { type: FieldType; page: number; source?: string; align?: FieldAlign; mask?: string; name: string }): string {
  const parts = [field.type, `pagina ${field.page}`, field.source, fieldTextAlign(field)]
  if (field.mask) parts.push('máscara ' + field.mask)
  const validation = fieldValidationSummary(field as any)
  if (validation) parts.push(validation)
  if (Object.prototype.hasOwnProperty.call(docStore.formValues, field.name)) parts.push('preenchido')
  return parts.filter(Boolean).join(' · ')
}
</script>

<template>
  <aside class="fields">
    <div class="fields-header">
      <div class="fields-title-row">
        <h3>Campos detectados</h3>
        <div class="field-primary-actions" aria-label="Ações principais">
          <button type="button" @click="addField">+ Campo</button>
          <button type="button" @click="saveFields">Salvar</button>
          <button type="button" class="button-secondary" :disabled="!docStore.fieldsChanged" @click="discardFields">Descartar</button>
        </div>
      </div>
      <div class="field-toolbar" aria-label="Ações de edição dos campos">
        <div class="field-toolbar-group" aria-label="Seleção">
          <button type="button" class="button-secondary" :disabled="!checkboxFields.length || allCheckboxesSelected" @click="selectAllCheckboxFields">Selecionar</button>
          <button type="button" class="button-secondary" :disabled="!selectedFieldNames.length" @click="clearFieldSelection">Limpar</button>
        </div>
        <div class="field-toolbar-group" aria-label="Agrupamento">
          <button type="button" :disabled="!canGroupSelectedCheckboxes" @click="groupSelectedCheckboxes">Agrupar</button>
          <button type="button" class="button-secondary" :disabled="!canUngroupSelectedCheckboxes" @click="ungroupSelectedCheckboxes">Desagrupar</button>
        </div>
        <div class="field-toolbar-group" aria-label="Conversão de tipos">
          <button type="button" :disabled="selectedCheckboxFields.length < 2" @click="convertSelectedCheckboxesToRadio">Checkbox → radio</button>
          <button type="button" :disabled="!selectedRadioFields.length" @click="convertSelectedRadiosToCheckboxes">Radio → checkbox</button>
        </div>
        <div class="field-toolbar-group field-toolbar-group-compact" aria-label="Reordenação">
          <button type="button" class="button-secondary field-icon-button" :disabled="!canMoveSelectedUp" aria-label="Mover seleção para cima" title="Mover seleção para cima" @click="moveSelectedFields('up')">↑</button>
          <button type="button" class="button-secondary field-icon-button" :disabled="!canMoveSelectedDown" aria-label="Mover seleção para baixo" title="Mover seleção para baixo" @click="moveSelectedFields('down')">↓</button>
        </div>
      </div>
      <small class="fields-help">Dê duplo clique para editar. Arraste para mover ou use as setas para reordenar.</small>
      <div class="editor" :class="{ show: fieldEditor.addingField }">
        <input v-model="fieldEditor.form.label" maxlength="160" placeholder="Nome do campo" aria-label="Nome do campo">
        <select v-model="fieldEditor.form.type" aria-label="Tipo do campo" @change="onTypeChange">
          <option value="text">Texto</option><option value="date">Data</option>
          <option value="time">Horário</option><option value="email">E-mail</option>
          <option value="tel">Telefone</option><option value="number">Número</option>
          <option value="checkbox">Checkbox</option><option value="radio">Grupo de opções (radio)</option><option value="textarea">Área de texto</option>
        </select>
        <textarea v-show="isRadio" v-model="fieldEditor.form.options" rows="4" maxlength="16000" placeholder="Uma opção por linha" aria-label="Opções do campo radio" :disabled="!isRadio"></textarea>
        <input v-model="fieldEditor.form.mask" maxlength="80" placeholder="Máscara opcional, ex.: (00) 00000-0000" aria-label="Máscara do campo">
        <select v-model="fieldEditor.form.align" aria-label="Alinhamento do texto" @change="fieldEditor.onAlignChange">
          <option value="left">Alinhado à esquerda</option>
          <option value="center">Centralizado</option>
          <option value="justify">Justificado</option>
          <option value="right">Alinhado à direita</option>
        </select>
        <label class="checkbox-row">
          <input v-model="fieldEditor.form.required" type="checkbox"> Campo obrigatório
        </label>
        <div class="number-rules" v-show="isNumber">
          <input v-model="fieldEditor.form.min" type="number" step="any" placeholder="Valor mínimo" aria-label="Valor mínimo" :disabled="!isNumber">
          <input v-model="fieldEditor.form.max" type="number" step="any" placeholder="Valor máximo" aria-label="Valor máximo" :disabled="!isNumber">
        </div>
        <span class="mask-hint">0 = número, A = letra, * = letra ou número. Os demais caracteres são fixos.</span>
        <small>{{ radioDrawingHint }}</small>
        <button type="button" @click="cancelEdit">Cancelar</button>
      </div>
    </div>
    <div ref="fieldsScroll" class="fields-scroll">
      <div id="fields">
      <template v-if="docStore.currentFields.length">
        <template v-for="node in fieldTreeNodes" :key="node.kind === 'group' ? node.groupId : node.field.name">
          <div v-if="node.kind === 'group'" class="field-group" :class="{ active: node.fields.some(({ field }) => props.activeFieldName === field.name) }">
            <div
              :ref="(element) => node.groupType === 'radio' && node.field ? setFieldRowRef(node.field.name, element) : undefined"
              class="field-group-header"
              :class="{ 'drag-over': dragOverFieldName === `group:${node.groupId}` }"
              @dragover="dragOverGroup($event, node)"
              @drop="dropFieldOnGroup($event, node)"
              @dragleave="dragOverFieldName === `group:${node.groupId}` && (dragOverFieldName = null)"
            >
              <label class="field-select" :title="isGroupSelected(node) ? 'Limpar seleção do grupo' : 'Selecionar grupo'">
                <input
                  type="checkbox"
                  :checked="isGroupSelected(node)"
                  :aria-label="`Selecionar grupo ${node.label}`"
                  @change="setGroupSelected(node, ($event.target as HTMLInputElement).checked)"
                >
              </label>
              <button type="button" class="field-group-toggle" :aria-expanded="!isGroupCollapsed(node.groupId)" :aria-label="`${isGroupCollapsed(node.groupId) ? 'Expandir' : 'Recolher'} ${node.label}`" @click="toggleGroup(node.groupId)">
                {{ isGroupCollapsed(node.groupId) ? '+' : '-' }}
              </button>
              <button type="button" class="field-group-title" @click="toggleGroup(node.groupId)">
                <strong>{{ node.label }}</strong>
                <small>{{ groupSummary(node) }}</small>
              </button>
              <button type="button" class="edit-field" :aria-label="`Adicionar item em ${node.label}`" title="Adicionar item" @click="addGroupItem(node)">Adicionar item</button>
              <button type="button" class="edit-field" :aria-label="`Renomear ${node.label}`" title="Renomear grupo" @click="renameGroup(node)">Renomear</button>
              <button type="button" class="delete-field" :aria-label="node.groupType === 'radio' ? `Excluir ${node.label}` : `Desagrupar ${node.label}`" :title="node.groupType === 'radio' ? 'Excluir grupo' : 'Desagrupar'" @click="deleteGroup(node)">×</button>
            </div>
            <div
              v-show="!isGroupCollapsed(node.groupId)"
              class="field-group-children"
              :class="{ 'drag-over': dragOverFieldName === `group:${node.groupId}` }"
              @dragover="dragOverGroup($event, node)"
              @drop="dropFieldOnGroup($event, node)"
              @dragleave="dragOverFieldName === `group:${node.groupId}` && (dragOverFieldName = null)"
            >
              <div
                v-for="entry in node.fields"
                :key="entry.optionValue ? `${entry.field.name}:${entry.optionValue}` : entry.field.name"
                class="field-row field-row-child"
                :class="{ 'drag-over': dragOverFieldName === entry.field.name, dragging: draggedFieldName === entry.field.name, active: props.activeFieldName === entry.field.name }"
                @dragover="node.groupType === 'checkbox' && dragOverField($event, entry.field.name)"
                @drop="node.groupType === 'checkbox' && dropField($event, entry.field.name)"
              >
                <label class="field-select" title="Selecionar campo">
                  <input
                    type="checkbox"
                    :checked="selectedFieldNames.includes(entry.field.name)"
                    :aria-label="`Selecionar ${groupChildLabel(entry)}`"
                    @change="setFieldSelected(entry.field.name, ($event.target as HTMLInputElement).checked)"
                  >
                </label>
                <div class="field-order-controls" aria-label="Controles de ordenação">
                  <button
                    type="button"
                    class="move-field drag-handle"
                    :draggable="node.groupType === 'checkbox'"
                    :aria-label="node.groupType === 'checkbox' ? `Arrastar ${entry.field.label} para reordenar` : `Opção ${groupChildLabel(entry)}`"
                    :title="node.groupType === 'checkbox' ? 'Arraste para reordenar' : 'Opção radio'"
                    @dragstart="node.groupType === 'checkbox' && startFieldDrag($event, entry.index)"
                    @dragend="endFieldDrag"
                  >⠿</button>
                  <button type="button" class="move-field" :disabled="node.groupType !== 'checkbox' || entry.index === 0" :aria-label="`Mover ${groupChildLabel(entry)} para cima`" title="Mover para cima" @click="reorderFieldOrSelection(entry.index, 'up')">↑</button>
                  <button type="button" class="move-field" :disabled="node.groupType !== 'checkbox' || entry.index === docStore.currentFields.length - 1" :aria-label="`Mover ${groupChildLabel(entry)} para baixo`" title="Mover para baixo" @click="reorderFieldOrSelection(entry.index, 'down')">↓</button>
                </div>
                <a href="#" class="field-link" @click.prevent="emit('scrollTo', entry.field.name)" @dblclick.prevent="emit('openValue', entry.index)">
                  <strong>{{ groupChildLabel(entry) }}</strong><br>
                  <code>{{ entry.field.type }}</code> · {{ node.groupType === 'radio' ? groupChildSummary(entry) : fieldSummary(entry.field) }}
                </a>
                <button type="button" class="edit-field" :aria-label="`Editar ${groupChildLabel(entry)}`" title="Editar campo" @click="editField(entry.index)">Editar</button>
                <button v-if="node.groupType === 'checkbox'" type="button" class="ungroup-field" :aria-label="`Remover ${entry.field.label} do grupo`" title="Remover do grupo" @click="removeFieldFromGroup(entry.field)">Remover</button>
                <button v-else type="button" class="ungroup-field" :aria-label="`Editar opções de ${node.label}`" title="Editar opções" @click="editField(entry.index)">Opções</button>
                <button type="button" class="delete-field" :aria-label="`Excluir ${groupChildLabel(entry)}`" title="Excluir campo" @click="deleteGroupChild(node, entry)">×</button>
              </div>
            </div>
          </div>
          <div
            v-else
            :ref="(element) => setFieldRowRef(node.field.name, element)"
            class="field-row"
            :class="{ 'drag-over': dragOverFieldName === node.field.name, dragging: draggedFieldName === node.field.name, active: props.activeFieldName === node.field.name }"
            @dragover="dragOverField($event, node.field.name)"
            @drop="dropField($event, node.field.name)"
          >
            <label class="field-select" :title="node.field.type === 'checkbox' || node.field.type === 'radio' ? 'Selecionar campo' : 'Apenas campos checkbox ou radio podem ser selecionados para conversão'">
              <input
                type="checkbox"
                :checked="selectedFieldNames.includes(node.field.name)"
                :disabled="node.field.type !== 'checkbox' && node.field.type !== 'radio'"
                :aria-label="`Selecionar ${node.field.label}`"
                @change="setFieldSelected(node.field.name, ($event.target as HTMLInputElement).checked)"
              >
            </label>
            <div class="field-order-controls" aria-label="Controles de ordenação">
              <button
                type="button"
                class="move-field drag-handle"
                draggable="true"
                :aria-label="`Arrastar ${node.field.label} para reordenar`"
                title="Arraste para reordenar"
                @dragstart="startFieldDrag($event, node.index)"
                @dragend="endFieldDrag"
              >⠿</button>
              <button type="button" class="move-field" :disabled="node.index === 0" :aria-label="`Mover ${node.field.label} para cima`" title="Mover para cima" @click="reorderFieldOrSelection(node.index, 'up')">↑</button>
              <button type="button" class="move-field" :disabled="node.index === docStore.currentFields.length - 1" :aria-label="`Mover ${node.field.label} para baixo`" title="Mover para baixo" @click="reorderFieldOrSelection(node.index, 'down')">↓</button>
            </div>
            <a href="#" class="field-link" @click.prevent="emit('scrollTo', node.field.name)" @dblclick.prevent="emit('openValue', node.index)">
              <strong>{{ node.field.label }}</strong><br>
              <code>{{ node.field.type }}</code> · {{ fieldSummary(node.field) }}
            </a>
            <button type="button" class="edit-field" :aria-label="`Editar ${node.field.label}`" title="Editar campo" @click="editField(node.index)">Editar</button>
            <button type="button" class="delete-field" :aria-label="`Excluir ${node.field.label}`" title="Excluir campo" @click="deleteField(node.index)">×</button>
          </div>
        </template>
      </template>
      <template v-else>Nenhum campo encontrado.</template>
      </div>
      <h3 class="section-title">Tabelas - rede neural</h3>
      <div id="neural-tables">
        <template v-if="docStore.neuralTables.length">
          <a v-for="table in docStore.neuralTables" :key="table.page" href="#" class="field-link" @click.prevent="emit('scrollTo', `page-${table.page}`)">
            <strong>Pagina {{ table.page }}</strong><br>
            <span class="confidence">{{ Math.round(table.confidence * 100) }}% de confianca</span><br>
            <small>{{ table.row_count || 0 }} linhas × {{ table.column_count || 0 }} colunas</small>
          </a>
        </template>
        <template v-else>Nenhuma tabela encontrada pela rede.</template>
      </div>
    </div>
  </aside>
</template>
