<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
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

const STATUS_TYPES: Record<OutboxStatus, TagType> = {
  pending: 'warning',
  processing: 'primary',
  done: 'success',
  dead: 'danger',
}

const GENERATION_TYPES: Record<GenerationStatus, TagType> = {
  building: 'warning',
  active: 'success',
  retired: 'info',
  failed: 'danger',
}

const { t } = useI18n()

const STATUS_META = computed(
  () =>
    Object.fromEntries(
      (Object.keys(STATUS_TYPES) as OutboxStatus[]).map((s) => [
        s,
        { label: t(`indexing.outboxStatus.${s}`), type: STATUS_TYPES[s] },
      ]),
    ) as Record<OutboxStatus, { label: string; type: TagType }>,
)

function generationMeta(status: GenerationStatus): { label: string; type: TagType } {
  return { label: t(`indexing.generationStatus.${status}`), type: GENERATION_TYPES[status] }
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
    ElMessage.success(t('indexing.outbox.requeued'))
    await refresh()
  } finally {
    retrying.value = null
  }
}

async function retryAllDead(): Promise<void> {
  await ElMessageBox.confirm(
    t('indexing.outbox.retryDeadConfirm', { count: stats.value.dead }),
    t('indexing.outbox.retryDeadTitle'),
    { type: 'warning' },
  )
  const { count } = await retryDeadEvents()
  ElMessage.success(t('indexing.outbox.requeuedCount', { count }))
  await refresh()
}

// ---- generations --------------------------------------------------------------

const generations = ref<IndexGeneration[]>([])

async function loadGenerations(): Promise<void> {
  generations.value = await listGenerations()
}

async function onReloadSynonyms(): Promise<void> {
  await reloadSynonyms()
  ElMessage.success(t('indexing.generations.synonymsReloaded'))
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
    ElMessage.success(t('indexing.consistency.repairSubmitted'))
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
          <span>{{ t('indexing.outbox.title') }}</span>
          <div>
            <el-button :disabled="!stats.dead" type="danger" plain @click="retryAllDead">
              {{ t('indexing.outbox.retryAllDead') }}
            </el-button>
            <el-button @click="refresh">{{ t('common.refresh') }}</el-button>
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
        <el-form-item :label="t('common.status')">
          <el-select
            v-model="filters.status"
            clearable
            :placeholder="t('common.all')"
            style="width: 120px"
          >
            <el-option
              v-for="(meta, key) in STATUS_META"
              :key="key"
              :label="meta.label"
              :value="key"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('indexing.outbox.eventType')">
          <el-input
            v-model="filters.event_type"
            :placeholder="t('indexing.outbox.eventTypePlaceholder')"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">{{
            t('indexing.outbox.query')
          }}</el-button>
        </el-form-item>
      </el-form>

      <el-table
        v-loading="loading"
        :data="events"
        row-key="id"
        :empty-text="t('indexing.outbox.empty')"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="detail">
              <el-descriptions :column="2" size="small" border>
                <el-descriptions-item :label="t('indexing.outbox.eventId')">{{
                  row.id
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('indexing.outbox.processedAt')">
                  {{ formatDateTime(row.processed_at) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('indexing.outbox.lockedUntil')">
                  {{ formatDateTime(row.locked_until) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('indexing.outbox.nextAttempt')">
                  {{ formatDateTime(row.next_attempt_at) }}
                </el-descriptions-item>
                <el-descriptions-item label="Payload" :span="2">
                  <code class="mono">{{ JSON.stringify(row.payload) }}</code>
                </el-descriptions-item>
                <el-descriptions-item :label="t('indexing.outbox.error')" :span="2">
                  <span class="error">{{ row.last_error ?? '—' }}</span>
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.createdAt')" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column
          prop="event_type"
          :label="t('indexing.outbox.eventType')"
          min-width="180"
        />
        <el-table-column :label="t('indexing.outbox.aggregate')" min-width="220">
          <template #default="{ row }">
            {{ row.aggregate_type }} / <span class="mono">{{ row.aggregate_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="90">
          <template #default="{ row }">
            <el-tag :type="STATUS_META[row.status as OutboxStatus].type" size="small">
              {{ STATUS_META[row.status as OutboxStatus].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="retry_count" :label="t('indexing.outbox.retryCount')" width="90" />
        <el-table-column
          :label="t('indexing.outbox.lastError')"
          min-width="200"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ row.last_error ?? '' }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="90" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'dead' || row.status === 'pending'"
              link
              type="primary"
              :loading="retrying === row.id"
              @click="retry(row as OutboxEvent)"
            >
              {{ t('indexing.outbox.retry') }}
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
          <span>{{ t('indexing.consistency.title') }}</span>
        </div>
      </template>
      <el-form :inline="true" @submit.prevent="check">
        <el-form-item :label="t('indexing.consistency.kb')">
          <el-select
            v-model="selectedKb"
            filterable
            remote
            :remote-method="searchKbs"
            :loading="kbLoading"
            :placeholder="t('indexing.consistency.kbPlaceholder')"
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
            {{ t('indexing.consistency.check') }}
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
            {{
              report.consistent
                ? t('indexing.consistency.reportConsistent', {
                    kb: kbName(report.kb_id),
                    generation: report.generation,
                  })
                : t('indexing.consistency.reportInconsistent', {
                    kb: kbName(report.kb_id),
                    generation: report.generation,
                    count: report.reindex_documents.length,
                  })
            }}
          </template>
          <div>
            {{
              t('indexing.consistency.reportMeta', {
                time: formatDateTime(report.checked_at),
                count: report.pg_count,
              })
            }}
            <span v-if="report.skipped_documents">
              {{ t('indexing.consistency.skipped', { count: report.skipped_documents }) }}
            </span>
          </div>
        </el-alert>

        <el-table :data="diffRows" size="small">
          <el-table-column prop="name" :label="t('indexing.consistency.index')" width="120" />
          <el-table-column prop="count" :label="t('indexing.consistency.count')" width="100" />
          <el-table-column
            prop="missing_count"
            :label="t('indexing.consistency.missing')"
            width="100"
          />
          <el-table-column
            prop="extra_count"
            :label="t('indexing.consistency.extra')"
            width="100"
          />
          <el-table-column :label="t('indexing.consistency.missingSamples')" min-width="200">
            <template #default="{ row }">
              <code v-for="id in row.missing" :key="id" class="mono id">{{ id }}</code>
            </template>
          </el-table-column>
          <el-table-column :label="t('indexing.consistency.extraSamples')" min-width="200">
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
            {{ t('indexing.consistency.repair') }}
          </el-button>
        </div>
      </template>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>{{ t('indexing.generations.title') }}</span>
          <div>
            <el-button v-if="isPlatformAdmin" @click="onReloadSynonyms">{{
              t('indexing.generations.reloadSynonyms')
            }}</el-button>
            <el-button @click="loadGenerations">{{ t('common.refresh') }}</el-button>
          </div>
        </div>
      </template>
      <el-table :data="generations" row-key="version" :empty-text="t('indexing.generations.empty')">
        <el-table-column :label="t('indexing.generations.version')" width="80">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="100">
          <template #default="{ row }">
            <el-tag :type="generationMeta(row.status as GenerationStatus).type" size="small">
              {{ generationMeta(row.status as GenerationStatus).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="qdrant_collection" label="Qdrant collection" min-width="150" />
        <el-table-column prop="opensearch_index" label="OpenSearch index" min-width="150" />
        <el-table-column label="Embedding" min-width="180">
          <template #default="{ row }">{{
            t('indexing.generations.embeddingValue', {
              model: row.embedding_model,
              dim: row.embedding_dim,
            })
          }}</template>
        </el-table-column>
        <el-table-column :label="t('common.createdAt')" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column :label="t('indexing.generations.activatedAt')" width="170">
          <template #default="{ row }">{{ formatDateTime(row.activated_at) }}</template>
        </el-table-column>
        <el-table-column
          :label="t('indexing.generations.error')"
          min-width="160"
          show-overflow-tooltip
        >
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
