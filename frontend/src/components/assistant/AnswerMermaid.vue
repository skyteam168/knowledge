<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTheme } from '@/composables/useTheme'

const props = defineProps<{
  source: string
}>()

const { t } = useI18n()
const svgHtml = ref('')
const error = ref('')
const el = ref<HTMLDivElement | null>(null)
const { isDark } = useTheme()
let renderId = 0

async function render(): Promise<void> {
  const id = ++renderId
  error.value = ''
  svgHtml.value = ''
  const src = props.source.trim()
  if (!src) return
  try {
    const mermaid = (await import('mermaid')).default
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: isDark.value ? 'dark' : 'default',
      fontFamily: 'inherit',
    })
    const { svg } = await mermaid.render(`mermaid-${id}-${Date.now()}`, src)
    if (id !== renderId) return
    svgHtml.value = svg
  } catch (e) {
    if (id !== renderId) return
    error.value = e instanceof Error ? e.message : t('assistant.mermaidFailed')
  }
}

watch(
  () => [props.source, isDark.value] as const,
  () => void render(),
  { immediate: true },
)

onBeforeUnmount(() => {
  renderId += 1
})
</script>

<template>
  <div class="answer-mermaid" data-test="answer-mermaid">
    <!-- eslint-disable-next-line vue/no-v-html -- mermaid SVG output, securityLevel: strict -->
    <div v-if="svgHtml" ref="el" class="answer-mermaid__svg" v-html="svgHtml" />
    <pre v-else-if="error" class="answer-mermaid__error">{{ error }}</pre>
    <pre v-else class="answer-mermaid__pending">{{ source }}</pre>
  </div>
</template>

<style scoped>
.answer-mermaid {
  margin: 12px 0;
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--ekb-code-border);
  border-radius: 10px;
  background: var(--ekb-bg-card, var(--el-bg-color));
}
.answer-mermaid__svg :deep(svg) {
  max-width: 100%;
  height: auto;
}
.answer-mermaid__error {
  margin: 0;
  color: var(--el-color-danger);
  white-space: pre-wrap;
  font-size: 13px;
}
.answer-mermaid__pending {
  margin: 0;
  color: var(--el-text-color-secondary);
  white-space: pre-wrap;
  font-size: 13px;
}
</style>
