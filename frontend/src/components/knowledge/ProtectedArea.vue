<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'

/**
 * Wraps protected content: a tiled watermark of the viewer (name, account · employee no., time)
 * and, with copy protection, no selection / copy / context menu / drag / print. Page images are
 * also watermarked server-side; this layer covers text and screenshots of the page itself.
 */
const props = defineProps<{ watermark?: boolean; copyProtect?: boolean }>()
const auth = useAuthStore()
const { t } = useI18n()

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function escapeXml(text: string): string {
  return text.replace(/[<>&"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

const lines = computed(() => {
  const me = auth.profile
  const now = new Date()
  const offset = -now.getTimezoneOffset() / 60
  const zone = `UTC${offset >= 0 ? '+' : ''}${offset}`
  const time = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())} ${zone}`
  const detail = [me?.username, me?.employee_no].filter(Boolean).join(' · ')
  return [auth.displayName, detail, time].filter(Boolean)
})

const background = computed(() => {
  const text = lines.value
    .map((line, i) => `<tspan x="0" dy="${i ? 22 : 0}">${escapeXml(line)}</tspan>`)
    .join('')
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200">` +
    `<text transform="translate(40 120) rotate(-30)" fill="rgba(128,128,128,0.18)" ` +
    `font-size="15" font-family="sans-serif">${text}</text></svg>`
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`
})

function block(event: Event): void {
  if (!props.copyProtect) return
  event.preventDefault()
  if (event.type === 'copy' || event.type === 'cut')
    ElMessage.warning(t('knowledge.protect.copyBlocked'))
}
</script>

<template>
  <div
    class="protected"
    :class="{ 'protected--nocopy': copyProtect }"
    data-test="protected-area"
    @copy="block"
    @cut="block"
    @contextmenu="block"
    @dragstart="block"
  >
    <slot />
    <div
      v-if="watermark"
      class="protected__mark"
      data-test="watermark-layer"
      :data-watermark="lines.join(' / ')"
      :style="{ backgroundImage: background }"
      aria-hidden="true"
    />
  </div>
</template>

<style scoped>
.protected {
  position: relative;
}
.protected--nocopy {
  user-select: none;
  -webkit-user-select: none;
}
.protected__mark {
  position: absolute;
  inset: 0;
  z-index: 5;
  pointer-events: none;
  background-repeat: repeat;
}
@media print {
  .protected--nocopy {
    visibility: hidden;
  }
}
</style>
