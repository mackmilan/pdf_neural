<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useDocumentStore } from '../stores/document'
import { useFieldEditorStore } from '../stores/fieldEditor'

const docStore = useDocumentStore()
const fieldEditor = useFieldEditorStore()
const labelRef = ref<HTMLInputElement | null>(null)

const show = computed(() => fieldEditor.editingFieldIndex !== null)
const isNumber = computed(() => fieldEditor.form.type === 'number')
const isRadio = computed(() => fieldEditor.form.type === 'radio')

watch(show, (visible) => {
  if (visible) nextTick(() => labelRef.value?.focus())
})

function close() {
  fieldEditor.stop()
}

function onTypeChange() {
  if (fieldEditor.form.type !== 'number') {
    fieldEditor.form.min = ''
    fieldEditor.form.max = ''
  }
}

function apply() {
  if (!fieldEditor.applyEditingField()) return
  fieldEditor.stop()
  docStore.status = 'Campo editado. Clique em Salvar alterações.'
}
</script>

<template>
  <div class="modal-backdrop" :class="{ show }" :aria-hidden="!show" @click.self="close">
    <section v-if="show" class="modal" role="dialog" aria-modal="true">
      <h3>Editar campo</h3>
      <p>{{ fieldEditor.hint }}</p>
      <form class="field-form" @submit.prevent="apply">
        <label>
          <span>Nome do campo</span>
          <input ref="labelRef" v-model="fieldEditor.form.label" maxlength="160" aria-label="Nome do campo">
        </label>
        <label>
          <span>Tipo do campo</span>
          <select v-model="fieldEditor.form.type" aria-label="Tipo do campo" @change="onTypeChange">
            <option value="text">Texto</option><option value="date">Data</option>
            <option value="time">Horário</option><option value="email">E-mail</option>
            <option value="tel">Telefone</option><option value="number">Número</option>
            <option value="checkbox">Checkbox</option><option value="radio">Grupo de opções (radio)</option><option value="textarea">Área de texto</option>
          </select>
        </label>
        <label v-show="isRadio">
          <span>Opções (uma por linha)</span>
          <textarea v-model="fieldEditor.form.options" rows="5" maxlength="16000" aria-label="Opções do campo radio" :disabled="!isRadio"></textarea>
        </label>
        <label>
          <span>Máscara (opcional)</span>
          <input v-model="fieldEditor.form.mask" maxlength="80" placeholder="ex.: (00) 00000-0000" aria-label="Máscara do campo">
        </label>
        <label>
          <span>Alinhamento do texto</span>
          <select v-model="fieldEditor.form.align" aria-label="Alinhamento do texto" @change="fieldEditor.onAlignChange">
            <option value="left">Alinhado à esquerda</option>
            <option value="center">Centralizado</option>
            <option value="justify">Justificado</option>
            <option value="right">Alinhado à direita</option>
          </select>
        </label>
        <label class="checkbox-row">
          <input v-model="fieldEditor.form.required" type="checkbox"> Campo obrigatório
        </label>
        <div class="number-rules" v-show="isNumber">
          <input v-model="fieldEditor.form.min" type="number" step="any" placeholder="Valor mínimo" aria-label="Valor mínimo" :disabled="!isNumber">
          <input v-model="fieldEditor.form.max" type="number" step="any" placeholder="Valor máximo" aria-label="Valor máximo" :disabled="!isNumber">
        </div>
        <span class="mask-hint">0 = número, A = letra, * = letra ou número. Os demais caracteres são fixos.</span>
        <div class="modal-actions">
          <button type="button" class="button-secondary" @click="close">Cancelar</button>
          <button type="submit">Aplicar edição</button>
        </div>
      </form>
    </section>
  </div>
</template>
