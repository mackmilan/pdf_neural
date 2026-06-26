<script setup lang="ts">
import { ref } from 'vue'
import { useContextStore } from '../stores/context'
import { useDocumentStore } from '../stores/document'

const context = useContextStore()
const doc = useDocumentStore()
const fileInput = ref<HTMLInputElement | null>(null)
const fileName = ref('')
const url = ref('')
const submitting = ref(false)

function onFileChange() {
  fileName.value = fileInput.value?.files?.[0]?.name || ''
  if (fileInput.value?.files?.length) url.value = ''
}

function onUrlInput() {
  if (url.value && fileInput.value) fileInput.value.value = ''
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
    await doc.uploadDocument(formData)
  } catch (error) {
    doc.status = (error as Error).message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="card">
    <form @submit.prevent="submit">
      <label class="drop">
        <input ref="fileInput" type="file" accept="application/pdf" @change="onFileChange">
        <strong>{{ fileName || 'Escolha ou arraste um PDF' }}</strong>
        <br><small>Maximo de 30 MB</small>
      </label>
      <div class="separator">ou use uma URL</div>
      <input class="url-input" v-model="url" type="url" inputmode="url" placeholder="https://exemplo.com/documento.pdf" aria-label="URL do arquivo PDF" @input="onUrlInput">
      <div class="actions">
        <button type="submit" :disabled="submitting">Converter documento</button>
        <span class="status">{{ doc.status }}</span>
      </div>
    </form>
  </section>
</template>
