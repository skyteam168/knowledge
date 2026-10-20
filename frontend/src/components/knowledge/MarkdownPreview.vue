<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const NO_CITATIONS = new Set<number>()

const props = defineProps<{
  content: string
}>()

const html = computed(() => renderMarkdown(props.content, { citations: NO_CITATIONS }))
</script>

<template>
  <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
  <div class="markdown-preview" data-test="markdown-preview" v-html="html" />
</template>

<style scoped>
.markdown-preview {
  overflow: auto;
  padding: 14px 18px;
  line-height: 1.7;
  word-break: break-word;
}
.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3) {
  margin: 1.1em 0 0.5em;
  line-height: 1.35;
}
.markdown-preview :deep(h1) {
  font-size: 1.45em;
}
.markdown-preview :deep(h2) {
  font-size: 1.25em;
}
.markdown-preview :deep(h3) {
  font-size: 1.1em;
}
.markdown-preview :deep(p),
.markdown-preview :deep(ul),
.markdown-preview :deep(ol) {
  margin: 0.55em 0;
}
.markdown-preview :deep(pre) {
  overflow: auto;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.markdown-preview :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.92em;
}
.markdown-preview :deep(p code),
.markdown-preview :deep(li code) {
  padding: 0.1em 0.35em;
  border-radius: 4px;
  background: var(--el-fill-color);
}
.markdown-preview :deep(blockquote) {
  margin: 0.7em 0;
  padding: 0.2em 0 0.2em 0.9em;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
}
.markdown-preview :deep(table) {
  border-collapse: collapse;
  margin: 8px 0 12px;
  width: 100%;
}
.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 6px 12px;
  text-align: left;
}
.markdown-preview :deep(th) {
  background: var(--el-fill-color-light);
}
.markdown-preview :deep(img) {
  max-width: 100%;
}
</style>
