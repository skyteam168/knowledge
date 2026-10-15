<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Citation } from '@/api/types'
import { citationOf, codeOfCopyButton, renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
  citations: Citation[]
  streaming?: boolean
}>()

const emit = defineEmits<{ cite: [n: number] }>()

const byNumber = computed(() => new Map(props.citations.map((c) => [c.n, c])))

// While streaming, citations are not validated yet: render every marker as a link.
const html = computed(() =>
  renderMarkdown(props.content, {
    citations: props.streaming ? undefined : new Set(byNumber.value.keys()),
  }),
)

const hoverEl = ref<HTMLElement>()
const hovered = ref<Citation | null>(null)
// Grace period that lets the pointer travel from the marker into the popover.
const CLOSE_DELAY_MS = 200
let closeTimer: number | undefined

function cancelClose(): void {
  window.clearTimeout(closeTimer)
  closeTimer = undefined
}

function scheduleClose(): void {
  cancelClose()
  closeTimer = window.setTimeout(() => {
    hovered.value = null
  }, CLOSE_DELAY_MS)
}

onBeforeUnmount(cancelClose)

function onOver(event: MouseEvent): void {
  const hit = citationOf(event.target)
  if (!hit) return
  cancelClose()
  hoverEl.value = hit.el
  hovered.value = byNumber.value.get(hit.n) ?? null
}

function onOut(event: MouseEvent): void {
  if (citationOf(event.relatedTarget)?.el !== hoverEl.value) scheduleClose()
}

function openHovered(): void {
  const n = hovered.value?.n
  cancelClose()
  hovered.value = null
  if (n !== undefined) emit('cite', n)
}

async function copyCode(target: EventTarget | null): Promise<boolean> {
  const hit = codeOfCopyButton(target)
  if (!hit) return false
  try {
    await navigator.clipboard.writeText(hit.code)
    hit.el.textContent = '已复制'
    hit.el.classList.add('copied')
    window.setTimeout(() => {
      hit.el.textContent = '复制'
      hit.el.classList.remove('copied')
    }, 1500)
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
  return true
}

function onClick(event: Event): void {
  if (codeOfCopyButton(event.target)) {
    void copyCode(event.target)
    return
  }
  const hit = citationOf(event.target)
  if (!hit || !byNumber.value.has(hit.n)) return
  cancelClose()
  hovered.value = null
  emit('cite', hit.n)
}
</script>

<template>
  <!-- eslint-disable vue/no-v-html -- markdown-it runs with html: false -->
  <div
    class="markdown"
    :class="{ streaming }"
    @mouseover="onOver"
    @mouseout="onOut"
    @click="onClick"
    @keydown.enter="onClick"
    v-html="html"
  />
  <!-- eslint-enable vue/no-v-html -->
  <el-popover
    :visible="hovered !== null"
    :virtual-ref="hoverEl"
    virtual-triggering
    placement="top"
    :width="380"
  >
    <div
      v-if="hovered"
      class="cite-preview"
      data-test="cite-preview"
      @mouseenter="cancelClose"
      @mouseleave="scheduleClose"
    >
      <div class="cite-title">[{{ hovered.n }}] {{ hovered.title }}</div>
      <div v-if="hovered.heading_path.length" class="cite-path">
        {{ hovered.heading_path.join(' › ') }}
      </div>
      <div class="cite-quote">{{ hovered.quote }}</div>
      <button type="button" class="cite-hint" data-test="cite-open" @click="openHovered">
        点击查看原文
      </button>
    </div>
  </el-popover>
</template>

<style scoped>
.markdown {
  font-size: 15px;
  line-height: 1.8;
  color: var(--ekb-text-1);
  word-break: break-word;
}
.markdown :deep(p) {
  margin: 0 0 10px;
}
.markdown :deep(> :last-child) {
  margin-bottom: 0;
}
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3),
.markdown :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
  line-height: 1.5;
}
.markdown :deep(h1) {
  font-size: 20px;
}
.markdown :deep(h2) {
  font-size: 18px;
}
.markdown :deep(h3),
.markdown :deep(h4) {
  font-size: 16px;
}
.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 4px 0 10px;
  padding-left: 22px;
}
.markdown :deep(li) {
  margin: 2px 0;
}
.markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  color: var(--el-text-color-secondary);
  border-left: 3px solid var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  border-radius: 0 6px 6px 0;
}
.markdown :deep(a) {
  color: var(--el-color-primary);
}
.markdown :deep(:not(pre) > code) {
  padding: 1px 6px;
  color: var(--ekb-code-text);
  background: var(--ekb-bg-fill);
  border-radius: 4px;
}
.markdown :deep(code) {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}
.markdown :deep(.code-block) {
  margin: 10px 0;
  overflow: hidden;
  border: 1px solid var(--ekb-code-border);
  border-radius: 8px;
  background: var(--ekb-table-header);
}
.markdown :deep(.code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 4px 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--ekb-bg-fill-2);
}
.markdown :deep(.code-copy) {
  padding: 2px 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  background: transparent;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
}
.markdown :deep(.code-copy:hover) {
  background: var(--ekb-bg-hover);
}
.markdown :deep(.code-copy.copied) {
  color: var(--el-color-success);
}
.markdown :deep(pre) {
  margin: 0;
  padding: 12px 14px;
  overflow: auto;
  line-height: 1.6;
}
.markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow: auto;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 14px;
}
.markdown :deep(th) {
  background: var(--ekb-bg-fill);
  font-weight: 600;
}
.markdown :deep(th),
.markdown :deep(td) {
  padding: 6px 10px;
  border: 1px solid var(--ekb-code-border);
}
.markdown :deep(sup.cite) {
  display: inline-block;
  min-width: 16px;
  margin: 0 2px;
  padding: 0 4px;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
  color: var(--el-color-primary);
  font-weight: 600;
  background: var(--el-color-primary-light-9);
  border-radius: 4px;
  cursor: pointer;
  vertical-align: super;
}
.markdown :deep(sup.cite:hover) {
  color: #fff;
  background: var(--el-color-primary);
}
.markdown.streaming > :deep(:last-child)::after {
  content: '▍';
  margin-left: 2px;
  color: var(--el-color-primary);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    visibility: hidden;
  }
}
.cite-preview {
  /* Cover the popover padding so the pointer never leaves the hover area inside it. */
  margin: -12px;
  padding: 12px;
}
.cite-title {
  font-weight: 600;
}
.cite-path {
  margin-top: 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cite-quote {
  margin-top: 6px;
  line-height: 1.6;
  white-space: pre-wrap;
  max-height: 200px;
  overflow: auto;
}
.cite-hint {
  margin-top: 6px;
  padding: 0;
  font-size: 12px;
  color: var(--el-color-primary);
  background: none;
  border: 0;
  cursor: pointer;
}
.cite-hint:hover {
  text-decoration: underline;
}
</style>
