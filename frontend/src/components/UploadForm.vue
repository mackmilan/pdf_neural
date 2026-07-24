<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'
import UiIcon from './UiIcon.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (event: 'close'): void }>()

const context = useContextStore()
const doc = useDocumentStore()
const fileInput = ref<HTMLInputElement | null>(null)
const fileName = ref('')
const url = ref('')
const submitting = ref(false)
const useOcr = ref(true)
const detectFields = ref(true)

function onFileChange() {
  fileName.value = fileInput.value?.files?.[0]?.name || ''
  if (fileInput.value?.files?.length) url.value = ''
}

function onUrlInput() {
  if (url.value && fileInput.value) fileInput.value.value = ''
}

function close() {
  emit('close')
}

async function submit() {
  if (!fileInput.value?.files?.length && !url.value.trim()) {
    doc.status = 'Escolha um PDF ou informe uma URL'
    return
  }
  submitting.value = true
  doc.status = url.value ? 'Baixando, convertendo e analisando…' : 'Convertendo e analisando com a rede neural…'
  try {
    if (!context.tenantId) throw new Error('Selecione um tenant antes de converter.')
    const formData = new FormData()
    if (fileInput.value?.files?.[0]) formData.append('pdf', fileInput.value.files[0])
    if (url.value.trim()) formData.append('url', url.value.trim())
    formData.append('single_submission_per_user', 'false')
    formData.append('allow_document_page_submission', 'false')
    formData.append('use_ocr', String(useOcr.value))
    formData.append('detect_fields', String(detectFields.value))
    await doc.uploadDocument(formData)
    close()
  } catch (error) {
    doc.status = (error as Error).message
  } finally {
    submitting.value = false
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

watch(
  () => props.open,
  (visible) => {
    if (visible) {
      document.addEventListener('keydown', onKeydown)
      nextTick(() => fileInput.value?.focus())
    } else {
      document.removeEventListener('keydown', onKeydown)
    }
  },
)

onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="modal-backdrop" :class="{ show: open }" :aria-hidden="!open" @click.self="close">
    <section v-if="open" class="modal upload-modal" role="dialog" aria-modal="true" aria-label="Novo documento">
      <h3><UiIcon name="plus" />Novo documento</h3>
      <form @submit.prevent="submit">
        <label class="drop">
          <input ref="fileInput" type="file" accept="application/pdf" @change="onFileChange">
          <UiIcon name="upload" />
          <strong>{{ fileName || 'Escolha ou arraste um PDF' }}</strong>
          <br><small>Maximo de 30 MB</small>
        </label>
        <label class="url-field">URL do PDF
          <input class="url-input" v-model="url" type="url" inputmode="url" placeholder="https://exemplo.com/documento.pdf" aria-label="URL do arquivo PDF" @input="onUrlInput">
        </label>
        <div class="upload-flags">
          <label class="upload-flag">
            <input v-model="useOcr" type="checkbox">
            Utilizar OCR
          </label>
          <label class="upload-flag">
            <input v-model="detectFields" type="checkbox">
            Detectar campos para preenchimento
          </label>
        </div>
        <div class="modal-actions">
          <button type="button" class="button-secondary" @click="close">Cancelar</button>
          <button type="submit" class="button-with-icon" :disabled="submitting">
            <UiIcon name="wand" />
            Converter documento
          </button>
        </div>
      </form>
    </section>
  </div>
</template>
