<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getEvalRun, listEvalResults } from '@/api/evaluation'
import type { EvalResult, EvalRun, EvalRunStatus } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import {
  RUN_STATUS_META,
  formatConfigValue,
  formatMetric,
  metricLabel,
  sortMetricKeys,
} from '@/utils/evaluation'

const POLL_MS = 3000
const CASE_METRICS = ['recall@5', 'recall@10', 'mrr', 'ndcg@10', 'faithfulness', 'answer_relevance']

const props = defineProps<{ runId: string }>()
const router = useRouter()

const run = ref<EvalRun | null>(null)
const onlyFailed = ref(false)
const pager = reactive({ page: 1, size: 20 })
const results = ref<EvalResult[]>([])
const total = ref(0)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

const finished = computed(() => run.value?.status === 'done' || run.value?.status === 'failed')
const metricKeys = computed(() => sortMetricKeys(Object.keys(run.value?.metrics ?? {})))
const progress = computed(() => {
  const r = run.value
  return r?.case_count ? Math.round((r.done_count / r.case_count) * 100) : 0
})

function flatten(obj: Record<string, unknown>, prefix = ''): [string, unknown][] {
  return Object.entries(obj).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return value && typeof value === 'object' && !Array.isArray(value)
      ? flatten(value as Record<string, unknown>, path)
      : [[path, value] as [string, unknown]]
  })
}

const configRows = computed(() =>
  run.value ? flatten(run.value.config).map(([key, value]) => ({ key, value })) : [],
)
const environmentRows = computed(() =>
  run.value ? flatten(run.value.environment).map(([key, value]) => ({ key, value })) : [],
)

async function loadRun(): Promise<void> {
  run.value = await getEvalRun(props.runId)
}

async function loadResults(): Promise<void> {
  loading.value = true
  try {
    const page = await listEvalResults(props.runId, { ...pager, only_failed: onlyFailed.value })
    results.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

async function poll(): Promise<void> {
  await loadRun()
  if (finished.value) {
    await loadResults()
    return
  }
  timer = setTimeout(() => void poll(), POLL_MS)
}

function search(): void {
  pager.page = 1
  void loadResults()
}

function judgeReasons(result: EvalResult): [string, string][] {
  const reasons = result.judge.reasons
  return reasons && typeof reasons === 'object'
    ? Object.entries(reasons as Record<string, string>)
    : []
}

onMounted(async () => {
  await poll()
  if (!finished.value) await loadResults()
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="run-detail">
    <el-card v-if="run" shadow="never">
      <template #header>
        <div class="card-header">
          <div>
            <el-button link @click="router.push('/admin/eval-runs')">评测任务</el-button>
            <span class="sep">/</span>
            <span class="title">{{ run.name || run.profile_name }}</span>
            <el-tag
              :type="RUN_STATUS_META[run.status as EvalRunStatus].type"
              size="small"
              class="tag"
            >
              {{ RUN_STATUS_META[run.status as EvalRunStatus].label }}
            </el-tag>
          </div>
          <el-button
            link
            type="primary"
            @click="router.push(`/admin/eval-runs?dataset_id=${run.dataset_id}`)"
          >
            同评测集的其他任务
          </el-button>
        </div>
      </template>

      <el-descriptions :column="3" size="small" border>
        <el-descriptions-item label="评测集">
          <RouterLink :to="`/admin/eval-datasets/${run.dataset_id}`">{{
            run.dataset_name
          }}</RouterLink>
        </el-descriptions-item>
        <el-descriptions-item label="检索策略">{{ run.profile_name }}</el-descriptions-item>
        <el-descriptions-item label="LLM 评判">{{
          run.judge_enabled ? '是' : '否'
        }}</el-descriptions-item>
        <el-descriptions-item label="进度">
          {{ run.done_count }}/{{ run.case_count }}
          <el-progress v-if="!finished" :percentage="progress" :stroke-width="6" class="progress" />
        </el-descriptions-item>
        <el-descriptions-item label="开始">{{
          formatDateTime(run.started_at)
        }}</el-descriptions-item>
        <el-descriptions-item label="结束">{{
          formatDateTime(run.finished_at)
        }}</el-descriptions-item>
        <el-descriptions-item v-if="run.error" label="错误" :span="3">
          <span class="error">{{ run.error }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <div v-if="metricKeys.length" class="metrics">
        <div v-for="key in metricKeys" :key="key" class="metric">
          <div class="metric__label">{{ metricLabel(key) }}</div>
          <div class="metric__value">{{ formatMetric(key, run.metrics[key]) }}</div>
        </div>
      </div>

      <el-collapse class="config">
        <el-collapse-item title="策略配置快照" name="config">
          <el-table :data="configRows" size="small" max-height="360">
            <el-table-column prop="key" label="参数" min-width="200" />
            <el-table-column label="值" min-width="200">
              <template #default="{ row }">{{ formatConfigValue(row.value) }}</template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
        <el-collapse-item title="运行环境（索引代、模型、切分参数）" name="env">
          <el-table :data="environmentRows" size="small" max-height="360">
            <el-table-column prop="key" label="项" min-width="200" />
            <el-table-column label="值" min-width="200">
              <template #default="{ row }">{{ formatConfigValue(row.value) }}</template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>用例结果</span>
          <el-checkbox v-model="onlyFailed" @change="search">只看错误</el-checkbox>
        </div>
      </template>
      <el-table v-loading="loading" :data="results" row-key="id" empty-text="暂无结果">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="result">
              <h4>召回结果</h4>
              <el-table :data="row.retrieved" size="small" max-height="300">
                <el-table-column prop="rank" label="#" width="50" />
                <el-table-column label="文档" min-width="200" show-overflow-tooltip>
                  <template #default="{ row: item }">
                    {{ item.title }}
                    <el-tag v-if="item.is_ko" size="small" type="warning">知识条目</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="分数" width="90">
                  <template #default="{ row: item }">{{ item.score?.toFixed(4) ?? '—' }}</template>
                </el-table-column>
                <el-table-column label="命中" width="70">
                  <template #default="{ row: item }">
                    <el-tag v-if="item.relevant" type="success" size="small">是</el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <template v-if="row.answer !== null">
                <h4>生成答案（{{ row.grounding ?? '—' }}）</h4>
                <div class="answer">{{ row.answer }}</div>
              </template>
              <template v-if="row.reference_answer">
                <h4>标准答案</h4>
                <div class="answer">{{ row.reference_answer }}</div>
              </template>
              <template v-if="judgeReasons(row as EvalResult).length">
                <h4>评判理由</h4>
                <el-descriptions :column="1" size="small" border>
                  <el-descriptions-item
                    v-for="[key, reason] in judgeReasons(row as EvalResult)"
                    :key="key"
                    :label="metricLabel(key)"
                  >
                    {{ reason }}
                  </el-descriptions-item>
                </el-descriptions>
              </template>
              <div v-if="row.judge.error || row.judge.skipped" class="muted">
                {{ row.judge.error ?? row.judge.skipped }}
              </div>
              <div v-if="row.error" class="error">{{ row.error }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
        <el-table-column
          v-for="key in CASE_METRICS"
          :key="key"
          :label="metricLabel(key)"
          width="110"
        >
          <template #default="{ row }">{{ formatMetric(key, row.metrics[key]) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.latency_ms }} ms</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.error" type="danger" size="small">错误</el-tag>
            <el-tag v-else type="success" size="small">完成</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="pager.page"
        v-model:page-size="pager.size"
        class="pager"
        layout="total, sizes, prev, pager, next"
        :total="total"
        @current-change="loadResults"
        @size-change="search"
      />
    </el-card>
  </div>
</template>

<style scoped>
.run-detail {
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

.tag {
  margin-left: 8px;
}

.progress {
  margin-top: 4px;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.metric {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}

.metric__label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.metric__value {
  margin-top: 4px;
  font-size: 20px;
  font-weight: 600;
}

.config {
  margin-top: 16px;
}

.result {
  padding: 8px 48px;
}

.result h4 {
  margin: 12px 0 6px;
}

.answer {
  white-space: pre-wrap;
  line-height: 1.6;
}

.muted {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.error {
  color: var(--el-color-danger);
  white-space: pre-wrap;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
