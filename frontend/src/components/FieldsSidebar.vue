<script setup lang="ts">
import { computed } from 'vue'
import { useDocumentStore, fieldTextAlign, fieldValidationSummary } from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'
import { useModalsStore } from '../stores/modals'
import type { FieldAlign, FieldType } from '../types'

const docStore = useDocumentStore()
const fieldEditor = useFieldEditorStore()
const modals = useModalsStore()

const emit = defineEmits<{ scrollTo: [string]; openValue: [number] }>()

const isNumber = computed(() => fieldEditor.form.type === 'number')

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
  docStore.currentFields.splice(index, 1)
  docStore.status = 'Campo excluído. Clique em Salvar alterações.'
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
    </div>
    <small style="display:block;color:#aab8d4;margin:-4px 0 12px">Dê duplo clique em um campo para preenchê-lo. Arraste campos para mover; as linhas-guia ajudam no alinhamento. Use as alças azuis para redimensionar.</small>
    <div class="editor" :class="{ show: fieldEditor.addingField }">
      <input v-model="fieldEditor.form.label" maxlength="160" placeholder="Nome do campo" aria-label="Nome do campo">
      <select v-model="fieldEditor.form.type" aria-label="Tipo do campo" @change="onTypeChange">
        <option value="text">Texto</option><option value="date">Data</option>
        <option value="time">Horário</option><option value="email">E-mail</option>
        <option value="tel">Telefone</option><option value="number">Número</option>
        <option value="checkbox">Checkbox</option><option value="textarea">Área de texto</option>
      </select>
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
      <small>{{ fieldEditor.hint }}</small>
      <button type="button" @click="cancelEdit">Cancelar</button>
    </div>
    <div id="fields">
      <template v-if="docStore.currentFields.length">
        <div v-for="(field, index) in docStore.currentFields" :key="field.name" class="field-row">
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
