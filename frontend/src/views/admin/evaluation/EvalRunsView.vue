<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import EvalRunDialog from '@/components/evaluation/EvalRunDialog.vue'
import { deleteEvalRun, listEvalDatasets, listEvalRuns } from '@/api/evaluation'
import type { EvalDataset, EvalRun, EvalRunStatus } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import { RUN_STATUS_META, formatMetric, metricLabel, runStatusLabel } from '@/utils/evaluation'

const POLL_MS = 3000
const SUMMARY_METRICS = ['recall@5', 'mrr', 'ndcg@10', 'faithfulness', 'answer_relevance']

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const datasets = ref<EvalDataset[]>([])
const datasetId = ref((route.query.dataset_id as string | undefined) ?? '')
const pager = reactive({ page: 1, size: 20 })
const items = ref<EvalRun[]>([])
const total = ref(0)
const loading = ref(false)
const selected = ref<EvalRun[]>([])
const runDialog = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

const active = computed(() =>
  items.value.some((r) => r.status === 'pending' || r.status === 'running'),
)
const canCompare = computed(() => {
  const n = selected.value.length
  return n >= 2 && n <= 4 && selected.value.every((r) => r.status === 'done')
})

async function load(quiet = false): Promise<void> {
  if (!quiet) loading.value = true
  try {
    const page = await listEvalRuns({ ...pager, dataset_id: datasetId.value || undefined })
    items.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
  schedule()
}

function schedule(): void {
  if (timer) clearTimeout(timer)
  timer = active.value ? setTimeout(() => void load(true), POLL_MS) : null
}

function search(): void {
  pager.page = 1
  void router.replace({ query: datasetId.value ? { dataset_id: datasetId.value } : {} })
  void load()
}

function compare(): void {
  void router.push({
    path: '/admin/eval-runs/compare',
    query: { ids: selected.value.map((r) => r.id).join(',') },
  })
}

async function remove(run: EvalRun): Promise<void> {
  await ElMessageBox.confirm(t('evaluation.runs.deleteConfirm'), t('evaluation.runs.deleteTitle'), {
    type: 'warning',
  })
  await deleteEvalRun(run.id)
  ElMessage.success(t('common.deleted'))
  await load()
}

function progress(run: EvalRun): number {
  return run.case_count ? Math.round((run.done_count / run.case_count) * 100) : 0
}

watch(datasetId, search)

onMounted(async () => {
  datasets.value = (await listEvalDatasets({ page: 1, size: 100 })).items
  await load()
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>{{ t('evaluation.shared.runs') }}</span>
        <div>
          <el-tooltip :content="t('evaluation.runs.compareTip')" placement="top">
            <el-button :disabled="!canCompare" @click="compare">
              {{ t('evaluation.runs.compareSelected', { n: selected.length }) }}
            </el-button>
          </el-tooltip>
          <el-button type="primary" @click="runDialog = true">{{
            t('evaluation.shared.runEval')
          }}</el-button>
        </div>
      </div>
    </template>

    <el-form :inline="true">
      <el-form-item :label="t('evaluation.shared.dataset')">
        <el-select
          v-model="datasetId"
          clearable
          :placeholder="t('common.all')"
          style="width: 240px"
        >
          <el-option v-for="ds in datasets" :key="ds.id" :label="ds.name" :value="ds.id" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="load()">{{ t('common.refresh') }}</el-button>
      </el-form-item>
    </el-form>

    <el-table
      v-loading="loading"
      :data="items"
      row-key="id"
      :empty-text="t('evaluation.runs.empty')"
      @selection-change="(rows: EvalRun[]) => (selected = rows)"
    >
      <el-table-column type="selection" width="44" />
      <el-table-column :label="t('evaluation.runs.run')" min-width="200">
        <template #default="{ row }">
          <RouterLink :to="`/admin/eval-runs/${row.id}`">{{
            row.name || row.profile_name
          }}</RouterLink>
          <div class="sub">{{ row.dataset_name }} · {{ row.profile_name }}</div>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.status')" width="170">
        <template #default="{ row }">
          <el-tag :type="RUN_STATUS_META[row.status as EvalRunStatus].type" size="small">
            {{ runStatusLabel(row.status as EvalRunStatus) }}
          </el-tag>
          <el-progress
            v-if="row.status === 'running'"
            :percentage="progress(row as EvalRun)"
            :stroke-width="6"
            class="progress"
          />
          <el-tooltip v-if="row.error" :content="row.error" placement="top">
            <el-text type="danger" size="small" class="err">{{
              t('evaluation.runs.reason')
            }}</el-text>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column :label="t('evaluation.shared.cases')" width="80">
        <template #default="{ row }">{{ row.done_count }}/{{ row.case_count }}</template>
      </el-table-column>
      <el-table-column
        v-for="key in SUMMARY_METRICS"
        :key="key"
        :label="metricLabel(key)"
        width="110"
      >
        <template #default="{ row }">{{ formatMetric(key, row.metrics[key]) }}</template>
      </el-table-column>
      <el-table-column :label="t('evaluation.shared.judge')" width="90">
        <template #default="{ row }">{{
          row.judge_enabled ? t('common.yes') : t('common.no')
        }}</template>
      </el-table-column>
      <el-table-column :label="t('common.createdAt')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="110" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/admin/eval-runs/${row.id}`)">
            {{ t('common.detail') }}
          </el-button>
          <el-button
            link
            type="danger"
            :disabled="row.status === 'pending' || row.status === 'running'"
            @click="remove(row as EvalRun)"
          >
            {{ t('common.delete') }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      @current-change="load()"
    />

    <EvalRunDialog v-model="runDialog" :dataset-id="datasetId || undefined" @created="load()" />
  </el-card>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.progress {
  margin-top: 4px;
}

.err {
  margin-left: 8px;
  cursor: help;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
