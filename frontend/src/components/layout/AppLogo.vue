<script setup lang="ts">
import logoColor from '@/assets/brand/logo-color.png'
import logoWhite from '@/assets/brand/logo-white.png'
import logoMark from '@/assets/brand/logo-mark.png'

withDefaults(defineProps<{ size?: number; collapsed?: boolean }>(), {
  size: 32,
  collapsed: false,
})

const appTitle = import.meta.env.VITE_APP_TITLE ?? '企业知识库'
</script>

<template>
  <div class="app-logo" :class="{ 'app-logo--collapsed': collapsed }" :title="appTitle">
    <img
      v-if="collapsed"
      class="app-logo__mark"
      :src="logoMark"
      :width="size"
      :height="size"
      :alt="appTitle"
    />
    <template v-else>
      <img class="app-logo__full app-logo__full--light" :src="logoColor" :alt="appTitle" />
      <img class="app-logo__full app-logo__full--dark" :src="logoWhite" alt="" aria-hidden="true" />
      <span class="app-logo__divider" />
      <span class="app-logo__product">知识库</span>
    </template>
  </div>
</template>

<style scoped>
.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.app-logo__mark {
  flex: none;
  object-fit: contain;
}
.app-logo__full {
  flex: none;
  height: 22px;
  width: auto;
}
.app-logo__full--dark {
  display: none;
}
:global(html.dark .app-logo__full--light) {
  display: none;
}
:global(html.dark .app-logo__full--dark) {
  display: block;
}
.app-logo__divider {
  flex: none;
  width: 1px;
  height: 16px;
  background: var(--ekb-border);
}
.app-logo__product {
  font-size: 15px;
  font-weight: 600;
  color: var(--ekb-text-1);
  letter-spacing: 1px;
  white-space: nowrap;
}
</style>
