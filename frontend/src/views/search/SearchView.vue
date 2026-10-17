<script setup lang="ts">
import { computed, onActivated, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter, type LocationQuery } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Search } from '@element-plus/icons-vue'
import { listKnowledgeBases } from '@/api/knowledge'
import { getSearchOptions, listRetrievalProfiles, search } from '@/api/search'
import type {
  KnowledgeBase,
  RetrievalProfile,
  SearchHit,
  SearchOptions,
  SearchResponse,
} from '@/api/types'
import { CURATION_PERMISSIONS } from '@/router/routes'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import {
  dayRangeToParams,
  docTypeLabel,
  formatRank,
  formatScore,
  hitLocation,
} from '@/utils/search'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

const form = reactive({
  q: '',
  kbIds: [] as string[],
  docTypes: [] as string[],
  tags: [] as string[],
  days: null as [string, string] | null,
  debug: false,
  profileId: '',
})

const options = ref<SearchOptions>({ doc_types: [], tags: [], can_debug: false })
const kbOptions = ref<KnowledgeBase[]>([])
const kbLoading = ref(false)
const profiles = ref<RetrievalProfile[]>([])
const result = ref<SearchResponse | null>(null)
const loading = ref(false)
const debugPanel = ref(false)

const debugOn = computed(() => options.value.can_debug && form.debug)
const hasFilters = computed(
  () => form.kbIds.length + form.docTypes.length + form.tags.length > 0 || !!form.days,
)

// ---- URL <-> form ----------------------------------------------------------------

function list(value: LocationQuery[string]): string[] {
  if (value == null) return []
  return (Array.isArray(value) ? value : [value]).filter((v): v is string => !!v)
}

function readQuery(query: LocationQuery): void {
  form.q = typeof query.q === 'string' ? query.q : ''
  form.kbIds = list(query.kb)
  form.docTypes = list(query.type)
  form.tags = list(query.tag)
  const days = list(query.days)
  form.days = days.length === 2 ? [days[0], days[1]] : null
  form.debug = query.debug === '1'
  form.profileId = typeof query.profile === 'string' ? query.profile : ''
}

function writeQuery(): void {
  void router.replace({
    query: {
      q: form.q || undefined,
      kb: form.kbIds.length ? form.kbIds : undefined,
      type: form.docTypes.length ? form.docTypes : undefined,
      tag: form.tags.length ? form.tags : undefined,
      days: form.days ?? undefined,
      debug: debugOn.value ? '1' : undefined,
      profile: debugOn.value && form.profileId ? form.profileId : undefined,
    },
  })
}

// ---- data ------------------------------------------------------------------------

async function loadKbs(keyword = ''): Promise<void> {
  kbLoading.value = true
  try {
    const page = await listKnowledgeBases({ page: 1, size: 50, keyword: keyword || undefined })
    const selected = kbOptions.value.filter((kb) => form.kbIds.includes(kb.id))
    const ids = new Set(page.items.map((kb) => kb.id))
    kbOptions.value = [...page.items, ...selected.filter((kb) => !ids.has(kb.id))]
  } finally {
    kbLoading.value = false
  }
}

async function runSearch(): Promise<void> {
  const q = form.q.trim()
  if (!q) {
    result.value = null
    writeQuery()
    return
  }
  writeQuery()
  loading.value = true
  try {
    result.value = await search({
      q,
      kb_ids: form.kbIds,
      doc_types: form.docTypes,
      tags: form.tags,
      ...dayRangeToParams(form.days),
      debug: debugOn.value || undefined,
      profile_id: (debugOn.value && form.profileId) || undefined,
    })
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  form.kbIds = []
  form.docTypes = []
  form.tags = []
  form.days = null
  void runSearch()
}

function openHit(hit: SearchHit): void {
  if (hit.is_ko) {
    // Knowledge objects open in the curation editor (only for curators).
    if (auth.can(CURATION_PERMISSIONS)) {
      void router.push({ name: 'curation-ko', params: { koId: hit.document.id } })
    }
    return
  }
  void router.push({
    name: 'knowledge-document',
    params: { kbId: hit.document.kb_id, docId: hit.document.id },
    query: {
      chunk: hit.chunk_id,
      page: hit.page_start != null ? String(hit.page_start) : undefined,
    },
  })
}

function breadcrumb(hit: SearchHit): string[] {
  return hit.heading_path.length ? hit.heading_path : [hit.document.title]
}

// ---- debug -----------------------------------------------------------------------

interface StageRow {
  stage: string
  rank: string
  score: string
}

function scoreRows(hit: SearchHit): StageRow[] {
  return [
    { stage: 'Dense', rank: formatRank(hit.ranks.dense), score: formatScore(hit.scores.dense) },
    { stage: 'BM25', rank: formatRank(hit.ranks.bm25), score: formatScore(hit.scores.bm25) },
    { stage: 'RRF', rank: formatRank(hit.ranks.rrf), score: formatScore(hit.scores.rrf, 6) },
    {
      stage: 'Rerank',
      rank: formatRank(hit.ranks.rerank),
      score: formatScore(hit.scores.rerank),
    },
  ]
}

type Stages = Record<string, Record<string, unknown> | undefined>

const stageSummary = computed(() => {
  const debug = result.value?.debug
  if (!debug) return []
  const stages = debug.stages as Stages
  const routes = (stages.routes ?? {}) as Record<string, Record<string, unknown>>
  const rows = Object.entries(routes).map(([name, info]) => {
    const n = (info.hits as unknown[] | undefined)?.length ?? 0
    return {
      stage: name === 'sparse' ? 'BM25' : 'Dense',
      status: String(info.status ?? '-'),
      detail:
        info.took_ms != null
          ? t('search.candidatesTook', { n, ms: String(info.took_ms) })
          : t('search.candidates', { n }),
    }
  })
  const fusion = stages.fusion ?? {}
  const hydration = stages.hydration ?? {}
  const rerank = stages.rerank ?? {}
  const dropped = Object.entries((hydration.dropped ?? {}) as Record<string, number>)
    .map(([reason, n]) => `${reason} ${n}`)
    .join(t('search.sep.comma'))
  const requested = String(hydration.requested)
  const kept = String(hydration.kept)
  rows.push(
    {
      stage: t('search.rrfFusion'),
      status: 'ok',
      detail: t('search.fusionDetail', {
        k: String(fusion.k),
        weights: JSON.stringify(fusion.weights),
        total: String(fusion.total),
      }),
    },
    {
      stage: t('search.aclRecheck'),
      status: 'ok',
      detail: dropped
        ? t('search.hydrationDetailDropped', { requested, kept, dropped })
        : t('search.hydrationDetail', { requested, kept }),
    },
    {
      stage: 'Rerank',
      status: String(rerank.status ?? '-'),
      detail: rerank.model ? String(rerank.model) : '-',
    },
  )
  return rows
})

function statusType(status: string): 'success' | 'warning' | 'info' | 'danger' {
  if (status === 'ok' || status === 'cached') return 'success'
  if (status === 'disabled') return 'info'
  if (status.startsWith('degraded') || status === 'timeout') return 'warning'
  return 'danger'
}

async function toggleDebug(on: boolean): Promise<void> {
  if (on && !profiles.value.length) {
    profiles.value = await listRetrievalProfiles()
  }
  if (form.q.trim()) await runSearch()
}

onMounted(async () => {
  readQuery(route.query)
  const [opts] = await Promise.all([getSearchOptions(), loadKbs()])
  options.value = opts
  if (debugOn.value) profiles.value = await listRetrievalProfiles()
  if (form.q.trim()) await runSearch()
})

onActivated(() => {
  const q = typeof route.query.q === 'string' ? route.query.q : ''
  if (q && q !== form.q) {
    readQuery(route.query)
    void runSearch()
  }
})
</script>

<template>
  <div class="search-page">
    <el-card shadow="never">
      <div class="search-bar" data-guide="search-input">
        <el-input
          v-model="form.q"
          size="large"
          clearable
          :placeholder="t('search.placeholder')"
          :prefix-icon="Search"
          @keyup.enter="runSearch"
          @clear="runSearch"
        />
        <el-button type="primary" size="large" :loading="loading" @click="runSearch">
          {{ t('common.search') }}
        </el-button>
      </div>
      <div class="filters" data-guide="search-filters">
        <el-select
          v-model="form.kbIds"
          multiple
          filterable
          remote
          collapse-tags
          collapse-tags-tooltip
          clearable
          :remote-method="loadKbs"
          :loading="kbLoading"
          :placeholder="t('search.knowledgeBase')"
          class="filter"
          @change="runSearch"
        >
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <el-select
          v-model="form.docTypes"
          multiple
          collapse-tags
          clearable
          :placeholder="t('search.docType')"
          class="filter"
          @change="runSearch"
        >
          <el-option
            v-for="dt in options.doc_types"
            :key="dt"
            :label="docTypeLabel(dt)"
            :value="dt"
          />
        </el-select>
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          collapse-tags
          clearable
          :placeholder="t('search.tags')"
          class="filter"
          @change="runSearch"
        >
          <el-option v-for="tag in options.tags" :key="tag" :label="tag" :value="tag" />
        </el-select>
        <el-date-picker
          v-model="form.days"
          type="daterange"
          value-format="YYYY-MM-DD"
          :start-placeholder="t('search.ingestStart')"
          :end-placeholder="t('search.ingestEnd')"
          unlink-panels
          class="date-filter"
          @change="runSearch"
        />
        <el-button v-if="hasFilters" link type="primary" @click="resetFilters">{{
          t('search.clearFilters')
        }}</el-button>
        <div class="spacer" />
        <template v-if="options.can_debug">
          <el-select
            v-if="debugOn"
            v-model="form.profileId"
            clearable
            :placeholder="t('search.activeProfile')"
            class="profile-filter"
            @change="runSearch"
          >
            <el-option
              v-for="p in profiles"
              :key="p.id ?? 'builtin'"
              :label="p.is_active ? t('search.profileActive', { name: p.name }) : p.name"
              :value="p.id ?? 'builtin'"
            />
          </el-select>
          <el-switch
            v-model="form.debug"
            :active-text="t('search.debugMode')"
            @change="(v: string | number | boolean) => toggleDebug(Boolean(v))"
          />
        </template>
      </div>
      <i18n-t keypath="search.syntaxHint" tag="div" class="hint" data-guide="search-syntax">
        <template #operators>
          <code>kb:{{ t('search.syntaxKbName') }}</code>
          <code>tag:{{ t('search.syntaxTag') }}</code> <code>type:pdf</code>
          <code>date:2026-03</code> <code>after:2026-01-01</code>
        </template>
      </i18n-t>
    </el-card>

    <el-card v-if="result" v-loading="loading" shadow="never">
      <div class="summary">
        <i18n-t keypath="search.summary" tag="span">
          <template #total>
            <b>{{ result.total }}</b>
          </template>
          <template #ms>{{ result.took_ms.toFixed(0) }}</template>
        </i18n-t>
        <el-tag v-if="result.cache_hit" size="small" type="info">{{ t('search.cached') }}</el-tag>
        <el-tag v-for="term in result.exact_terms" :key="term" size="small" effect="plain">
          {{ t('search.exactTerm', { term }) }}
        </el-tag>
        <el-tag v-for="kb in result.filters.kbs" :key="kb.id" size="small" type="success">
          {{ t('search.kbFilter', { name: kb.name }) }}
        </el-tag>
        <div class="spacer" />
        <el-button v-if="result.debug" size="small" @click="debugPanel = true">
          {{ t('search.pipeline') }}
        </el-button>
      </div>
      <el-alert
        v-if="result.degraded.length"
        type="warning"
        show-icon
        :closable="false"
        class="notice"
        :title="t('search.degraded', { channels: result.degraded.join(t('search.sep.semicolon')) })"
      />
      <el-alert
        v-if="result.ignored_operators.length"
        type="info"
        show-icon
        :closable="false"
        class="notice"
        :title="t('search.ignoredOperators', { operators: result.ignored_operators.join('  ') })"
      />
      <el-alert
        v-if="result.filters.unresolved_kbs.length"
        type="info"
        show-icon
        :closable="false"
        class="notice"
        :title="
          t('search.unresolvedKbs', {
            kbs: result.filters.unresolved_kbs.join(t('search.sep.enum')),
          })
        "
      />

      <el-empty v-if="!result.items.length" :description="t('search.empty')" />
      <div v-for="hit in result.items" :key="hit.chunk_id" class="hit">
        <div
          class="hit-main"
          role="link"
          tabindex="0"
          @click="openHit(hit)"
          @keyup.enter="openHit(hit)"
        >
          <div class="hit-title">
            <!-- eslint-disable-next-line vue/no-v-html -- server-escaped, only <em> marks -->
            <span class="title" v-html="hit.title_html" />
            <el-tag v-if="hit.is_ko" size="small" type="success">{{
              t('search.knowledgeObject')
            }}</el-tag>
            <el-tag v-else size="small" effect="plain">
              {{ docTypeLabel(hit.document.doc_type) }}
            </el-tag>
            <el-tag v-if="hit.chunk_type === 'table'" size="small" type="warning">{{
              t('search.table')
            }}</el-tag>
          </div>
          <el-breadcrumb separator="›" class="crumbs">
            <el-breadcrumb-item v-for="(h, i) in breadcrumb(hit)" :key="i">{{
              h
            }}</el-breadcrumb-item>
          </el-breadcrumb>
          <!-- eslint-disable-next-line vue/no-v-html -- server-escaped, only <em> marks -->
          <div class="snippet" v-html="hit.snippet" />
          <div class="meta">
            <span>{{ hit.document.kb_name }}</span>
            <span>{{ hit.document.filename }}</span>
            <span v-if="hitLocation(hit)">{{ hitLocation(hit) }}</span>
            <span>{{
              t('search.updatedAt', { time: formatDateTime(hit.document.updated_at) })
            }}</span>
            <span v-for="tag in hit.document.tags" :key="tag" class="tag">#{{ tag }}</span>
          </div>
        </div>
        <div v-if="result.debug" class="hit-debug">
          <div class="debug-rank">#{{ hit.rank }}</div>
          <el-table :data="scoreRows(hit)" size="small" class="score-table">
            <el-table-column prop="stage" :label="t('search.stage')" width="70" />
            <el-table-column prop="rank" :label="t('search.rank')" width="60" />
            <el-table-column prop="score" :label="t('search.score')" />
          </el-table>
        </div>
      </div>
    </el-card>

    <el-drawer v-model="debugPanel" :title="t('search.pipeline')" size="50%">
      <template v-if="result?.debug">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('search.profile')">{{
            result.profile.name
          }}</el-descriptions-item>
          <el-descriptions-item label="Trace">
            <span class="mono">{{ result.trace_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item :label="t('search.normalizedQuery')" :span="2">
            {{ result.normalized_query }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('search.timings')" :span="2">
            <span v-for="(ms, key) in result.debug.timings" :key="key" class="timing">
              {{ key }}: {{ ms }}
            </span>
          </el-descriptions-item>
        </el-descriptions>
        <h4>{{ t('search.stages') }}</h4>
        <el-table :data="stageSummary" size="small">
          <el-table-column prop="stage" :label="t('search.stage')" width="120" />
          <el-table-column :label="t('common.status')" width="160">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="detail" :label="t('common.detail')" />
        </el-table>
        <el-collapse class="raw">
          <el-collapse-item :title="t('search.profileConfig')" name="config">
            <pre class="json">{{ JSON.stringify(result.debug.config, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item :title="t('search.rawStages')" name="stages">
            <pre class="json">{{ JSON.stringify(result.debug.stages, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.search-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.search-bar {
  display: flex;
  gap: 12px;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
}
.filter {
  width: 200px;
}
.date-filter {
  max-width: 280px;
}
.profile-filter {
  width: 200px;
}
.spacer {
  flex: 1;
}
.hint {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.hint code {
  padding: 0 4px;
  background: var(--el-fill-color-light);
  border-radius: 3px;
}
.summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--el-text-color-regular);
}
.notice {
  margin-bottom: 8px;
}
.hit {
  display: flex;
  gap: 16px;
  padding: 14px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.hit:last-child {
  border-bottom: 0;
}
.hit-main {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.hit-main:hover .title {
  text-decoration: underline;
}
.hit-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title {
  font-size: 16px;
  font-weight: 500;
  color: var(--el-color-primary);
}
.crumbs {
  margin: 6px 0;
  font-size: 12px;
}
.snippet {
  line-height: 1.7;
  color: var(--el-text-color-regular);
  word-break: break-word;
}
.title :deep(em),
.snippet :deep(em) {
  font-style: normal;
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  padding: 0 1px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tag {
  color: var(--el-color-primary-light-3);
}
.hit-debug {
  width: 280px;
  flex-shrink: 0;
}
.debug-rank {
  font-weight: 600;
  margin-bottom: 4px;
}
.score-table {
  width: 100%;
}
.mono,
.json {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.json {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow: auto;
}
.timing {
  margin-right: 12px;
}
.raw {
  margin-top: 16px;
}
</style>
