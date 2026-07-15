<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'

defineProps<{ passwordLogin?: boolean }>()

const auth = useAuthStore()
const email = ref('')
const password = ref('')
const submitting = ref(false)

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
</script>

<template>
  <section class="login-screen" id="login-screen">
    <div class="card login-card">
      <h1>PDF Neural</h1>
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
      <p class="status">{{ auth.initialized ? auth.loginError || 'Faça login para continuar.' : 'Verificando sessão…' }}</p>
    </div>
  </section>
</template>
