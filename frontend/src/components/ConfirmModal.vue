<script setup lang="ts">
import { useModalsStore } from '../stores/modals'

const modals = useModalsStore()
</script>

<template>
  <div
    class="modal-backdrop"
    :class="{ show: modals.confirm || modals.alert }"
    :aria-hidden="!(modals.confirm || modals.alert)"
    @click.self="modals.confirm ? modals.resolveConfirm(false) : modals.resolveAlert()"
  >
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
    <section v-else-if="modals.alert" class="modal" role="alertdialog" aria-modal="true">
      <h3>{{ modals.alert.title }}</h3>
      <p>{{ modals.alert.message }}</p>
      <div class="modal-actions">
        <button type="button" @click="modals.resolveAlert()">{{ modals.alert.confirmLabel }}</button>
      </div>
    </section>
  </div>
</template>
