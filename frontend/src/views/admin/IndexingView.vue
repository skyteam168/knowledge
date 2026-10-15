<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkKbConsistency,
  getOutboxStats,
  listGenerations,
  listOutboxEvents,
  reloadSynonyms,
  repairKbIndex,
  retryDeadEvents,
  retryOutboxEvent,
} from '@/api/indexing'
import { listKnowledgeBases } from '@/api/knowledge'
import type {
  BackendDiff,
  ConsistencyReport,
  GenerationStatus,
  IndexGeneration,
  KnowledgeBase,
  OutboxEvent,
  OutboxStats,
  OutboxStatus,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'

const STATUS_META: Record<OutboxStatus, { label: string; type: TagType }> = {
  pending: { label: '待处理', type: 'warning' },
  processing: { label: '处理中', type: 'primary' },
  done: { label: '已完成', type: 'success' },
  dead: { label: '死信', type: 'danger' },
}

const GENERATION_META: Record<GenerationStatus, { label: string; type: TagType }> = {
  building: { label: '构建中', type: 'warning' },
  active: { label: '使用中', type: 'success' },
  retired: { label: '已下线', type: 'info' },
  failed: { label: '失败', type: 'danger' },
}

const auth = useAuthStore()
const isPlatformAdmin = computed(() => auth.profile?.is_platform_admin ?? false)

// ---- outbox -------------------------------------------------------------------

const stats = ref<OutboxStats>({ pending: 0, processing: 0, done: 0, dead: 0 })
const filters = reactive({ status: '' as OutboxStatus | '', event_type: '' })
const pager = reactive({ page: 1, size: 20 })
const events = ref<OutboxEvent[]>([])
const total = ref(0)
const loading = ref(false)
const retrying = ref<string | null>(null)

async function loadStats(): Promise<void> {
  stats.value = await getOutboxStats()
}

async function loadEvents(): Promise<void> {
  loading.value = true
  try {
    const page = await listOutboxEvents({
      status: filters.status || undefined,
      event_type: filters.event_type || undefined,
      ...pager,
    })
    events.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function refresh(): Promise<unknown> {
  return Promise.all([loadStats(), loadEvents()])
}

function search(): void {
  pager.page = 1
  void loadEvents()
}

function filterByStatus(status: OutboxStatus): void {
  filters.status = filters.status === status ? '' : status
  search()
}

async function retry(event: OutboxEvent): Promise<void> {
  retrying.value = event.id
  try {
    await retryOutboxEvent(event.id)
    ElMessage.success('已重新排队')
    await refresh()
  } finally {
    retrying.value = null
  }
}

async function retryAllDead(): Promise<void> {
  await ElMessageBox.confirm(`确定将 ${stats.value.dead} 条死信事件全部重新排队？`, '重试死信', {
    type: 'warning',
  })
  const { count } = await retryDeadEvents()
  ElMessage.success(`已重新排队 ${count} 条事件`)
  await refresh()
}

// ---- generations --------------------------------------------------------------

const generations = ref<IndexGeneration[]>([])

async function loadGenerations(): Promise<void> {
  generations.value = await listGenerations()
}

async function onReloadSynonyms(): Promise<void> {
  await reloadSynonyms()
  ElMessage.success('同义词词典已重新加载')
}

// ---- consistency --------------------------------------------------------------

const kbOptions = ref<KnowledgeBase[]>([])
const kbLoading = ref(false)
const selectedKb = ref('')
const report = ref<ConsistencyReport | null>(null)
const checking = ref(false)
const repairing = ref(false)

async function searchKbs(keyword = ''): Promise<void> {
  kbLoading.value = true
  try {
    kbOptions.value = (await listKnowledgeBases({ keyword, page: 1, size: 50 })).items
  } finally {
    kbLoading.value = false
  }
}

async function check(): Promise<void> {
  if (!selectedKb.value) return
  checking.value = true
  try {
    report.value = await checkKbConsistency(selectedKb.value)
  } finally {
    checking.value = false
  }
}

async function repair(): Promise<void> {
  if (!report.value) return
  repairing.value = true
  try {
    await repairKbIndex(report.value.kb_id)
    ElMessage.success('修复任务已提交，完成后可重新校验')
  } finally {
    repairing.value = false
  }
}

const diffRows = computed(() => {
  const r = report.value
  if (!r) return []
  const row = (name: string, diff: BackendDiff) => ({ name, ...diff })
  return [row('Qdrant', r.qdrant), row('OpenSearch', r.opensearch)]
})

function kbName(id: string): string {
  return kbOptions.value.find((kb) => kb.id === id)?.name ?? id
}

onMounted(() => {
  void refresh()
  void loadGenerations()
  void searchKbs()
})
</script>

<template>
  <div class="indexing">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>Outbox 事件</span>
          <div>
            <el-button :disabled="!stats.dead" type="danger" plain @click="retryAllDead">
              重试全部死信
            </el-button>
            <el-button @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>

      <el-row :gutter="16" class="stats">
        <el-col v-for="(meta, key) in STATUS_META" :key="key" :span="6">
          <div
            class="stat"
            :class="{ 'stat--active': filters.status === key }"
            @click="filterByStatus(key)"
          >
            <el-statistic :title="meta.label" :value="stats[key]" />
          </div>
        </el-col>
      </el-row>

      <el-form :inline="true" @submit.prevent="search">
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部" style="width: 120px">
            <el-option
              v-for="(meta, key) in STATUS_META"
              :key="key"
              :label="meta.label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="事件类型">
          <el-input v-model="filters.event_type" placeholder="如 document.chunks_ready" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="events" row-key="id" empty-text="暂无事件">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item label="事件 ID">{{ row.id }}</el-descriptions-item>
                <el-descriptions-item label="完成时间">
                  {{ formatDateTime(row.processed_at) }}
                </el-descriptions-item>
                <el-descriptions-item label="租约到期">
                  {{ formatDateTime(row.locked_until) }}
                </el-descriptions-item>
                <el-descriptions-item label="下次重试">
                  {{ formatDateTime(row.next_attempt_at) }}
                </el-descriptions-item>
                <el-descriptions-item label="Payload" :span="2">
                  <code class="mono">{{ JSON.stringify(row.payload) }}</code>
                </el-descriptions-item>
                <el-descriptions-item label="错误" :span="2">
                  <span class="error">{{ row.last_error ?? '—' }}</span>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="event_type" label="事件类型" min-width="180" />
        <el-table-column label="聚合" min-width="220">
          <template #default="{ row }">
            {{ row.aggregate_type }} / <span class="mono">{{ row.aggregate_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="STATUS_META[row.status as OutboxStatus].type" size="small">
              {{ STATUS_META[row.status as OutboxStatus].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="retry_count" label="重试次数" width="90" />
        <el-table-column label="最近错误" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.last_error ?? '' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'dead' || row.status === 'pending'"
              link
              type="primary"
              :loading="retrying === row.id"
              @click="retry(row as OutboxEvent)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="pager.page"
        v-model:page-size="pager.size"
        class="pager"
        layout="total, sizes, prev, pager, next"
        :total="total"
        @current-change="loadEvents"
        @size-change="search"
      />
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>一致性校验</span>
        </div>
      </template>
      <el-form :inline="true" @submit.prevent="check">
        <el-form-item label="知识库">
          <el-select
            v-model="selectedKb"
            filterable
            remote
            :remote-method="searchKbs"
            :loading="kbLoading"
            placeholder="选择知识库"
            style="width: 260px"
          >
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :disabled="!selectedKb"
            :loading="checking"
          >
            校验
          </el-button>
        </el-form-item>
      </el-form>

      <template v-if="report">
        <el-alert
          :type="report.consistent ? 'success' : 'warning'"
          :closable="false"
          show-icon
          class="report-alert"
        >
          <template #title>
            {{ kbName(report.kb_id) }}（索引代 v{{ report.generation }}）：
            {{
              report.consistent
                ? '数据一致'
                : `发现差异，需重建 ${report.reindex_documents.length} 个文档`
            }}
          </template>
          <div>
            校验时间 {{ formatDateTime(report.checked_at) }}；PostgreSQL chunk 数
            {{ report.pg_count }}
            <span v-if="report.skipped_documents">
              ；{{ report.skipped_documents }} 个文档正在处理中，已跳过
            </span>
          </div>
        </el-alert>

        <el-table :data="diffRows" size="small">
          <el-table-column prop="name" label="索引" width="120" />
          <el-table-column prop="count" label="条数" width="100" />
          <el-table-column prop="missing_count" label="缺失" width="100" />
          <el-table-column prop="extra_count" label="多余" width="100" />
          <el-table-column label="缺失样例" min-width="200">
            <template #default="{ row }">
              <code v-for="id in row.missing" :key="id" class="mono id">{{ id }}</code>
            </template>
          </el-table-column>
          <el-table-column label="多余样例" min-width="200">
            <template #default="{ row }">
              <code v-for="id in row.extra" :key="id" class="mono id">{{ id }}</code>
            </template>
          </el-table-column>
        </el-table>

        <div class="repair">
          <el-button
            type="warning"
            :disabled="report.consistent"
            :loading="repairing"
            @click="repair"
          >
            一键修复
          </el-button>
        </div>
      </template>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>索引代（蓝绿切换）</span>
          <div>
            <el-button v-if="isPlatformAdmin" @click="onReloadSynonyms">重新加载同义词</el-button>
            <el-button @click="loadGenerations">刷新</el-button>
          </div>
        </div>
      </template>
      <el-table :data="generations" row-key="version" empty-text="尚未创建索引">
        <el-table-column label="版本" width="80">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="GENERATION_META[row.status as GenerationStatus].type" size="small">
              {{ GENERATION_META[row.status as GenerationStatus].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="qdrant_collection" label="Qdrant collection" min-width="150" />
        <el-table-column prop="opensearch_index" label="OpenSearch index" min-width="150" />
        <el-table-column label="Embedding" min-width="180">
          <template #default="{ row }"
            >{{ row.embedding_model }}（{{ row.embedding_dim }} 维）</template
          >
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="启用时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.activated_at) }}</template>
        </el-table-column>
        <el-table-column label="错误" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.error ?? '' }}</template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.indexing {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.stats {
  margin-bottom: 16px;
}

.stat {
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  cursor: pointer;
}

.stat--active {
  border-color: var(--el-color-primary);
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.detail {
  padding: 8px 48px;
}

.mono {
  font-family: var(--el-font-family-mono, monospace);
  font-size: 12px;
  word-break: break-all;
}

.id {
  display: block;
}

.error {
  color: var(--el-color-danger);
  white-space: pre-wrap;
}

.report-alert {
  margin-bottom: 12px;
}

.repair {
  margin-top: 12px;
  text-align: right;
}
</style>
