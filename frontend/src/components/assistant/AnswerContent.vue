<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElImageViewer, ElMessage } from 'element-plus'
import { getCitationSource } from '@/api/chat'
import type { Citation } from '@/api/types'
import AnswerChart from '@/components/assistant/AnswerChart.vue'
import AnswerMermaid from '@/components/assistant/AnswerMermaid.vue'
import AnswerTable from '@/components/assistant/AnswerTable.vue'
import { splitAnswerBlocks } from '@/utils/answerBlocks'
import { citationOf, codeOfCopyButton, renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  content: string
  citations: Citation[]
  streaming?: boolean
  /** Server message id; used to load page images for citation hover preview. */
  messageId?: string | null
}>()

const emit = defineEmits<{ cite: [n: number] }>()

const byNumber = computed(() => new Map(props.citations.map((c) => [c.n, c])))

const blocks = computed(() => splitAnswerBlocks(props.content))

function markdownHtml(text: string): string {
  return renderMarkdown(text, {
    citations: props.streaming ? undefined : new Set(byNumber.value.keys()),
  })
}

const hoverEl = ref<HTMLElement>()
const hovered = ref<Citation | null>(null)
const hoverImageUrl = ref<string | null>(null)
const hoverImageLoading = ref(false)
const previewUrl = ref<string | null>(null)
const CLOSE_DELAY_MS = 200
let closeTimer: number | undefined
let hoverFetchSeq = 0
const imageCache = new Map<number, string | null>()

function cancelClose(): void {
  window.clearTimeout(closeTimer)
  closeTimer = undefined
}

function scheduleClose(): void {
  cancelClose()
  closeTimer = window.setTimeout(() => {
    hovered.value = null
    hoverImageUrl.value = null
    hoverImageLoading.value = false
  }, CLOSE_DELAY_MS)
}

onBeforeUnmount(cancelClose)

async function loadHoverImage(n: number): Promise<void> {
  if (props.streaming || !props.messageId) return
  if (imageCache.has(n)) {
    hoverImageUrl.value = imageCache.get(n) ?? null
    return
  }
  const seq = ++hoverFetchSeq
  hoverImageLoading.value = true
  hoverImageUrl.value = null
  try {
    const src = await getCitationSource(props.messageId, n)
    const url = src.image_url || null
    imageCache.set(n, url)
    if (seq !== hoverFetchSeq || hovered.value?.n !== n) return
    hoverImageUrl.value = url
  } catch {
    imageCache.set(n, null)
    if (seq === hoverFetchSeq) hoverImageUrl.value = null
  } finally {
    if (seq === hoverFetchSeq) hoverImageLoading.value = false
  }
}

function onOver(event: MouseEvent): void {
  const hit = citationOf(event.target)
  if (!hit) return
  cancelClose()
  hoverEl.value = hit.el
  hovered.value = byNumber.value.get(hit.n) ?? null
  hoverImageUrl.value = imageCache.has(hit.n) ? (imageCache.get(hit.n) ?? null) : null
  hoverImageLoading.value = false
  if (hovered.value) void loadHoverImage(hit.n)
}

function onOut(event: MouseEvent): void {
  if (citationOf(event.relatedTarget)?.el !== hoverEl.value) scheduleClose()
}

function openHovered(): void {
  const n = hovered.value?.n
  cancelClose()
  hovered.value = null
  hoverImageUrl.value = null
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

function imageOf(target: EventTarget | null): string | null {
  if (!(target instanceof HTMLElement)) return null
  const img = target.closest<HTMLImageElement>('img.md-img')
  return img?.dataset.src || img?.getAttribute('src') || null
}

function onClick(event: Event): void {
  if (codeOfCopyButton(event.target)) {
    void copyCode(event.target)
    return
  }
  const src = imageOf(event.target)
  if (src) {
    previewUrl.value = src
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
  <div class="answer-content" :class="{ streaming }">
    <template v-for="(block, i) in blocks" :key="i">
      <!-- eslint-disable vue/no-v-html -- markdown-it runs with html: false -->
      <div
        v-if="block.type === 'markdown'"
        class="markdown"
        @mouseover="onOver"
        @mouseout="onOut"
        @click="onClick"
        @keydown.enter="onClick"
        v-html="markdownHtml(block.text)"
      />
      <!-- eslint-enable vue/no-v-html -->
      <AnswerTable
        v-else-if="block.type === 'table'"
        :headers="block.headers"
        :rows="block.rows"
      />
      <AnswerChart v-else-if="block.type === 'echarts'" :option="block.option" />
      <AnswerMermaid v-else-if="block.type === 'mermaid'" :source="block.source" />
    </template>
  </div>
  <el-popover
    :visible="hovered !== null"
    :virtual-ref="hoverEl"
    virtual-triggering
    placement="top"
    :width="hoverImageUrl ? 420 : 380"
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
      <div v-if="hoverImageLoading" class="cite-image-loading" data-test="cite-image-loading">
        附图加载中…
      </div>
      <button
        v-else-if="hoverImageUrl"
        type="button"
        class="cite-image"
        data-test="cite-image"
        @click="openHovered"
      >
        <img :src="hoverImageUrl" alt="引用页附图" loading="lazy" />
      </button>
      <div class="cite-quote">{{ hovered.quote }}</div>
      <button type="button" class="cite-hint" data-test="cite-open" @click="openHovered">
        {{ hoverImageUrl ? '点击查看原文与附图' : '点击查看原文' }}
      </button>
    </div>
  </el-popover>
  <ElImageViewer
    v-if="previewUrl"
    :url-list="[previewUrl]"
    teleported
    @close="previewUrl = null"
  />
</template>

<style scoped>
.answer-content {
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
.markdown :deep(.md-img-wrap) {
  display: block;
  margin: 12px 0;
}
.markdown :deep(.md-img) {
  display: block;
  max-width: min(100%, 640px);
  max-height: 420px;
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid var(--ekb-code-border);
  cursor: zoom-in;
  background: var(--ekb-bg-fill);
}
.markdown :deep(.md-img-blocked) {
  color: var(--el-text-color-secondary);
  font-size: 13px;
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
.answer-content.streaming > :deep(.markdown:last-child > :last-child)::after,
.answer-content.streaming > :deep(.markdown:last-of-type > :last-child)::after {
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
.cite-image-loading {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.cite-image {
  display: block;
  width: 100%;
  margin-top: 8px;
  padding: 0;
  overflow: hidden;
  border: 1px solid var(--ekb-code-border, var(--el-border-color));
  border-radius: 8px;
  background: var(--el-fill-color-light);
  cursor: zoom-in;
}
.cite-image img {
  display: block;
  width: 100%;
  max-height: 220px;
  object-fit: contain;
  background: #fff;
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
