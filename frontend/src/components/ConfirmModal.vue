<script setup lang="ts">
import { useModalsStore } from '../stores/modals'

const modals = useModalsStore()
</script>

<template>
  <div class="modal-backdrop" :class="{ show: modals.confirm }" :aria-hidden="!modals.confirm" @click.self="modals.resolveConfirm(false)">
    <section v-if="modals.confirm" class="modal" role="alertdialog" aria-modal="true">
      <h3>{{ modals.confirm.title }}</h3>
      <p>{{ modals.confirm.message }}</p>
      <div class="modal-actions">
        <button type="button" class="button-secondary" @click="modals.resolveConfirm(false)">Cancelar</button>
        <button type="button" :class="modals.confirm.danger ? 'button-danger' : ''" @click="modals.resolveConfirm(true)">
          {{ modals.confirm.confirmLabel }}
        </button>
      </div>
    </section>
  </div>
</template>
