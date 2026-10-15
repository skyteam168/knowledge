<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getCitationSource } from '@/api/chat'
import { HttpError } from '@/api/http'
import type { Citation, CitationSource } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { KO_TYPE_LABEL } from '@/utils/curation'
import { formatDateTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import { hitLocation } from '@/utils/search'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ messageId: string | null; citation: Citation | null }>()

const router = useRouter()
const source = ref<CitationSource | null>(null)
const error = ref('')
const loading = ref(false)
const body = ref<HTMLElement>()

async function load(): Promise<void> {
  const { messageId, citation } = props
  if (!messageId || !citation) return
  source.value = null
  error.value = ''
  loading.value = true
  try {
    source.value = await getCitationSource(messageId, citation.n)
    await nextTick()
    body.value?.querySelector('.segment.highlight')?.scrollIntoView({ block: 'center' })
  } catch (err) {
    error.value = err instanceof HttpError ? err.message : '原文加载失败'
  } finally {
    loading.value = false
  }
}

watch(
  () => [visible.value, props.messageId, props.citation?.n] as const,
  ([open]) => {
    if (open) void load()
  },
)

function openDocument(): void {
  const doc = source.value?.document
  if (!doc) return
  void router.push({
    name: 'knowledge-document',
    params: { kbId: doc.kb_id, docId: doc.id },
    query: {
      chunk: source.value?.anchor_chunk_id,
      page: source.value?.page_start != null ? String(source.value.page_start) : undefined,
    },
  })
}

const auth = useAuthStore()
const canEditKo = computed(() => auth.can(['ko:edit', 'review:approve']))

function openKo(): void {
  const ko = source.value?.ko
  if (ko) void router.push({ name: 'curation-ko', params: { koId: ko.id } })
}

function openKoSource(documentId: string, chunkId: string | null): void {
  const kbId = source.value?.document.kb_id
  if (!kbId) return
  void router.push({
    name: 'knowledge-document',
    params: { kbId, docId: documentId },
    query: { chunk: chunkId ?? undefined },
  })
}

function location(s: CitationSource): string {
  return hitLocation({ ...s, sheet_name: null, slide_number: null })
}
</script>

<template>
  <el-drawer v-model="visible" size="42%" :title="citation ? `引用 [${citation.n}]` : '引用'">
    <div ref="body" v-loading="loading" class="drawer-body">
      <template v-if="source?.is_ko && source.ko">
        <div class="doc-title">
          <el-tag type="success" size="small" effect="dark">知识条目</el-tag>
          {{ source.ko.question }}
        </div>
        <div class="doc-meta">
          <span>{{ source.document.kb_name }}</span>
          <span>{{ KO_TYPE_LABEL[source.ko.ko_type] ?? source.ko.ko_type }}</span>
          <span>v{{ source.document.version }}</span>
          <span v-if="source.ko.effective_to">
            有效期至 {{ formatDateTime(source.ko.effective_to) }}
          </span>
        </div>
        <el-alert
          v-if="source.outdated"
          type="warning"
          show-icon
          :closable="false"
          class="notice"
          title="该知识条目在回答生成后已更新，以下为当前发布版本"
        />
        <div v-if="source.ko.variants.length" class="variants">
          <span class="label">相似问法：</span>
          <el-tag v-for="v in source.ko.variants" :key="v" size="small" type="info">{{ v }}</el-tag>
        </div>
        <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
        <div class="segments markdown ko-answer" v-html="renderMarkdown(source.ko.answer)" />
        <template v-if="source.ko.sources.length">
          <div class="label">依据文档</div>
          <div
            v-for="s in source.ko.sources"
            :key="`${s.document_id}:${s.chunk_id}`"
            class="ko-src"
          >
            <el-link type="primary" @click="openKoSource(s.document_id, s.chunk_id)">
              {{ s.title }}
            </el-link>
            <span v-if="s.heading_path.length" class="doc-meta">{{
              s.heading_path.join(' › ')
            }}</span>
            <p v-if="s.quote" class="segment">{{ s.quote }}</p>
          </div>
        </template>
        <el-button v-if="canEditKo" type="primary" plain class="notice" @click="openKo">
          打开知识条目
        </el-button>
      </template>
      <template v-else-if="source">
        <div class="doc-title">{{ source.document.title }}</div>
        <div class="doc-meta">
          <span>{{ source.document.kb_name }}</span>
          <span>{{ source.document.filename }}</span>
          <span>v{{ source.document.version }}</span>
          <span v-if="location(source)">{{ location(source) }}</span>
        </div>
        <el-breadcrumb v-if="source.heading_path.length" separator="›" class="crumbs">
          <el-breadcrumb-item v-for="(h, i) in source.heading_path" :key="i">{{
            h
          }}</el-breadcrumb-item>
        </el-breadcrumb>
        <el-alert
          v-if="source.outdated"
          type="warning"
          show-icon
          :closable="false"
          class="notice"
          title="该文档在回答生成后已更新，以下内容可能与回答引用时不同"
        />
        <div class="segments">
          <p
            v-for="seg in source.segments"
            :key="seg.chunk_id"
            class="segment"
            :class="{ highlight: seg.highlight }"
          >
            {{ seg.content }}
          </p>
        </div>
        <el-button type="primary" plain @click="openDocument">打开原文档</el-button>
      </template>
      <template v-else-if="error && citation">
        <el-alert type="warning" show-icon :closable="false" class="notice" :title="error" />
        <div class="doc-title">{{ citation.title }}</div>
        <p class="segment highlight">{{ citation.quote }}</p>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.drawer-body {
  min-height: 200px;
}
.doc-title {
  font-size: 16px;
  font-weight: 600;
}
.doc-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.crumbs {
  margin-top: 8px;
  font-size: 12px;
}
.notice {
  margin-top: 12px;
}
.segments {
  margin: 12px 0 16px;
}
.segment {
  margin: 0 0 8px;
  padding: 8px 10px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
  border-left: 3px solid transparent;
  border-radius: 2px;
}
.segment.highlight {
  color: var(--el-text-color-primary);
  background: var(--el-color-warning-light-9);
  border-left-color: var(--el-color-warning);
}
.variants {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
}
.label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ko-answer {
  padding: 8px 12px;
  background: var(--el-color-success-light-9);
  border-radius: 4px;
}
.ko-src {
  margin-top: 8px;
}
</style>
