import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './style.css'
import App from './App.vue'
import { applyTheme, resolveInitialTheme, useThemeStore } from './stores/theme'

// Antes de montar para a página nunca aparecer com o tema errado.
applyTheme(resolveInitialTheme())

const pinia = createPinia()

window.matchMedia?.('(prefers-color-scheme: light)').addEventListener('change', (event) => {
  useThemeStore(pinia).syncWithSystem(event.matches ? 'light' : 'dark')
})

createApp(App).use(pinia).mount('#app')
