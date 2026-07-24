import { defineStore } from 'pinia'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'pdf-neural-theme'

function storedTheme(): Theme | null {
  const saved = localStorage.getItem(STORAGE_KEY)
  return saved === 'dark' || saved === 'light' ? saved : null
}

function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

/** Tema inicial: escolha salva do usuário ou, sem escolha, a preferência do sistema. */
export function resolveInitialTheme(): Theme {
  return storedTheme() || systemTheme()
}

/** Aplica o tema no <html>; os tokens de cor em style.css derivam de data-theme. */
export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    theme: resolveInitialTheme(),
    // Sem escolha salva o tema acompanha o sistema até o usuário decidir.
    followsSystem: !storedTheme(),
  }),
  actions: {
    setTheme(theme: Theme) {
      this.theme = theme
      this.followsSystem = false
      localStorage.setItem(STORAGE_KEY, theme)
      applyTheme(theme)
    },
    toggle() {
      this.setTheme(this.theme === 'dark' ? 'light' : 'dark')
    },
    syncWithSystem(theme: Theme) {
      if (!this.followsSystem) return
      this.theme = theme
      applyTheme(theme)
    },
  },
})
