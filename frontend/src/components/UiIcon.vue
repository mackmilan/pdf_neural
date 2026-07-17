<script setup lang="ts">
type IconName =
  | 'archive'
  | 'check'
  | 'edit'
  | 'external-link'
  | 'maximize'
  | 'more-horizontal'
  | 'refresh'
  | 'save'
  | 'trash'

defineProps<{
  name: IconName
}>()
</script>

<template>
  <svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <g v-if="name === 'archive'">
      <path d="M21 8v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8" />
      <path d="M1 3h22v5H1z" />
      <path d="M10 12h4" />
    </g>
    <g v-else-if="name === 'check'">
      <path d="m20 6-11 11-5-5" />
    </g>
    <g v-else-if="name === 'edit'">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </g>
    <g v-else-if="name === 'external-link'">
      <path d="M15 3h6v6" />
      <path d="M10 14 21 3" />
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </g>
    <g v-else-if="name === 'maximize'">
      <path d="M8 3H5a2 2 0 0 0-2 2v3" />
      <path d="M21 8V5a2 2 0 0 0-2-2h-3" />
      <path d="M3 16v3a2 2 0 0 0 2 2h3" />
      <path d="M16 21h3a2 2 0 0 0 2-2v-3" />
    </g>
    <g v-else-if="name === 'more-horizontal'">
      <path d="M12 12h.01" />
      <path d="M19 12h.01" />
      <path d="M5 12h.01" />
    </g>
    <g v-else-if="name === 'refresh'">
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
      <path d="M3 21v-5h5" />
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </g>
    <g v-else-if="name === 'save'">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" />
      <path d="M17 21v-8H7v8" />
      <path d="M7 3v5h8" />
    </g>
    <g v-else-if="name === 'trash'">
      <path d="M3 6h18" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </g>
  </svg>
</template>
