<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
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

const FEATURE_LABELS: Record<string, string> = {
  assistant: 'AI 助手',
  search: '搜索',
  open_api: '开放平台',
  evaluation: '评测',
  curation: '知识运营',
  indexing: '索引',
  other: '其他',
}

const KIND_LABELS: Record<LlmUsageKind, string> = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
}

const STAGE_LABELS: Record<LatencyStage, string> = {
  retrieval: '检索',
  rerank: '重排',
  first_token: '首 token',
  total: '总耗时',
}

const DOC_STATUS_LABELS: Record<DocumentStatus, string> = {
  uploaded: '已上传',
  parsing: '解析中',
  parsed: '已解析',
  indexing: '索引中',
  indexed: '已索引',
  failed: '失败',
}

const GROUNDING_SERIES = [
  { key: 'grounded', label: '有据回答' },
  { key: 'uncertain', label: '不确定' },
  { key: 'low_grounding', label: '低引用' },
  { key: 'no_evidence', label: '拒答' },
  { key: 'chitchat', label: '闲聊' },
  { key: 'out_of_scope', label: '超范围' },
  { key: 'errors', label: '错误' },
] as const

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
    ElMessage.success(`已重新汇总 ${result.days.length} 天数据`)
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
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

const qualityKpis = computed(() => {
  const q = overview.value?.quality
  if (!q) return []
  return [
    {
      label: '点赞率',
      value: pct(q.like_rate),
      sub: `赞 ${q.feedback_up} / 踩 ${q.feedback_down}`,
    },
    { label: '拒答率', value: pct(q.refusal_rate) },
    { label: '低引用比例', value: pct(q.low_grounding_rate) },
    { label: '平均引用数', value: num(q.avg_citations, 2) },
    { label: '错误率', value: pct(q.error_rate) },
    { label: '缺口 新增 / 解决', value: `${q.gaps_new} / ${q.gaps_resolved}` },
  ]
})

const ratePercent = (v: number | null) => (v === null ? null : +(v * 100).toFixed(2))

// ---- charts -------------------------------------------------------------------

const days = computed(() => overview.value?.daily.map((d) => d.day) ?? [])

const usageTrend = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['提问数', '日活用户'] },
    grid: { left: 48, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: [
      { type: 'value', name: '提问', minInterval: 1 },
      { type: 'value', name: '用户', minInterval: 1 },
    ],
    series: [
      { name: '提问数', type: 'bar', data: daily.map((d) => d.questions) },
      {
        name: '日活用户',
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
    legend: { data: ['提问数', '被引用次数'] },
    grid: { left: 140, right: 32, bottom: 24, top: 40 },
    xAxis: { type: 'value', minInterval: 1 },
    yAxis: { type: 'category', data: rows.map((r) => r.kb_name) },
    series: [
      { name: '提问数', type: 'bar', data: rows.map((r) => r.questions) },
      { name: '被引用次数', type: 'bar', data: rows.map((r) => r.citations) },
    ],
  }
})

const qualityTrend = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis', valueFormatter: (v: unknown) => (v == null ? '—' : `${v}%`) },
    legend: { data: ['点赞率', '拒答率', '低引用比例'] },
    grid: { left: 48, right: 32, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' }, max: 100 },
    series: [
      { name: '点赞率', key: 'like_rate' },
      { name: '拒答率', key: 'refusal_rate' },
      { name: '低引用比例', key: 'low_grounding_rate' },
    ].map((s) => ({
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
    legend: { data: GROUNDING_SERIES.map((s) => s.label) },
    grid: { left: 48, right: 32, bottom: 32, top: 56 },
    xAxis: { type: 'category', data: days.value },
    yAxis: { type: 'value', minInterval: 1 },
    series: GROUNDING_SERIES.map((s) => ({
      name: s.label,
      type: 'bar',
      stack: 'grounding',
      data: daily.map((d) => d[s.key]),
    })),
  }
})

const gapChart = computed<EChartsCoreOption>(() => {
  const daily = overview.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['新增缺口', '已解决缺口', '平均引用数'] },
    grid: { left: 48, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: days.value },
    yAxis: [
      { type: 'value', minInterval: 1 },
      { type: 'value', name: '引用数' },
    ],
    series: [
      { name: '新增缺口', type: 'bar', data: daily.map((d) => d.gaps_new) },
      { name: '已解决缺口', type: 'bar', data: daily.map((d) => d.gaps_resolved) },
      {
        name: '平均引用数',
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
    xAxis: { type: 'category', data: stats.map((s) => STAGE_LABELS[s.stage]) },
    yAxis: { type: 'value', name: 'ms' },
    series: [
      { name: 'P50', type: 'bar', data: stats.map((s) => s.p50) },
      { name: 'P95', type: 'bar', data: stats.map((s) => s.p95) },
    ],
  }
})

const latencyTrend = computed<EChartsCoreOption>(() => {
  const rows = overview.value?.latency_daily ?? []
  const stages = Object.keys(STAGE_LABELS) as LatencyStage[]
  return {
    tooltip: { trigger: 'axis', valueFormatter: ms },
    legend: { data: stages.map((s) => `${STAGE_LABELS[s]} P95`) },
    grid: { left: 64, right: 32, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: rows.map((r) => r.day) },
    yAxis: { type: 'value', name: 'ms' },
    series: stages.map((stage) => ({
      name: `${STAGE_LABELS[stage]} P95`,
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
        name: DOC_STATUS_LABELS[s.status] ?? s.status,
        value: s.count,
      })),
    },
  ],
}))

const llmTrend = computed<EChartsCoreOption>(() => {
  const daily = llm.value?.daily ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['输入 token', '输出 token', '调用次数'] },
    grid: { left: 64, right: 48, bottom: 32, top: 40 },
    xAxis: { type: 'category', data: daily.map((d) => d.day) },
    yAxis: [
      { type: 'value', name: 'token' },
      { type: 'value', name: '调用', minInterval: 1 },
    ],
    series: [
      { name: '输入 token', type: 'bar', stack: 'tokens', data: daily.map((d) => d.prompt_tokens) },
      {
        name: '输出 token',
        type: 'bar',
        stack: 'tokens',
        data: daily.map((d) => d.completion_tokens),
      },
      {
        name: '调用次数',
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
    valueFormatter: (v: unknown) => `${Number(v).toLocaleString()} token`,
  },
  legend: { orient: 'vertical', left: 'left' },
  series: [
    {
      type: 'pie',
      radius: ['40%', '70%'],
      data: (llm.value?.by_feature ?? []).map((f) => ({
        name: FEATURE_LABELS[f.feature] ?? f.feature,
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
        <el-form-item v-if="showOrgFilter" label="组织">
          <el-select v-model="filters.org_id" style="width: 200px" @change="onOrgChange">
            <el-option v-for="org in meta?.orgs" :key="org.id" :label="org.name" :value="org.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库">
          <el-select
            v-model="filters.kb_id"
            clearable
            filterable
            placeholder="全部知识库"
            style="width: 220px"
            @change="load"
          >
            <el-option v-for="kb in meta?.kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker
            v-model="filters.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            :clearable="false"
            @change="load"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button :loading="refreshing" @click="refreshNow">重新汇总</el-button>
        </el-form-item>
      </el-form>
      <div v-if="overview" class="refreshed">
        数据汇总于 {{ formatDateTime(overview.refreshed_at) }}（时区 {{ meta?.timezone }}）
      </div>
    </el-card>

    <el-tabs v-if="overview && content" v-model="tab">
      <el-tab-pane label="使用量" name="usage">
        <el-row :gutter="16" class="stats">
          <el-col :span="6"
            ><el-statistic title="提问数" :value="overview.usage.questions"
          /></el-col>
          <el-col :span="6">
            <el-statistic
              title="日均活跃用户"
              :value="overview.usage.active_users_avg"
              :precision="2"
            />
          </el-col>
          <el-col :span="6">
            <el-statistic title="峰值日活" :value="overview.usage.active_users_peak" />
          </el-col>
          <el-col :span="6">
            <el-statistic title="生成回答数" :value="overview.usage.answered" />
          </el-col>
        </el-row>
        <el-card shadow="never" header="提问与日活趋势">
          <EChart :option="usageTrend" />
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" header="知识库热度">
              <EChart :option="kbHeatChart" height="360px" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" header="热门问题">
              <el-table :data="overview.top_questions" height="360" size="small">
                <el-table-column type="index" width="50" />
                <el-table-column prop="query" label="问题" min-width="220" show-overflow-tooltip />
                <el-table-column prop="count" label="次数" width="70" />
                <el-table-column prop="unanswered" label="未答" width="70" />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="质量" name="quality">
        <el-row :gutter="16" class="stats">
          <el-col v-for="kpi in qualityKpis" :key="kpi.label" :span="4">
            <div class="kpi__label">{{ kpi.label }}</div>
            <div class="kpi__value">{{ kpi.value }}</div>
            <div v-if="kpi.sub" class="sub">{{ kpi.sub }}</div>
          </el-col>
        </el-row>
        <el-card shadow="never" header="质量趋势">
          <EChart :option="qualityTrend" />
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" header="回答类型分布">
              <EChart :option="groundingChart" />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" header="知识缺口与引用">
              <EChart :option="gapChart" />
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="性能" name="latency">
        <el-card shadow="never" header="各阶段耗时（区间汇总）">
          <el-table :data="overview.latency" size="small" class="latency-table">
            <el-table-column label="阶段" width="120">
              <template #default="{ row }">{{ STAGE_LABELS[row.stage as LatencyStage] }}</template>
            </el-table-column>
            <el-table-column prop="count" label="样本数" width="100" />
            <el-table-column label="P50">
              <template #default="{ row }">{{ ms(row.p50) }}</template>
            </el-table-column>
            <el-table-column label="P95">
              <template #default="{ row }">{{ ms(row.p95) }}</template>
            </el-table-column>
            <el-table-column label="平均">
              <template #default="{ row }">{{ ms(row.avg) }}</template>
            </el-table-column>
          </el-table>
          <EChart :option="latencyChart" />
        </el-card>
        <el-card shadow="never" header="P95 耗时趋势">
          <EChart :option="latencyTrend" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="内容" name="content">
        <el-row :gutter="16" class="stats">
          <el-col :span="4">
            <el-statistic title="知识库" :value="content.knowledge_bases" />
          </el-col>
          <el-col :span="4"><el-statistic title="文档" :value="content.documents" /></el-col>
          <el-col :span="4"><el-statistic title="Chunk" :value="content.chunks" /></el-col>
          <el-col :span="4">
            <el-statistic title="已发布知识条目" :value="content.published_kos" />
          </el-col>
          <el-col :span="4">
            <el-statistic
              :title="`僵尸文档（${content.zombie_days} 天未引用）`"
              :value="content.zombie_total"
            />
          </el-col>
          <el-col :span="4">
            <el-statistic title="已过期文档" :value="content.expired_documents" />
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="10">
            <el-card shadow="never" header="文档状态">
              <EChart :option="docStatusChart" height="260px" />
            </el-card>
          </el-col>
          <el-col :span="14">
            <el-card shadow="never" header="索引状态">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="Outbox 待处理">
                  {{ content.index.outbox_pending }}
                </el-descriptions-item>
                <el-descriptions-item label="Outbox 处理中">
                  {{ content.index.outbox_processing }}
                </el-descriptions-item>
                <el-descriptions-item label="Outbox 死信">
                  <el-text :type="content.index.outbox_dead ? 'danger' : undefined">
                    {{ content.index.outbox_dead }}
                  </el-text>
                </el-descriptions-item>
                <el-descriptions-item label="最久积压">
                  {{ duration(content.index.oldest_pending_seconds) }}
                </el-descriptions-item>
              </el-descriptions>
              <el-table
                :data="content.index.failed_documents"
                size="small"
                height="170"
                empty-text="没有处理失败的文档"
                class="failed"
              >
                <el-table-column
                  prop="title"
                  label="失败文档"
                  min-width="160"
                  show-overflow-tooltip
                />
                <el-table-column prop="kb_name" label="知识库" width="120" show-overflow-tooltip />
                <el-table-column
                  prop="error_message"
                  label="错误"
                  min-width="160"
                  show-overflow-tooltip
                />
              </el-table>
            </el-card>
          </el-col>
        </el-row>
        <el-card shadow="never" :header="`僵尸文档（超过 ${content.zombie_days} 天未被引用）`">
          <el-table :data="content.zombie_documents" size="small" empty-text="暂无">
            <el-table-column label="文档" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <RouterLink :to="`/knowledge/${row.kb_id}/documents/${row.id}`">
                  {{ row.title }}
                </RouterLink>
              </template>
            </el-table-column>
            <el-table-column prop="kb_name" label="知识库" width="160" show-overflow-tooltip />
            <el-table-column label="最近被引用" width="130">
              <template #default="{ row }">{{ row.last_cited ?? '从未' }}</template>
            </el-table-column>
            <el-table-column label="入库时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" :header="`即将过期的文档（${content.expiring_days} 天内）`">
              <el-table :data="content.expiring_documents" size="small" empty-text="暂无">
                <el-table-column label="文档" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    <RouterLink :to="`/knowledge/${row.kb_id}/documents/${row.id}`">
                      {{ row.title }}
                    </RouterLink>
                  </template>
                </el-table-column>
                <el-table-column prop="kb_name" label="知识库" width="120" show-overflow-tooltip />
                <el-table-column label="失效时间" width="170">
                  <template #default="{ row }">{{ formatDateTime(row.effective_to) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" :header="`即将过期的知识条目（${content.expiring_days} 天内）`">
              <el-table :data="content.expiring_kos" size="small" empty-text="暂无">
                <el-table-column label="条目" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    <RouterLink :to="`/curation/kos/${row.id}`">{{ row.title }}</RouterLink>
                  </template>
                </el-table-column>
                <el-table-column prop="kb_name" label="知识库" width="120" show-overflow-tooltip />
                <el-table-column label="失效时间" width="170">
                  <template #default="{ row }">{{ formatDateTime(row.effective_to) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane v-if="canSeeLlm" label="模型用量" name="llm">
        <div v-loading="llmLoading" class="llm">
          <div class="llm__scope">
            <span>统计范围：所选组织与日期内的全部模型调用（不受知识库筛选影响）</span>
            <el-tag v-if="llmUser" closable @close="selectLlmUser(null)">
              用户：{{ userLabel(llmUser) }}
            </el-tag>
            <span v-else class="sub">点击下方用户排行中的某一行可只看该用户</span>
          </div>
          <template v-if="llm">
            <el-row :gutter="16" class="stats">
              <el-col :span="4">
                <div class="kpi__label">总 token</div>
                <div class="kpi__value">{{ tokens(llm.summary.total_tokens) }}</div>
                <div class="sub">
                  输入 {{ tokens(llm.summary.prompt_tokens) }} / 输出
                  {{ tokens(llm.summary.completion_tokens) }}
                </div>
              </el-col>
              <el-col :span="4">
                <el-statistic title="调用次数" :value="llm.summary.calls" />
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">失败率</div>
                <div class="kpi__value">
                  {{ pct(llm.summary.calls ? llm.summary.errors / llm.summary.calls : null) }}
                </div>
                <div class="sub">失败 {{ llm.summary.errors }} 次</div>
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">平均耗时</div>
                <div class="kpi__value">{{ ms(llm.summary.avg_latency_ms) }}</div>
              </el-col>
              <el-col :span="4">
                <el-statistic title="使用人数" :value="llm.summary.users" />
              </el-col>
              <el-col :span="4">
                <div class="kpi__label">估算 / 降级调用</div>
                <div class="kpi__value">
                  {{ llm.summary.estimated_calls }} / {{ llm.summary.fallback_calls }}
                </div>
                <div class="sub">估算：模型未返回用量时按字数估算</div>
              </el-col>
            </el-row>
            <el-card shadow="never" header="每日 token 消耗">
              <EChart :option="llmTrend" />
            </el-card>
            <el-row :gutter="16">
              <el-col :span="14">
                <el-card shadow="never" header="按模型">
                  <el-table :data="llm.by_model" size="small" height="300" empty-text="暂无调用">
                    <el-table-column label="类型" width="70">
                      <template #default="{ row }">{{
                        KIND_LABELS[row.kind as LlmUsageKind] ?? row.kind
                      }}</template>
                    </el-table-column>
                    <el-table-column
                      prop="model"
                      label="模型"
                      min-width="160"
                      show-overflow-tooltip
                    />
                    <el-table-column prop="calls" label="调用" width="80" />
                    <el-table-column label="输入" width="90">
                      <template #default="{ row }">{{ tokens(row.prompt_tokens) }}</template>
                    </el-table-column>
                    <el-table-column label="输出" width="90">
                      <template #default="{ row }">{{ tokens(row.completion_tokens) }}</template>
                    </el-table-column>
                    <el-table-column label="合计" width="90">
                      <template #default="{ row }">{{ tokens(row.total_tokens) }}</template>
                    </el-table-column>
                    <el-table-column prop="errors" label="失败" width="60" />
                    <el-table-column label="平均耗时" width="90">
                      <template #default="{ row }">{{ ms(row.avg_latency_ms) }}</template>
                    </el-table-column>
                  </el-table>
                </el-card>
              </el-col>
              <el-col :span="10">
                <el-card shadow="never" header="按用途（token）">
                  <EChart :option="llmFeatureChart" height="300px" />
                </el-card>
              </el-col>
            </el-row>
            <el-card
              v-if="!llmUser"
              shadow="never"
              :header="`用户 token 排行（共 ${llm.users_total} 人，显示前 ${llm.users.length} 名）`"
            >
              <el-table
                :data="llm.users"
                size="small"
                empty-text="暂无调用"
                highlight-current-row
                class="llm__users"
                @row-click="selectLlmUser"
              >
                <el-table-column type="index" width="50" />
                <el-table-column label="用户" min-width="160" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ userLabel(row as LlmUsageUser) }}
                    <el-tag v-if="row.is_service" size="small" type="info">服务账号</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="部门" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">{{ row.department ?? '—' }}</template>
                </el-table-column>
                <el-table-column prop="calls" label="调用" width="80" />
                <el-table-column label="AI 助手 token" width="120">
                  <template #default="{ row }">{{ tokens(row.assistant_tokens) }}</template>
                </el-table-column>
                <el-table-column label="输入" width="90">
                  <template #default="{ row }">{{ tokens(row.prompt_tokens) }}</template>
                </el-table-column>
                <el-table-column label="输出" width="90">
                  <template #default="{ row }">{{ tokens(row.completion_tokens) }}</template>
                </el-table-column>
                <el-table-column label="合计 token" width="100">
                  <template #default="{ row }">{{ tokens(row.total_tokens) }}</template>
                </el-table-column>
              </el-table>
            </el-card>
            <div class="refreshed">
              数据汇总于
              {{
                llm.refreshed_at ? formatDateTime(llm.refreshed_at) : '尚未汇总'
              }}（最新调用需点击“重新汇总”或等待定时汇总）
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
