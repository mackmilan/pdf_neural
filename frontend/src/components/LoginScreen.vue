<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ documentId?: string }>()

const auth = useAuthStore()
const documentTitle = ref('')
const tenantName = ref('')
const groupName = ref('')

const title = computed(() => documentTitle.value || 'PDF Neural')
const subtitle = computed(() => {
  if (!props.documentId) return 'Entre com sua conta para acessar documentos, conversões e histórico.'
  return [tenantName.value, groupName.value].filter(Boolean).join(' · ') || 'Documento disponível para preenchimento.'
})

async function loadDocumentTitle() {
  documentTitle.value = ''
  tenantName.value = ''
  groupName.value = ''
  if (!props.documentId) return
  try {
    const response = await fetch(`/api/public/viewer/documents/${encodeURIComponent(props.documentId)}`)
    const data = await response.json().catch(() => ({}))
    if (response.ok && typeof data.document_name === 'string') {
      documentTitle.value = data.document_name.trim()
    }
    if (response.ok && typeof data.tenant_name === 'string') {
      tenantName.value = data.tenant_name.trim()
    }
    if (response.ok && typeof data.group_name === 'string') {
      groupName.value = data.group_name.trim()
    }
  } catch {
    documentTitle.value = ''
    tenantName.value = ''
    groupName.value = ''
  }
}

function loginWithKeycloak() {
  auth.beginLogin().catch((error) => auth.showLogin(error))
}

onMounted(loadDocumentTitle)
watch(() => props.documentId, loadDocumentTitle)
</script>

<template>
  <section class="login-screen" id="login-screen">
    <div class="card login-card">
      <h1>{{ title }}</h1>
      <p class="lead">
        {{ subtitle }}
      </p>
      <button type="button" :disabled="!auth.config" @click="loginWithKeycloak">Entrar com Keycloak</button>
      <p class="status">{{ auth.initialized ? auth.loginError || 'Faça login para continuar.' : 'Verificando sessão…' }}</p>
    </div>
  </section>
</template>
