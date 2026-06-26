<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from './stores/auth'
import LoginScreen from './components/LoginScreen.vue'
import AppShell from './components/AppShell.vue'
import ConfirmModal from './components/ConfirmModal.vue'
import TextInputModal from './components/TextInputModal.vue'

const auth = useAuthStore()

onMounted(() => {
  auth.initialize()
})
</script>

<template>
  <LoginScreen v-if="!auth.initialized || !auth.isAuthenticated" />
  <AppShell v-else />
  <ConfirmModal />
  <TextInputModal />
</template>
