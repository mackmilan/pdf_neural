<script setup lang="ts">
import { computed, ref } from 'vue'
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

const docStore = useDocumentStore()
const fieldEditor = useFieldEditorStore()
const modals = useModalsStore()

const emit = defineEmits<{ scrollTo: [string]; openValue: [number] }>()

const isNumber = computed(() => fieldEditor.form.type === 'number')
const isRadio = computed(() => fieldEditor.form.type === 'radio')
const draggedFieldName = ref<string | null>(null)
const dragOverFieldName = ref<string | null>(null)
const selectedFieldNames = ref<string[]>([])
const checkboxFields = computed(() => docStore.currentFields.filter((field) => field.type === 'checkbox'))
const selectedCheckboxFields = computed(() => {
  const selected = new Set(selectedFieldNames.value)
  return docStore.currentFields.filter((field) => field.type === 'checkbox' && selected.has(field.name))
})
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
const radioDrawingHint = computed(() => {
  if (!isRadio.value) return fieldEditor.hint
  const options = fieldEditor.form.options.split(/\r?\n/).map((option) => option.trim()).filter(Boolean)
  const index = fieldEditor.pendingRadioBoxes?.length || 0
  return options[index]
    ? `Desenhe a área da opção “${options[index]}” (${index + 1}/${options.length}).`
    : 'Informe as opções antes de desenhar as áreas.'
})

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
    <h3>Campos detectados</h3>
    <div class="field-toolbar">
      <button type="button" @click="addField">+ Adicionar campo</button>
      <button type="button" @click="saveFields">Salvar alterações</button>
      <button type="button" class="button-secondary" :disabled="!docStore.fieldsChanged" @click="discardFields">Descartar alterações</button>
      <button type="button" class="button-secondary" :disabled="!checkboxFields.length || allCheckboxesSelected" @click="selectAllCheckboxFields">Selecionar checkboxes</button>
      <button type="button" class="button-secondary" :disabled="!selectedFieldNames.length" @click="clearFieldSelection">Limpar seleção</button>
      <button type="button" class="button-secondary" :disabled="!canMoveSelectedUp" @click="moveSelectedFields('up')">Mover seleção ↑</button>
      <button type="button" class="button-secondary" :disabled="!canMoveSelectedDown" @click="moveSelectedFields('down')">Mover seleção ↓</button>
      <button type="button" :disabled="selectedCheckboxFields.length < 2" @click="convertSelectedCheckboxesToRadio">Converter checkboxes em radio</button>
      <button type="button" :disabled="!selectedRadioFields.length" @click="convertSelectedRadiosToCheckboxes">Converter radio em checkboxes</button>
    </div>
    <small style="display:block;color:#aab8d4;margin:-4px 0 12px">Dê duplo clique em um campo para preenchê-lo. Use o marcador ou as setas para reordenar a lista. Arraste campos na página para mover; as linhas-guia ajudam no alinhamento. Use as alças azuis para redimensionar.</small>
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
    <div id="fields">
      <template v-if="docStore.currentFields.length">
        <div
          v-for="(field, index) in docStore.currentFields"
          :key="field.name"
          class="field-row"
          :class="{ 'drag-over': dragOverFieldName === field.name, dragging: draggedFieldName === field.name }"
          @dragover="dragOverField($event, field.name)"
          @drop="dropField($event, field.name)"
        >
          <label class="field-select" :title="field.type === 'checkbox' || field.type === 'radio' ? 'Selecionar campo' : 'Apenas campos checkbox ou radio podem ser selecionados para conversão'">
            <input
              type="checkbox"
              :checked="selectedFieldNames.includes(field.name)"
              :disabled="field.type !== 'checkbox' && field.type !== 'radio'"
              :aria-label="`Selecionar ${field.label}`"
              @change="setFieldSelected(field.name, ($event.target as HTMLInputElement).checked)"
            >
          </label>
          <div class="field-order-controls" aria-label="Controles de ordenação">
            <button
              type="button"
              class="move-field drag-handle"
              draggable="true"
              :aria-label="`Arrastar ${field.label} para reordenar`"
              title="Arraste para reordenar"
              @dragstart="startFieldDrag($event, index)"
              @dragend="endFieldDrag"
            >⠿</button>
            <button type="button" class="move-field" :disabled="index === 0" :aria-label="`Mover ${field.label} para cima`" title="Mover para cima" @click="reorderFieldOrSelection(index, 'up')">↑</button>
            <button type="button" class="move-field" :disabled="index === docStore.currentFields.length - 1" :aria-label="`Mover ${field.label} para baixo`" title="Mover para baixo" @click="reorderFieldOrSelection(index, 'down')">↓</button>
          </div>
          <a href="#" class="field-link" @click.prevent="emit('scrollTo', field.name)" @dblclick.prevent="emit('openValue', index)">
            <strong>{{ field.label }}</strong><br>
            <code>{{ field.type }}</code> · {{ fieldSummary(field) }}
          </a>
          <button type="button" class="edit-field" :aria-label="`Editar ${field.label}`" title="Editar campo" @click="editField(index)">Editar</button>
          <button type="button" class="delete-field" :aria-label="`Excluir ${field.label}`" title="Excluir campo" @click="deleteField(index)">×</button>
        </div>
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
  </aside>
</template>
