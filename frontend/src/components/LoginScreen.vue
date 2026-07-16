<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '../stores/auth'

const props = defineProps<{ passwordLogin?: boolean; documentId?: string }>()

const auth = useAuthStore()
const email = ref('')
const password = ref('')
const submitting = ref(false)
const documentTitle = ref('')

const title = computed(() => documentTitle.value || (props.documentId ? 'Documento' : 'PDF Neural'))

async function loadDocumentTitle() {
  documentTitle.value = ''
  if (!props.documentId) return
  try {
    const response = await fetch(`/api/public/viewer/documents/${encodeURIComponent(props.documentId)}`)
    const data = await response.json().catch(() => ({}))
    if (response.ok && typeof data.document_name === 'string') {
      documentTitle.value = data.document_name.trim()
    }
  } catch {
    documentTitle.value = ''
  }
}

async function login() {
  submitting.value = true
  try {
    await auth.loginWithPassword(email.value, password.value)
    password.value = ''
  } catch (error) {
    auth.showLogin(error as Error)
  } finally {
    submitting.value = false
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
        {{ passwordLogin ? 'Entre com seu e-mail e senha para visualizar o documento.' : 'Entre com sua conta para acessar documentos, conversões e histórico.' }}
      </p>
      <form v-if="passwordLogin" class="login-form" @submit.prevent="login">
        <label>
          E-mail
          <input v-model="email" type="email" autocomplete="username" required />
        </label>
        <label>
          Senha
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <button type="submit" :disabled="!auth.config || submitting">
          {{ submitting ? 'Entrando…' : 'Entrar' }}
        </button>
      </form>
      <button v-else type="button" :disabled="!auth.config" @click="loginWithKeycloak">Entrar com Keycloak</button>
      <button
        v-if="passwordLogin && auth.accountSetupRequired"
        type="button"
        class="button-secondary login-setup-button"
        :disabled="!auth.config"
        @click="loginWithKeycloak"
      >
        Concluir cadastro no Keycloak
      </button>
      <p class="status">{{ auth.initialized ? auth.loginError || 'Faça login para continuar.' : 'Verificando sessão…' }}</p>
    </div>
  </section>
</template>
