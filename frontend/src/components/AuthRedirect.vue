<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const status = computed(() => {
  if (auth.loginError) return auth.loginError
  if (auth.redirecting) return 'Redirecionando para o Keycloak…'
  return 'Verificando sessão…'
})

function retryLogin() {
  auth.requireLogin(undefined, true)
}
</script>

<template>
  <section class="login-screen" id="auth-redirect">
    <div class="card login-card">
      <h1>PDF Neural</h1>
      <p class="status">{{ status }}</p>
      <button v-if="auth.loginError" type="button" :disabled="!auth.config" @click="retryLogin">
        Tentar novamente
      </button>
    </div>
  </section>
</template>
