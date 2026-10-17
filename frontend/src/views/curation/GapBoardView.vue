<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getGapStats, listGapClusters, listGaps, runGapClustering } from '@/api/curation'
import { listKnowledgeBases } from '@/api/knowledge'
import type {
  Gap,
  GapCluster,
  GapSort,
  GapStats,
  GapStatus,
  GapType,
  KnowledgeBase,
} from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { GAP_STATUS_META, GAP_TYPE_META, metaOf } from '@/utils/curation'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

const stats = ref<GapStats | null>(null)
const activeTab = ref<'gaps' | 'clusters'>('gaps')

// ---- gaps -----------------------------------------------------------------------

const filters = reactive({
  status: ['open', 'in_review'] as GapStatus[],
  gap_type: '' as GapType | '',
  kb_id: '',
  keyword: '',
  sort: 'frequency' as GapSort,
  cluster_id: '',
  mine: false,
})
const pager = reactive({ page: 1, size: 20 })
const gaps = ref<Gap[]>([])
const total = ref(0)
const loading = ref(false)
const clustering = ref(false)

const kbOptions = ref<KnowledgeBase[]>([])
const clusterFilterLabel = ref('')

const sourceCards = computed(() =>
  (Object.keys(GAP_TYPE_META) as GapType[]).map((type) => ({
    type,
    label: GAP_TYPE_META[type].label,
    count: stats.value?.by_source[type] ?? 0,
  })),
)

async function loadStats(): Promise<void> {
  stats.value = await getGapStats()
}

async function loadGaps(): Promise<void> {
  loading.value = true
  try {
    const page = await listGaps({
      status: filters.status.length ? filters.status : undefined,
      gap_type: filters.gap_type || undefined,
      kb_id: filters.kb_id || undefined,
      keyword: filters.keyword.trim() || undefined,
      cluster_id: filters.cluster_id || undefined,
      assignee_id: filters.mine ? auth.profile?.id : undefined,
      sort: filters.sort,
      ...pager,
    })
    gaps.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function search(): void {
  pager.page = 1
  void loadGaps()
}

function filterBySource(type: GapType): void {
  filters.gap_type = filters.gap_type === type ? '' : type
  search()
}

function clearCluster(): void {
  filters.cluster_id = ''
  clusterFilterLabel.value = ''
  search()
}

async function runClustering(): Promise<void> {
  clustering.value = true
  try {
    const r = await runGapClustering()
    ElMessage.success(
      t('curation.gapBoard.clusteringResult', {
        processed: r.processed,
        clustered: r.clustered,
        created: r.new_clusters,
        folded: r.folded,
      }),
    )
    await Promise.all([loadStats(), loadGaps(), loadClusters()])
  } finally {
    clustering.value = false
  }
}

function openGap(gap: Gap): void {
  void router.push({ name: 'curation-gap', params: { gapId: gap.id } })
}

// ---- clusters -------------------------------------------------------------------

const clusterPager = reactive({ page: 1, size: 20 })
const clusters = ref<GapCluster[]>([])
const clusterTotal = ref(0)
const clusterLoading = ref(false)
const openOnly = ref(true)

async function loadClusters(): Promise<void> {
  clusterLoading.value = true
  try {
    const page = await listGapClusters({ ...clusterPager, open_only: openOnly.value })
    clusters.value = page.items
    clusterTotal.value = page.total
  } finally {
    clusterLoading.value = false
  }
}

function showCluster(cluster: GapCluster): void {
  filters.cluster_id = cluster.id
  filters.status = []
  clusterFilterLabel.value = cluster.representative_query
  activeTab.value = 'gaps'
  search()
}

function kbName(id: string | null): string {
  if (!id) return '-'
  return kbOptions.value.find((k) => k.id === id)?.name ?? id.slice(0, 8)
}

onMounted(async () => {
  void loadStats()
  void loadGaps()
  void loadClusters()
  kbOptions.value = (await listKnowledgeBases({ page: 1, size: 100 })).items
})
</script>

<template>
  <div class="gap-board">
    <div class="gap-board__cards">
      <el-card shadow="never" class="stat-card">
        <div class="stat-card__value">{{ stats?.by_status.open ?? 0 }}</div>
        <div class="stat-card__label">{{ t('curation.gapBoard.statOpen') }}</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-card__value">{{ stats?.by_status.in_review ?? 0 }}</div>
        <div class="stat-card__label">{{ t('curation.gapBoard.statInReview') }}</div>
      </el-card>
      <el-card shadow="never" class="stat-card">
        <div class="stat-card__value">{{ stats?.clusters_open ?? 0 }}</div>
        <div class="stat-card__label">{{ t('curation.gapBoard.statClusters') }}</div>
      </el-card>
      <el-card
        v-for="card in sourceCards"
        :key="card.type"
        shadow="never"
        class="stat-card stat-card--clickable"
        :class="{ 'stat-card--active': filters.gap_type === card.type }"
        @click="filterBySource(card.type)"
      >
        <div class="stat-card__value">{{ card.count }}</div>
        <div class="stat-card__label">
          {{ t('curation.gapBoard.sourceCount', { label: card.label }) }}
        </div>
      </el-card>
    </div>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane :label="t('curation.gapBoard.tabGaps')" name="gaps">
          <el-form inline class="gap-board__filters" @submit.prevent="search">
            <el-form-item :label="t('common.status')">
              <el-select
                v-model="filters.status"
                multiple
                collapse-tags
                clearable
                :placeholder="t('common.all')"
                style="width: 200px"
                @change="search"
              >
                <el-option
                  v-for="(meta, key) in GAP_STATUS_META"
                  :key="key"
                  :label="meta.label"
                  :value="key"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('curation.field.source')">
              <el-select
                v-model="filters.gap_type"
                clearable
                :placeholder="t('common.all')"
                style="width: 130px"
                @change="search"
              >
                <el-option
                  v-for="(meta, key) in GAP_TYPE_META"
                  :key="key"
                  :label="meta.label"
                  :value="key"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('curation.field.kb')">
              <el-select
                v-model="filters.kb_id"
                clearable
                filterable
                :placeholder="t('common.all')"
                style="width: 180px"
                @change="search"
              >
                <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('curation.gapBoard.sort')">
              <el-radio-group v-model="filters.sort" @change="search">
                <el-radio-button value="frequency">{{
                  t('curation.gapBoard.byFrequency')
                }}</el-radio-button>
                <el-radio-button value="recent">{{
                  t('curation.gapBoard.byRecent')
                }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-input
                v-model="filters.keyword"
                :placeholder="t('curation.gapBoard.keywordPlaceholder')"
                clearable
                style="width: 200px"
                @clear="search"
              />
            </el-form-item>
            <el-form-item>
              <el-checkbox v-model="filters.mine" @change="search">{{
                t('curation.gapBoard.mine')
              }}</el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit">{{
                t('curation.field.query')
              }}</el-button>
              <el-button :loading="clustering" @click="runClustering">{{
                t('curation.gapBoard.runClustering')
              }}</el-button>
            </el-form-item>
          </el-form>

          <el-alert
            v-if="filters.cluster_id"
            type="info"
            :closable="true"
            show-icon
            class="gap-board__cluster-alert"
            @close="clearCluster"
          >
            {{ t('curation.gapBoard.viewingCluster', { label: clusterFilterLabel }) }}
          </el-alert>

          <el-table
            v-loading="loading"
            :data="gaps"
            row-key="id"
            data-test="gap-table"
            @row-click="openGap"
          >
            <el-table-column :label="t('curation.gapBoard.colQuestion')" min-width="280">
              <template #default="{ row }">
                <div class="gap-board__question">{{ row.rewritten_query || row.query }}</div>
                <div v-if="row.rewritten_query && row.rewritten_query !== row.query" class="muted">
                  {{ t('curation.gapBoard.originalQuery', { query: row.query }) }}
                </div>
              </template>
            </el-table-column>
            <el-table-column :label="t('curation.field.source')" width="100">
              <template #default="{ row }">
                <el-tag :type="metaOf(GAP_TYPE_META, row.gap_type).type" size="small">
                  {{ metaOf(GAP_TYPE_META, row.gap_type).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              :label="t('curation.gapBoard.colFrequency')"
              width="110"
              align="center"
            >
              <template #default="{ row }">
                <strong>{{ row.occurrences }}</strong>
                <span v-if="row.cluster_occurrences && row.cluster_occurrences > row.occurrences">
                  {{ t('curation.gapBoard.clusterFrequency', { count: row.cluster_occurrences }) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column :label="t('curation.field.kb')" width="140">
              <template #default="{ row }">{{ row.kb_name || kbName(row.kb_id) }}</template>
            </el-table-column>
            <el-table-column :label="t('common.status')" width="90">
              <template #default="{ row }">
                <el-tag :type="metaOf(GAP_STATUS_META, row.status).type" size="small">
                  {{ metaOf(GAP_STATUS_META, row.status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('curation.field.assignee')" width="110">
              <template #default="{ row }">{{ row.assignee?.name ?? '-' }}</template>
            </el-table-column>
            <el-table-column :label="t('curation.field.lastSeen')" width="170">
              <template #default="{ row }">{{ formatDateTime(row.last_seen_at) }}</template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="pager.page"
            v-model:page-size="pager.size"
            :total="total"
            layout="total, sizes, prev, pager, next"
            class="pager"
            @current-change="loadGaps"
            @size-change="search"
          />
        </el-tab-pane>

        <el-tab-pane :label="t('curation.gapBoard.tabClusters')" name="clusters">
          <div class="gap-board__filters">
            <el-checkbox
              v-model="openOnly"
              @change="
                () => {
                  clusterPager.page = 1
                  void loadClusters()
                }
              "
            >
              {{ t('curation.gapBoard.openOnly') }}
            </el-checkbox>
          </div>
          <el-table
            v-loading="clusterLoading"
            :data="clusters"
            row-key="id"
            @row-click="showCluster"
          >
            <el-table-column
              :label="t('curation.gapBoard.representative')"
              prop="representative_query"
              min-width="300"
            />
            <el-table-column
              :label="t('curation.gapBoard.gapCount')"
              prop="gap_count"
              width="90"
              align="center"
            />
            <el-table-column
              :label="t('curation.gapBoard.totalOccurrences')"
              prop="occurrences"
              width="90"
              align="center"
            />
            <el-table-column
              :label="t('curation.gapBoard.openCount')"
              prop="open_count"
              width="90"
              align="center"
            />
            <el-table-column :label="t('curation.gapBoard.sourceDistribution')" min-width="200">
              <template #default="{ row }">
                <el-tag
                  v-for="(count, type) in row.sources"
                  :key="type"
                  size="small"
                  :type="metaOf(GAP_TYPE_META, String(type)).type"
                  class="gap-board__source-tag"
                >
                  {{ metaOf(GAP_TYPE_META, String(type)).label }} {{ count }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('curation.field.kb')" width="140">
              <template #default="{ row }">{{ kbName(row.kb_id) }}</template>
            </el-table-column>
            <el-table-column :label="t('curation.field.lastSeen')" width="170">
              <template #default="{ row }">{{ formatDateTime(row.last_seen_at) }}</template>
            </el-table-column>
          </el-table>
          <el-pagination
            v-model:current-page="clusterPager.page"
            v-model:page-size="clusterPager.size"
            :total="clusterTotal"
            layout="total, prev, pager, next"
            class="pager"
            @current-change="loadClusters"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.gap-board {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.gap-board__cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.stat-card__value {
  font-size: 24px;
  font-weight: 600;
}

.stat-card__label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.stat-card--clickable {
  cursor: pointer;
}

.stat-card--active {
  border-color: var(--el-color-primary);
}

.gap-board__filters {
  margin-bottom: 8px;
}

.gap-board__cluster-alert {
  margin-bottom: 12px;
}

.gap-board__question {
  font-weight: 500;
}

.gap-board__source-tag {
  margin-right: 4px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
