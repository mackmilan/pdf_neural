<script setup lang="ts">
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

function login() {
  auth.beginLogin().catch((error) => auth.showLogin(error))
}
</script>

<template>
  <section class="login-screen" id="login-screen">
    <div class="card login-card">
      <h1>PDF Neural</h1>
      <p class="lead">Entre com sua conta para acessar documentos, conversões e histórico.</p>
      <button type="button" :disabled="!auth.config" @click="login">Entrar com Keycloak</button>
      <p class="status">{{ auth.initialized ? auth.loginError || 'Faça login para continuar.' : 'Verificando sessão…' }}</p>
    </div>
  </section>
</template>
