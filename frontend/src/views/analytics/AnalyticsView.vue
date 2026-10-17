<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { EChartsCoreOption } from 'echarts/core'
import EChart from '@/components/charts/EChart.vue'
import {
  getAnalyticsContent,
  getAnalyticsFilters,
  getAnalyticsOverview,
  getLlmUsage,
  refreshAnalytics,
} from '@/api/analytics'
import type {
  AnalyticsContent,
  AnalyticsFilters,
  AnalyticsOverview,
  DocumentStatus,
  LatencyStage,
  LlmUsage,
  LlmUsageKind,
  LlmUsageUser,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'

type Tab = 'usage' | 'quality' | 'latency' | 'content' | 'llm'

const FEATURES = ['assistant', 'search', 'open_api', 'evaluation', 'curation', 'indexing', 'other']
const KINDS: LlmUsageKind[] = ['chat', 'embedding', 'rerank']
const STAGES: LatencyStage[] = ['retrieval', 'rerank', 'first_token', 'total']
const DOC_STATUSES: DocumentStatus[] = [
  'uploaded',
  'parsing',
  'parsed',
  'indexing',
  'indexed',
  'failed',
]

const GROUNDING_SERIES = [
  'grounded',
  'uncertain',
  'low_grounding',
  'no_evidence',
  'chitchat',
  'out_of_scope',
  'errors',
] as const

const { t } = useI18n()

function featureLabel(feature: string): string {
  return FEATURES.includes(feature) ? t(`analytics.feature.${feature}`) : feature
}

function kindLabel(kind: string): string {
  return (KINDS as string[]).includes(kind) ? t(`analytics.kind.${kind}`) : kind
}

function stageLabel(stage: LatencyStage): string {
  return t(`analytics.stage.${stage}`)
}

function docStatusLabel(status: string): string {
  return (DOC_STATUSES as string[]).includes(status) ? t(`analytics.docStatus.${status}`) : status
}

const meta = ref<AnalyticsFilters | null>(null)
const filters = reactive({ org_id: '', kb_id: '', range: [] as string[] })
const tab = ref<Tab>('usage')
const overview = ref<AnalyticsOverview | null>(null)
const content = ref<AnalyticsContent | null>(null)
const loading = ref(false)
const refreshing = ref(false)
const llm = ref<LlmUsage | null>(null)
const llmUser = ref<LlmUsageUser | null>(null)
const llmLoading = ref(false)

const auth = useAuthStore()
const canSeeLlm = computed(() => auth.can('analytics:usage'))
const showOrgFilter = computed(() => (meta.value?.orgs.length ?? 0) > 1)

function scope() {
  return { org_id: filters.org_id || undefined, kb_id: filters.kb_id || undefined }
}

async function loadMeta(): Promise<void> {
  meta.value = await getAnalyticsFilters(filters.org_id || undefined)
  filters.org_id = meta.value.org_id
  if (filters.kb_id && !meta.value.kbs.some((kb) => kb.id === filters.kb_id)) filters.kb_id = ''
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [range_from, range_to] = filters.range
    const [o, c] = await Promise.all([
      getAnalyticsOverview({ ...scope(), date_from: range_from, date_to: range_to }),
      getAnalyticsContent(scope()),
    ])
    overview.value = o
    content.value = c
    if (!filters.range.length) filters.range = [o.date_from, o.date_to]
  } finally {
    loading.value = false
  }
  await loadLlm()
}

async function loadLlm(): Promise<void> {
  if (!canSeeLlm.value) return
  llmLoading.value = true
  try {
    const [date_from, date_to] = filters.range
    llm.value = await getLlmUsage({
      org_id: filters.org_id || undefined,
      user_id: llmUser.value?.user_id,
      date_from,
      date_to,
    })
  } finally {
    llmLoading.value = false
  }
}

async function selectLlmUser(user: LlmUsageUser | null): Promise<void> {
  llmUser.value = user
  await loadLlm()
}

function userLabel(user: LlmUsageUser): string {
  return user.display_name || user.username || user.user_id
}

function tokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} M`
  if (value >= 10_000) return `${(value / 1000).toFixed(1)} K`
  return value.toLocaleString()
}

async function onOrgChange(): Promise<void> {
  filters.kb_id = ''
  llmUser.value = null
  await loadMeta()
  await load()
}

async function refreshNow(): Promise<void> {
  refreshing.value = true
  try {
    const result = await refreshAnalytics(2)
    ElMessage.success(t('analytics.filters.reaggregated', { n: result.days.length }))
    await load()
  } finally {
    refreshing.value = false
  }
}

// ---- formatting ---------------------------------------------------------------

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

function num(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`
}

function duration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return t('analytics.duration.seconds', { n: Math.round(seconds) })
  if (seconds < 3600) return t('analytics.duration.minutes', { n: Math.round(seconds / 60) })
  return t('analytics.duration.hours', { n: (seconds / 3600).toFixed(1) })
}

const qualityKpis = computed(() => {
  const q = overview.value?.quality
  if (!q) return []
  return [
    {
      label: t('analytics.kpi.likeRate'),
      value: pct(q.like_rate),
      sub: t('analytics.kpi.likeSub', { up: q.feedback_up, down: q.feedback_down }),
    },
    { label: t('analytics.kpi.refusalRate'), value: pct(q.refusal_rate) },
    { label: t('analytics.kpi.lowGroundingRate'), value: pct(q.low_grounding_rate) },
    { label: t('analytics.kpi.avgCitations'), value: num(q.avg_citations, 2) },
    { label: t('analytics.kpi.errorRate'), value: pct(q.error_rate) },
    { label: t('analytics.kpi.gaps'), value: `${q.gaps_new} / ${q.gaps_resolved}` },
  ]
})

const ratePercent = (v: number | null) => (v === null ? null : +(v * 100).toFixed(2))

// ---- charts -------------------------------------------------------------------

const days = computed(() => overview.value?.daily.map((d) => d.day) ?? [])

const usageTrend = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: [t('analytics.chart.questions'), t('analytics.chart.activeUsers')] },
    grid: { left: 48, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: [
      { type: 'value', name: t('analytics.chart.axisQuestions'), minInterval: 1 },
      { type: 'value', name: t('analytics.chart.axisUsers'), minInterval: 1 },
    ],
    series: [
      { name: t('analytics.chart.questions'), type: 'bar', data: daily.map((d) => d.questions) },
      {
        name: t('analytics.chart.activeUsers'),
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: daily.map((d) => d.active_users),
      },
    ],
  }
})

const kbHeatChart = computed<EChartsCoreOption>(() => {
  const rows = [...(overview.value?.kb_heat ?? [])].slice(0, 15).reverse()
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: [t('analytics.chart.questions'), t('analytics.chart.citedTimes')] },
    grid: { left: 140, right: 32, bottom: 24, top: 40 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: rows.map((r) => r.kb_name) },
    series: [
      { name: t('analytics.chart.questions'), type: 'bar', data: rows.map((r) => r.questions) },
      { name: t('analytics.chart.citedTimes'), type: 'bar', data: rows.map((r) => r.citations) },
    ],
  }
})

const qualityTrend = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  const lines = [
    { name: t('analytics.kpi.likeRate'), key: 'like_rate' },
    { name: t('analytics.kpi.refusalRate'), key: 'refusal_rate' },
    { name: t('analytics.kpi.lowGroundingRate'), key: 'low_grounding_rate' },
  ]
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => (v == null ? '—' : `${v}%`) },
    legend: { data: lines.map((s) => s.name) },
    grid: { left: 48, right: 32, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' }, max: 100 },
    series: lines.map((s) => ({
      name: s.name,
      type: 'line',
      smooth: true,
      connectNulls: true,
      data: daily.map((d) => ratePercent(d[s.key as 'like_rate'])),
    })),
  }
})

const groundingChart = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: GROUNDING_SERIES.map((key) => t(`analytics.grounding.${key}`)) },
    grid: { left: 48, right: 32, bottom: 32, top: 56 },
    xAxis: { type: 'category', data: days.value },
    yAxis: { type: 'value', minInterval: 1 },
    series: GROUNDING_SERIES.map((key) => ({
      name: t(`analytics.grounding.${key}`),
      type: 'bar',
      stack: 'grounding',
      data: daily.map((d) => d[key]),
    })),
  }
})

const gapChart = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: [
        t('analytics.chart.gapsNew'),
        t('analytics.chart.gapsResolved'),
        t('analytics.chart.avgCitations'),
      ],
    },
    grid: { left: 48, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: [
      { type: 'value', minInterval: 1 },
      { type: 'value', name: t('analytics.chart.axisCitations') },
    ],
    series: [
      { name: t('analytics.chart.gapsNew'), type: 'bar', data: daily.map((d) => d.gaps_new) },
      {
        name: t('analytics.chart.gapsResolved'),
        type: 'bar',
        data: daily.map((d) => d.gaps_resolved),
      },
      {
        name: t('analytics.chart.avgCitations'),
        type: 'line',
        yAxisIndex: 1,
        connectNulls: true,
        data: daily.map((d) => (d.avg_citations === null ? null : +d.avg_citations.toFixed(2))),
      },
    ],
  }
})

const latencyChart = computed<EChartsCoreOption>(() => {
  const stats = overview.value?.latency ?? []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: ms },
    legend: { data: ['P50', 'P95'] },
    grid: { left: 64, right: 32, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: stats.map((s) => stageLabel(s.stage)) },
    yAxis: { type: 'value', name: 'ms' },
    series: [
      { name: 'P50', type: 'bar', data: stats.map((s) => s.p50) },
      { name: 'P95', type: 'bar', data: stats.map((s) => s.p95) },
    ],
  }
})

const latencyTrend = computed<EChartsCoreOption>(() => {
  const rows = overview.value?.latency_daily ?? []
  const seriesName = (stage: LatencyStage) =>
    t('analytics.chart.stageP95', { stage: stageLabel(stage) })
  return {
    tooltip: { trigger: 'axis', valueFormatter: ms },
    legend: { data: STAGES.map(seriesName) },
    grid: { left: 64, right: 32, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: rows.map((r) => r.day) },
    yAxis: { type: 'value', name: 'ms' },
    series: STAGES.map((stage) => ({
      name: seriesName(stage),
      type: 'line',
      smooth: true,
      connectNulls: true,
      data: rows.map((r) => r.stages.find((s) => s.stage === stage)?.p95 ?? null),
    })),
  }
})

const docStatusChart = computed<EChartsCoreOption>(() => ({
  tooltip: { trigger: 'item' },
  legend: { orient: 'vertical', left: 'left' },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      data: (content.value?.document_status ?? []).map((s) => ({
        name: docStatusLabel(s.status),
        value: s.count,
      })),
    },
  ],
}))

const llmTrend = computed<EChartsCoreOption>(() => {
  const daily = llm.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: {
      data: [
        t('analytics.chart.promptTokens'),
        t('analytics.chart.completionTokens'),
        t('analytics.chart.calls'),
      ],
    },
    grid: { left: 64, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: daily.map((d) => d.day) },
    yAxis: [
      { type: 'value', name: 'token' },
      { type: 'value', name: t('analytics.chart.axisCalls'), minInterval: 1 },
    ],
    series: [
      {
        name: t('analytics.chart.promptTokens'),
        type: 'bar',
        stack: 'tokens',
        data: daily.map((d) => d.prompt_tokens),
      },
      {
        name: t('analytics.chart.completionTokens'),
        type: 'bar',
        stack: 'tokens',
        data: daily.map((d) => d.completion_tokens),
      },
      {
        name: t('analytics.chart.calls'),
        type: 'line',
        yAxisIndex: 1,
        smooth: true,
        data: daily.map((d) => d.calls),
      },
    ],
  }
})

const llmFeatureChart = computed<EChartsCoreOption>(() => ({
  tooltip: {
    trigger: 'item',
    valueFormatter: (v: unknown) =>
      t('analytics.chart.tokenValue', { n: Number(v).toLocaleString() }),
  },
  legend: { orient: 'vertical', left: 'left' },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      data: (llm.value?.by_feature ?? []).map((f) => ({
        name: featureLabel(f.feature),
        value: f.total_tokens,
      })),
    },
  ],
}))

onMounted(async () => {
  await loadMeta()
  await load()
})
</script>

<template>
  <div v-loading="loading" class="analytics">
    <el-card shadow="never">
      <el-form :inline="true" class="filters" @submit.prevent="load">
        <el-form-item v-if="showOrgFilter" :label="t('analytics.filters.org')">
          <el-select v-model="filters.org_id" style="width: 200px" @change="onOrgChange">
            <el-option v-for="org in meta?.orgs" :key="org.id" :label="org.name" :value="org.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('analytics.filters.kb')">
          <el-select
            v-model="filters.kb_id"
            clearable
            filterable
            :placeholder="t('analytics.filters.allKbs')"
            style="width: 220px"
            @change="load"
          >
            <el-option v-for="kb in meta?.kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('analytics.filters.date')">
          <el-date-picker
            v-model="filters.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            :range-separator="t('analytics.filters.rangeSeparator')"
            :start-placeholder="t('analytics.filters.start')"
            :end-placeholder="t('analytics.filters.end')"
            :clearable="false"
            @change="load"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">{{
            t('analytics.filters.query')
          }}</el-button>
          <el-button :loading="refreshing" @click="refreshNow">{{
            t('analytics.filters.reaggregate')
          }}</el-button>
        </el-form-item>
      </el-form>
      <div v-if="overview" class="refreshed">
        {{
          t('analytics.filters.refreshedAt', {
            time: formatDateTime(overview.refreshed_at),
            tz: meta?.timezone,
          })
        }}
      </div>
    </el-card>

    <el-tabs v-if="overview && content" v-model="tab">
      <el-tab-pane :label="t('analytics.tabs.usage')" name="usage">
        <el-row :gutter="16" class="stats">
          <el-col :span="6"
            ><el-statistic
              :title="t('analytics.usage.questions')"
              :value="overview.usage.questions"
          /></el-col>
          <el-col :span="6">
            <el-statistic
              :title="t('analytics.usage.activeUsersAvg')"
              :value="overview.usage.active_users_avg"
              :precision="2"
            />
          </el-col>
          <el-col :span="6">
            <el-statistic
              :title="t('analytics.usage.activeUsersPeak')"
              :value="overview.usage.active_users_peak"
            />
          </el-col>
          <el-col :span="6">
            <el-statistic :title="t('analytics.usage.answered')" :value="overview.usage.answered" />
          </el-col>
        </el-row>
        <el-card shadow="never" :header="t('analytics.usage.trend')">
          <EChart :option="usageTrend" />
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" :header="t('analytics.usage.kbHeat')">
              <EChart :option="kbHeatChart" height="360px" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" :header="t('analytics.usage.topQuestions')">
              <el-table :data="overview.top_questions" height="360" size="small">
                <el-table-column type="index" width="50" />
                <el-table-column
                  prop="query"
                  :label="t('analytics.usage.question')"
                  min-width="220"
                  show-overflow-tooltip
                />
                <el-table-column prop="count" :label="t('analytics.usage.count')" width="70" />
                <el-table-column
                  prop="unanswered"
                  :label="t('analytics.usage.unanswered')"
                  width="70"
                />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane :label="t('analytics.tabs.quality')" name="quality">
        <el-row :gutter="16" class="stats">
          <el-col v-for="kpi in qualityKpis" :key="kpi.label" :span="4">
            <div class="kpi__label">{{ kpi.label }}</div>
            <div class="kpi__value">{{ kpi.value }}</div>
            <div v-if="kpi.sub" class="sub">{{ kpi.sub }}</div>
          </el-col>
        </el-row>
        <el-card shadow="never" :header="t('analytics.quality.trend')">
          <EChart :option="qualityTrend" />
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" :header="t('analytics.quality.grounding')">
              <EChart :option="groundingChart" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" :header="t('analytics.quality.gaps')">
              <EChart :option="gapChart" />
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane :label="t('analytics.tabs.latency')" name="latency">
        <el-card shadow="never" :header="t('analytics.latency.byStage')">
          <el-table :data="overview.latency" size="small" class="latency-table">
            <el-table-column :label="t('analytics.latency.stage')" width="120">
              <template #default="{ row }">{{ stageLabel(row.stage as LatencyStage) }}</template>
            </el-table-column>
            <el-table-column prop="count" :label="t('analytics.latency.samples')" width="100" />
            <el-table-column label="P50">
              <template #default="{ row }">{{ ms(row.p50) }}</template>
            </el-table-column>
            <el-table-column label="P95">
              <template #default="{ row }">{{ ms(row.p95) }}</template>
            </el-table-column>
            <el-table-column :label="t('analytics.latency.avg')">
              <template #default="{ row }">{{ ms(row.avg) }}</template>
            </el-table-column>
          </el-table>
          <EChart :option="latencyChart" />
        </el-card>
        <el-card shadow="never" :header="t('analytics.latency.p95Trend')">
          <EChart :option="latencyTrend" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="t('analytics.tabs.content')" name="content">
        <el-row :gutter="16" class="stats">
          <el-col :span="4">
            <el-statistic
              :title="t('analytics.content.knowledgeBases')"
              :value="content.knowledge_bases"
            />
          </el-col>
          <el-col :span="4"
            ><el-statistic :title="t('analytics.content.documents')" :value="content.documents"
          /></el-col>
          <el-col :span="4"><el-statistic title="Chunk" :value="content.chunks" /></el-col>
          <el-col :span="4">
            <el-statistic
              :title="t('analytics.content.publishedKos')"
              :value="content.published_kos"
            />
          </el-col>
          <el-col :span="4">
            <el-statistic
              :title="t('analytics.content.zombieTotal', { n: content.zombie_days })"
              :value="content.zombie_total"
            />
          </el-col>
          <el-col :span="4">
            <el-statistic
              :title="t('analytics.content.expiredDocuments')"
              :value="content.expired_documents"
            />
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never" :header="t('analytics.content.docStatus')">
              <EChart :option="docStatusChart" height="260px" />
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never" :header="t('analytics.content.indexStatus')">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item :label="t('analytics.content.outboxPending')">
                  {{ content.index.outbox_pending }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('analytics.content.outboxProcessing')">
                  {{ content.index.outbox_processing }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('analytics.content.outboxDead')">
                  <el-text :type="content.index.outbox_dead ? 'danger' : undefined">
                    {{ content.index.outbox_dead }}
                  </el-text>
                </el-descriptions-item>
                <el-descriptions-item :label="t('analytics.content.oldestPending')">
                  {{ duration(content.index.oldest_pending_seconds) }}
                </el-descriptions-item>
              </el-descriptions>
              <el-table
                :data="content.index.failed_documents"
                size="small"
                height="170"
                :empty-text="t('analytics.content.noFailedDocs')"
                class="failed"
              >
                <el-table-column
                  prop="title"
                  :label="t('analytics.content.failedDoc')"
                  min-width="160"
                  show-overflow-tooltip
                />
                <el-table-column
                  prop="kb_name"
                  :label="t('analytics.content.kb')"
                  width="120"
                  show-overflow-tooltip
                />
                <el-table-column
                  prop="error_message"
                  :label="t('analytics.content.error')"
                  min-width="160"
                  show-overflow-tooltip
                />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
        <el-card
          shadow="never"
          :header="t('analytics.content.zombieDocs', { n: content.zombie_days })"
        >
          <el-table
            :data="content.zombie_documents"
            size="small"
            :empty-text="t('analytics.content.empty')"
          >
            <el-table-column
              :label="t('analytics.content.document')"
              min-width="220"
              show-overflow-tooltip
            >
              <template #default="{ row }">
                <RouterLink :to="`/knowledge/${row.kb_id}/documents/${row.id}`">
                  {{ row.title }}
                </RouterLink>
              </template>
            </el-table-column>
            <el-table-column
              prop="kb_name"
              :label="t('analytics.content.kb')"
              width="160"
              show-overflow-tooltip
            />
            <el-table-column :label="t('analytics.content.lastCited')" width="130">
              <template #default="{ row }">{{
                row.last_cited ?? t('analytics.content.never')
              }}</template>
            </el-table-column>
            <el-table-column :label="t('analytics.content.ingestedAt')" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card
              shadow="never"
              :header="t('analytics.content.expiringDocs', { n: content.expiring_days })"
            >
              <el-table
                :data="content.expiring_documents"
                size="small"
                :empty-text="t('analytics.content.empty')"
              >
                <el-table-column
                  :label="t('analytics.content.document')"
                  min-width="180"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    <RouterLink :to="`/knowledge/${row.kb_id}/documents/${row.id}`">
                      {{ row.title }}
                    </RouterLink>
                  </template>
                </el-table-column>
                <el-table-column
                  prop="kb_name"
                  :label="t('analytics.content.kb')"
                  width="120"
                  show-overflow-tooltip
                />
                <el-table-column :label="t('analytics.content.expiresAt')" width="170">
                  <template #default="{ row }">{{ formatDateTime(row.effective_to) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card
              shadow="never"
              :header="t('analytics.content.expiringKos', { n: content.expiring_days })"
            >
              <el-table
                :data="content.expiring_kos"
                size="small"
                :empty-text="t('analytics.content.empty')"
              >
                <el-table-column
                  :label="t('analytics.content.item')"
                  min-width="180"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    <RouterLink :to="`/curation/kos/${row.id}`">{{ row.title }}</RouterLink>
                  </template>
                </el-table-column>
                <el-table-column
                  prop="kb_name"
                  :label="t('analytics.content.kb')"
                  width="120"
                  show-overflow-tooltip
                />
                <el-table-column :label="t('analytics.content.expiresAt')" width="170">
                  <template #default="{ row }">{{ formatDateTime(row.effective_to) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane v-if="canSeeLlm" :label="t('analytics.tabs.llm')" name="llm">
        <div v-loading="llmLoading" class="llm">
          <div class="llm__scope">
            <span>{{ t('analytics.llm.scope') }}</span>
            <el-tag v-if="llmUser" closable @close="selectLlmUser(null)">
              {{ t('analytics.llm.user', { name: userLabel(llmUser) }) }}
            </el-tag>
            <span v-else class="sub">{{ t('analytics.llm.userHint') }}</span>
          </div>
          <template v-if="llm">
            <el-row :gutter="16" class="stats">
              <el-col :span="4">
                <div class="kpi__label">{{ t('analytics.llm.totalTokens') }}</div>
                <div class="kpi__value">{{ tokens(llm.summary.total_tokens) }}</div>
                <div class="sub">
                  {{
                    t('analytics.llm.inOut', {
                      prompt: tokens(llm.summary.prompt_tokens),
                      completion: tokens(llm.summary.completion_tokens),
                    })
                  }}
                </div>
              </el-col>
              <el-col :span="4">
                <el-statistic :title="t('analytics.llm.calls')" :value="llm.summary.calls" />
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">{{ t('analytics.llm.failureRate') }}</div>
                <div class="kpi__value">
                  {{ pct(llm.summary.calls ? llm.summary.errors / llm.summary.calls : null) }}
                </div>
                <div class="sub">{{ t('analytics.llm.failures', { n: llm.summary.errors }) }}</div>
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">{{ t('analytics.llm.avgLatency') }}</div>
                <div class="kpi__value">{{ ms(llm.summary.avg_latency_ms) }}</div>
              </el-col>
              <el-col :span="4">
                <el-statistic :title="t('analytics.llm.users')" :value="llm.summary.users" />
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">{{ t('analytics.llm.estimatedFallback') }}</div>
                <div class="kpi__value">
                  {{ llm.summary.estimated_calls }} / {{ llm.summary.fallback_calls }}
                </div>
                <div class="sub">{{ t('analytics.llm.estimatedHint') }}</div>
              </el-col>
            </el-row>
            <el-card shadow="never" :header="t('analytics.llm.dailyTokens')">
              <EChart :option="llmTrend" />
            </el-card>
            <el-row :gutter="16">
              <el-col :span="14">
                <el-card shadow="never" :header="t('analytics.llm.byModel')">
                  <el-table
                    :data="llm.by_model"
                    size="small"
                    height="300"
                    :empty-text="t('analytics.llm.noCalls')"
                  >
                    <el-table-column :label="t('analytics.llm.kind')" width="70">
                      <template #default="{ row }">{{ kindLabel(row.kind) }}</template>
                    </el-table-column>
                    <el-table-column
                      prop="model"
                      :label="t('analytics.llm.model')"
                      min-width="160"
                      show-overflow-tooltip
                    />
                    <el-table-column prop="calls" :label="t('analytics.llm.callsCol')" width="80" />
                    <el-table-column :label="t('analytics.llm.input')" width="90">
                      <template #default="{ row }">{{ tokens(row.prompt_tokens) }}</template>
                    </el-table-column>
                    <el-table-column :label="t('analytics.llm.output')" width="90">
                      <template #default="{ row }">{{ tokens(row.completion_tokens) }}</template>
                    </el-table-column>
                    <el-table-column :label="t('analytics.llm.total')" width="90">
                      <template #default="{ row }">{{ tokens(row.total_tokens) }}</template>
                    </el-table-column>
                    <el-table-column prop="errors" :label="t('analytics.llm.failed')" width="60" />
                    <el-table-column :label="t('analytics.llm.avgLatency')" width="90">
                      <template #default="{ row }">{{ ms(row.avg_latency_ms) }}</template>
                    </el-table-column>
                  </el-table>
                </el-card>
              </el-col>
              <el-col :span="10">
                <el-card shadow="never" :header="t('analytics.llm.byFeature')">
                  <EChart :option="llmFeatureChart" height="300px" />
                </el-card>
              </el-col>
            </el-row>
            <el-card
              v-if="!llmUser"
              shadow="never"
              :header="
                t('analytics.llm.userRanking', { total: llm.users_total, shown: llm.users.length })
              "
            >
              <el-table
                :data="llm.users"
                size="small"
                :empty-text="t('analytics.llm.noCalls')"
                highlight-current-row
                class="llm__users"
                @row-click="selectLlmUser"
              >
                <el-table-column type="index" width="50" />
                <el-table-column
                  :label="t('analytics.llm.userCol')"
                  min-width="160"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">
                    {{ userLabel(row as LlmUsageUser) }}
                    <el-tag v-if="row.is_service" size="small" type="info">{{
                      t('analytics.llm.serviceAccount')
                    }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column
                  :label="t('analytics.llm.department')"
                  min-width="180"
                  show-overflow-tooltip
                >
                  <template #default="{ row }">{{ row.department ?? '—' }}</template>
                </el-table-column>
                <el-table-column prop="calls" :label="t('analytics.llm.callsCol')" width="80" />
                <el-table-column :label="t('analytics.llm.assistantTokens')" width="120">
                  <template #default="{ row }">{{ tokens(row.assistant_tokens) }}</template>
                </el-table-column>
                <el-table-column :label="t('analytics.llm.input')" width="90">
                  <template #default="{ row }">{{ tokens(row.prompt_tokens) }}</template>
                </el-table-column>
                <el-table-column :label="t('analytics.llm.output')" width="90">
                  <template #default="{ row }">{{ tokens(row.completion_tokens) }}</template>
                </el-table-column>
                <el-table-column :label="t('analytics.llm.totalTokensCol')" width="100">
                  <template #default="{ row }">{{ tokens(row.total_tokens) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
            <div class="refreshed">
              {{
                t('analytics.llm.refreshedAt', {
                  time: llm.refreshed_at
                    ? formatDateTime(llm.refreshed_at)
                    : t('analytics.llm.notAggregated'),
                })
              }}
            </div>
          </template>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.analytics {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.analytics :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filters :deep(.el-form-item) {
  margin-bottom: 0;
}

.refreshed {
  margin-top: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.stats {
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-bg-color);
}

.kpi__label {
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 20px;
}

.kpi__value {
  font-size: 20px;
  line-height: 28px;
}

.sub {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.latency-table {
  margin-bottom: 16px;
}

.failed {
  margin-top: 12px;
}

.llm {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.llm__scope {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.llm__users :deep(.el-table__row) {
  cursor: pointer;
}
</style>
