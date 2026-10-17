<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import type { EChartsCoreOption } from 'echarts/core'
import EChart from '@/components/charts/EChart.vue'
import { compareEvalRuns } from '@/api/evaluation'
import type { EvalCompare, EvalRun } from '@/api/types'
import {
  bestRunPerMetric,
  formatConfigValue,
  formatMetric,
  isScoreMetric,
  metricLabel,
  sortMetricKeys,
} from '@/utils/evaluation'

const CASE_METRICS = ['recall@5', 'recall@10', 'mrr', 'ndcg@10', 'faithfulness', 'answer_relevance']

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const data = ref<EvalCompare | null>(null)
const loading = ref(false)
const caseMetric = ref('recall@5')
const onlyDiff = ref(true)

const runIds = computed(() =>
  String(route.query.ids ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
)

const runs = computed(() => data.value?.runs ?? [])
const metricKeys = computed(() => sortMetricKeys(data.value?.metric_keys ?? []))
const best = computed(() => bestRunPerMetric(metricKeys.value, runs.value))
const scoreKeys = computed(() => metricKeys.value.filter(isScoreMetric))
const caseMetricOptions = computed(() => CASE_METRICS.filter((k) => metricKeys.value.includes(k)))

function runLabel(run: EvalRun): string {
  return run.name || run.profile_name
}

const metricRows = computed(() => metricKeys.value.map((key) => ({ key })))

const chartOption = computed<EChartsCoreOption>(() => ({
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'shadow' },
    valueFormatter: (v: unknown) => (typeof v === 'number' ? `${v.toFixed(1)}%` : '—'),
  },
  legend: { data: runs.value.map(runLabel) },
  grid: { left: 48, right: 24, bottom: 64, top: 40 },
  xAxis: {
    type: 'category',
    data: scoreKeys.value.map(metricLabel),
    axisLabel: { interval: 0, rotate: 30 },
  },
  yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
  series: runs.value.map((run) => ({
    name: runLabel(run),
    type: 'bar',
    data: scoreKeys.value.map((k) => {
      const v = run.metrics[k]
      return v === null || v === undefined ? null : +(v * 100).toFixed(2)
    }),
  })),
}))

const caseRows = computed(() => {
  const rows = data.value?.cases ?? []
  const key = caseMetric.value
  return rows
    .map((c) => {
      const values = runs.value.map((r) => c.metrics[r.id]?.[key] ?? null)
      const defined = values.filter((v): v is number => v !== null)
      const spread = defined.length > 1 ? Math.max(...defined) - Math.min(...defined) : 0
      return { case_id: c.case_id, question: c.question, values, spread }
    })
    .filter((row) => !onlyDiff.value || row.spread > 0)
    .sort((a, b) => b.spread - a.spread)
})

async function load(): Promise<void> {
  if (runIds.value.length < 2) return
  loading.value = true
  try {
    data.value = await compareEvalRuns(runIds.value)
    if (!caseMetricOptions.value.includes(caseMetric.value)) {
      caseMetric.value = caseMetricOptions.value[0] ?? 'recall@5'
    }
  } finally {
    loading.value = false
  }
}

watch(runIds, load, { immediate: true })
</script>

<template>
  <div v-loading="loading" class="compare">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <el-button link @click="router.push('/admin/eval-runs')">{{
              t('evaluation.shared.runs')
            }}</el-button>
            <span class="sep">/</span>
            <span class="title">{{ t('evaluation.compare.title') }}</span>
          </div>
        </div>
      </template>
      <el-empty v-if="runIds.length < 2" :description="t('evaluation.compare.emptyHint')" />
      <template v-else-if="data">
        <el-table :data="metricRows" size="small" border>
          <el-table-column :label="t('evaluation.compare.metric')" width="180" fixed>
            <template #default="{ row }">{{ metricLabel(row.key) }}</template>
          </el-table-column>
          <el-table-column v-for="run in runs" :key="run.id" min-width="180">
            <template #header>
              <RouterLink :to="`/admin/eval-runs/${run.id}`">{{ runLabel(run) }}</RouterLink>
              <div class="sub">{{ run.profile_name }} · {{ run.dataset_name }}</div>
            </template>
            <template #default="{ row }">
              <span :class="{ best: best[row.key] === run.id }">
                {{ formatMetric(row.key, run.metrics[row.key]) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-card>

    <template v-if="data">
      <el-card shadow="never" :header="t('evaluation.compare.metricComparison')">
        <EChart :option="chartOption" height="360px" />
      </el-card>

      <el-card shadow="never" :header="t('evaluation.compare.configDiff')">
        <el-table
          :data="data.config_diff"
          size="small"
          border
          :empty-text="t('evaluation.compare.configSame')"
        >
          <el-table-column prop="key" :label="t('evaluation.shared.param')" min-width="220" />
          <el-table-column v-for="run in runs" :key="run.id" :label="runLabel(run)" min-width="160">
            <template #default="{ row }">
              <code class="mono">{{ formatConfigValue(row.values[run.id]) }}</code>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>{{ t('evaluation.compare.perCase') }}</span>
            <div class="case-tools">
              <el-select v-model="caseMetric" style="width: 160px">
                <el-option
                  v-for="key in caseMetricOptions"
                  :key="key"
                  :label="metricLabel(key)"
                  :value="key"
                />
              </el-select>
              <el-checkbox v-model="onlyDiff">{{ t('evaluation.compare.onlyDiff') }}</el-checkbox>
            </div>
          </div>
        </template>
        <el-table
          :data="caseRows"
          size="small"
          max-height="520"
          :empty-text="t('evaluation.compare.noDiff')"
        >
          <el-table-column
            prop="question"
            :label="t('evaluation.shared.question')"
            min-width="260"
            show-overflow-tooltip
          />
          <el-table-column
            v-for="(run, i) in runs"
            :key="run.id"
            :label="runLabel(run)"
            width="160"
          >
            <template #default="{ row }">{{ formatMetric(caseMetric, row.values[i]) }}</template>
          </el-table-column>
          <el-table-column :label="t('evaluation.compare.spread')" width="100">
            <template #default="{ row }">{{ formatMetric(caseMetric, row.spread) }}</template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.compare {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sep {
  margin: 0 8px;
  color: var(--el-text-color-secondary);
}

.title {
  font-weight: 600;
}

.sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: normal;
}

.best {
  color: var(--el-color-success);
  font-weight: 600;
}

.case-tools {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mono {
  font-family: var(--el-font-family-mono, monospace);
  font-size: 12px;
  word-break: break-all;
}
</style>
