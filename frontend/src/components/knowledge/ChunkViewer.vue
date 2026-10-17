<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Chunk } from '@/api/types'
import { hitLocation } from '@/utils/search'

const props = defineProps<{
  chunks: Chunk[]
  loading?: boolean
  /** Chunk to reveal (expand its parent, scroll to it and highlight it). */
  focus?: string | null
}>()

const COLLAPSE_ANIMATION_MS = 350
const { t } = useI18n()

interface ParentNode {
  parent: Chunk
  children: Chunk[]
}

const keyword = ref('')
const showParentContent = ref(false)
const expanded = ref<string[]>([])

const tree = computed<ParentNode[]>(() => {
  const nodes = new Map<string, ParentNode>()
  for (const chunk of props.chunks) {
    if (chunk.level === 1) nodes.set(chunk.id, { parent: chunk, children: [] })
  }
  for (const chunk of props.chunks) {
    if (chunk.level !== 1 && chunk.parent_id) nodes.get(chunk.parent_id)?.children.push(chunk)
  }
  return [...nodes.values()]
})

const filtered = computed<ParentNode[]>(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return tree.value
  const hit = (c: Chunk) =>
    c.content.toLowerCase().includes(kw) || c.heading_path.join(' ').toLowerCase().includes(kw)
  return tree.value
    .map((n) => ({ parent: n.parent, children: n.children.filter(hit) }))
    .filter((n) => n.children.length || hit(n.parent))
})

const stats = computed(() => {
  const children = props.chunks.filter((c) => c.level !== 1)
  return {
    parents: tree.value.length,
    children: children.length,
    tables: children.filter((c) => c.chunk_type === 'table').length,
  }
})

function location(chunk: Chunk): string {
  return hitLocation(chunk)
}

function headingText(chunk: Chunk): string {
  return chunk.heading_path.length ? chunk.heading_path.join(' › ') : t('knowledge.chunk.docStart')
}

function expandAll(): void {
  expanded.value = filtered.value.map((n) => n.parent.id)
}

const focused = ref<string | null>(null)

watch(
  () => [props.focus, props.chunks] as const,
  async ([focus, chunks]) => {
    const target = focus ? chunks.find((c) => c.id === focus) : undefined
    if (!target) return
    focused.value = target.id
    keyword.value = ''
    const parentId = target.level === 1 ? target.id : target.parent_id
    if (parentId && !expanded.value.includes(parentId)) {
      expanded.value = [...expanded.value, parentId]
    }
    await nextTick()
    setTimeout(() => {
      document
        .getElementById(`chunk-${target.id}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, COLLAPSE_ANIMATION_MS)
  },
  { immediate: true },
)
</script>

<template>
  <div v-loading="loading" class="chunk-viewer">
    <div class="toolbar">
      <el-input
        v-model="keyword"
        :placeholder="t('knowledge.chunk.searchPlaceholder')"
        clearable
        class="search"
      />
      <el-checkbox v-model="showParentContent">{{ t('knowledge.chunk.showParent') }}</el-checkbox>
      <el-button link type="primary" @click="expandAll">{{
        t('knowledge.chunk.expandAll')
      }}</el-button>
      <el-button link type="primary" @click="expanded = []">{{
        t('knowledge.chunk.collapseAll')
      }}</el-button>
    </div>
    <div class="stats">
      {{ t('knowledge.chunk.stats', stats) }}
    </div>

    <el-empty v-if="!filtered.length" :description="t('knowledge.chunk.empty')" />
    <el-collapse v-else v-model="expanded">
      <el-collapse-item v-for="node in filtered" :key="node.parent.id" :name="node.parent.id">
        <template #title>
          <div class="parent-title">
            <el-tag size="small" effect="dark">{{
              t('knowledge.chunk.parent', { seq: node.parent.seq })
            }}</el-tag>
            <span class="heading" :title="headingText(node.parent)">
              {{ headingText(node.parent) }}
            </span>
            <span class="meta">
              {{
                t('knowledge.chunk.parentMeta', {
                  tokens: node.parent.token_count,
                  count: node.children.length,
                })
              }}
              <template v-if="location(node.parent)"> · {{ location(node.parent) }}</template>
            </span>
          </div>
        </template>
        <pre v-if="showParentContent" class="content parent-content">{{ node.parent.content }}</pre>
        <div
          v-for="child in node.children"
          :id="`chunk-${child.id}`"
          :key="child.id"
          class="child"
          :class="{ focused: child.id === focused }"
        >
          <div class="child-header">
            <el-tag size="small" :type="child.chunk_type === 'table' ? 'warning' : 'info'">
              {{ t(`knowledge.chunk.${child.chunk_type}`) }}
            </el-tag>
            <span class="seq">#{{ child.seq }}</span>
            <span class="heading">{{ headingText(child) }}</span>
            <span class="meta">
              {{ child.token_count }} tokens
              <template v-if="location(child)"> · {{ location(child) }}</template>
            </span>
          </div>
          <pre class="content" :class="{ table: child.chunk_type === 'table' }">{{
            child.content
          }}</pre>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}
.search {
  width: 240px;
}
.stats {
  margin: 8px 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.parent-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}
.heading {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta,
.seq {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  white-space: nowrap;
}
.child {
  margin: 8px 0 8px 12px;
  padding: 8px 12px;
  border-left: 3px solid var(--el-color-primary-light-5);
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}
.child.focused {
  border-left-color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  box-shadow: 0 0 0 1px var(--el-color-warning-light-5);
}
.child-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
}
.content.table {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  white-space: pre;
  overflow-x: auto;
}
.parent-content {
  padding: 8px 12px;
  background: var(--el-color-primary-light-9);
  border-radius: 4px;
}
</style>
