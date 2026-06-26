<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useModalsStore } from '../stores/modals'

const modals = useModalsStore()
const value = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

watch(
  () => modals.textInput,
  (next) => {
    if (next) {
      value.value = next.value || ''
      nextTick(() => {
        inputRef.value?.focus()
        inputRef.value?.select()
      })
    }
  },
)

function submit() {
  modals.submitTextInput(value.value)
}
</script>

<template>
  <div class="modal-backdrop" :class="{ show: modals.textInput }" :aria-hidden="!modals.textInput" @click.self="modals.cancelTextInput()">
    <section v-if="modals.textInput" class="modal" role="dialog" aria-modal="true">
      <h3>{{ modals.textInput.title }}</h3>
      <p>{{ modals.textInput.message }}</p>
      <form class="field-form" @submit.prevent="submit">
        <label>
          <span>{{ modals.textInput.label }}</span>
          <input ref="inputRef" v-model="value" maxlength="255">
        </label>
        <span class="status" aria-live="polite">{{ modals.textInput.error }}</span>
        <div class="modal-actions">
          <button type="button" class="button-secondary" @click="modals.cancelTextInput()">Cancelar</button>
          <button type="submit">{{ modals.textInput.confirmLabel }}</button>
        </div>
      </form>
    </section>
  </div>
</template>
