import { defineStore } from 'pinia'

export interface ConfirmOptions {
  title?: string
  message: string
  confirmLabel?: string
  danger?: boolean
}

export interface AlertOptions {
  title?: string
  message: string
  confirmLabel?: string
}

export interface TextInputOptions {
  title: string
  message?: string
  label?: string
  value?: string
  confirmLabel?: string
}

export const useModalsStore = defineStore('modals', {
  state: () => ({
    confirm: null as (ConfirmOptions & { resolve: (value: boolean) => void }) | null,
    alert: null as (AlertOptions & { resolve: () => void }) | null,
    textInput: null as (TextInputOptions & { resolve: (value: string | null) => void; error: string }) | null,
  }),
  actions: {
    showConfirm(options: ConfirmOptions): Promise<boolean> {
      if (this.confirm) this.confirm.resolve(false)
      return new Promise((resolve) => {
        this.confirm = { title: 'Confirmar ação', confirmLabel: 'Confirmar', danger: false, ...options, resolve }
      })
    },
    resolveConfirm(accepted: boolean) {
      this.confirm?.resolve(accepted)
      this.confirm = null
    },
    showAlert(options: AlertOptions): Promise<void> {
      if (this.alert) this.alert.resolve()
      return new Promise((resolve) => {
        this.alert = { title: 'Aviso', confirmLabel: 'OK', ...options, resolve }
      })
    },
    resolveAlert() {
      this.alert?.resolve()
      this.alert = null
    },
    showTextInput(options: TextInputOptions): Promise<string | null> {
      if (this.textInput) this.textInput.resolve(null)
      return new Promise((resolve) => {
        this.textInput = { label: 'Valor', value: '', confirmLabel: 'Confirmar', ...options, resolve, error: '' }
      })
    },
    submitTextInput(value: string) {
      const trimmed = value.trim()
      if (!trimmed) {
        if (this.textInput) this.textInput.error = 'Informe um nome para continuar.'
        return
      }
      this.textInput?.resolve(trimmed)
      this.textInput = null
    },
    cancelTextInput() {
      this.textInput?.resolve(null)
      this.textInput = null
    },
  },
})
