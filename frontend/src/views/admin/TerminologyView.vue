<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import type { EChartsCoreOption } from 'echarts/core'
import {
  addTerminologyAlias,
  createTerminologyEntity,
  deleteTerminologyAlias,
  deleteTerminologyEntity,
  getTerminologyNeighborhood,
  listTerminologyEntities,
  syncTerminologySynonyms,
  updateTerminologyEntity,
} from '@/api/terminology'
import type { TerminologyEntity, TerminologyNeighborhood } from '@/api/types'
import EChart from '@/components/charts/EChart.vue'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

const ontologyVisible = ref(false)
const syncingSynonyms = ref(false)

const { t } = useI18n()

async function syncSynonyms(): Promise<void> {
  syncingSynonyms.value = true
  try {
    const result = await syncTerminologySynonyms(true)
    ElMessage.success(
      t('terminology.syncSynonymsOk', {
        lines: result.lines,
        reload: result.reloaded ? t('terminology.syncSynonymsReload') : '',
      }),
    )
  } catch {
    ElMessage.error(t('terminology.syncSynonymsFailed'))
  } finally {
    syncingSynonyms.value = false
  }
}

const ENTITY_TYPES = ['device', 'process', 'defect', 'policy', 'it_term', 'other'] as const
const STATUSES = ['active', 'disabled'] as const

const filters = reactive({ q: '', entity_type: '', status: '' })
const pager = reactive({ page: 1, size: 20 })
const items = ref<TerminologyEntity[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listTerminologyEntities({
      page: pager.page,
      size: pager.size,
      q: filters.q.trim() || undefined,
      entity_type: filters.entity_type || undefined,
      status: filters.status || undefined,
    })
    items.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function search(): void {
  pager.page = 1
  void load()
}

const dialogVisible = ref(false)
const editing = ref<TerminologyEntity | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({
  canonical_name: '',
  entity_type: 'it_term',
  description: '',
  status: 'active',
  aliasesText: '',
})
const saving = ref(false)
const rules = computed<FormRules>(() => ({
  canonical_name: [
    { required: true, message: t('terminology.nameRequired'), trigger: 'blur' },
  ],
}))

function openDialog(entity: TerminologyEntity | null): void {
  editing.value = entity
  form.canonical_name = entity?.canonical_name ?? ''
  form.entity_type = entity?.entity_type ?? 'it_term'
  form.description = entity?.description ?? ''
  form.status = entity?.status ?? 'active'
  form.aliasesText = ''
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

function parseAliases(text: string): string[] {
  return text
    .split(/[,，\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    if (editing.value) {
      await updateTerminologyEntity(editing.value.id, {
        canonical_name: form.canonical_name.trim(),
        entity_type: form.entity_type,
        description: form.description.trim() || null,
        status: form.status,
      })
    } else {
      await createTerminologyEntity({
        canonical_name: form.canonical_name.trim(),
        entity_type: form.entity_type,
        description: form.description.trim() || null,
        status: form.status,
        aliases: parseAliases(form.aliasesText),
      })
    }
    ElMessage.success(t('common.saved'))
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(entity: TerminologyEntity): Promise<void> {
  await ElMessageBox.confirm(
    t('terminology.deleteConfirm', { name: entity.canonical_name }),
    t('terminology.deleteTitle'),
    { type: 'warning' },
  )
  await deleteTerminologyEntity(entity.id)
  ElMessage.success(t('common.deleted'))
  await load()
}

const aliasDraft = reactive<Record<string, string>>({})

async function addAlias(entity: TerminologyEntity): Promise<void> {
  const alias = (aliasDraft[entity.id] || '').trim()
  if (!alias) return
  await addTerminologyAlias(entity.id, { alias })
  aliasDraft[entity.id] = ''
  ElMessage.success(t('common.saved'))
  await load()
}

async function removeAlias(_entity: TerminologyEntity, aliasId: string, alias: string): Promise<void> {
  await ElMessageBox.confirm(
    t('terminology.deleteAliasConfirm', { alias }),
    t('terminology.deleteTitle'),
    { type: 'warning' },
  )
  await deleteTerminologyAlias(aliasId)
  ElMessage.success(t('common.deleted'))
  await load()
}

function typeLabel(value: string): string {
  const key = `terminology.types.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

function statusLabel(value: string): string {
  const key = `terminology.statuses.${value}`
  const translated = t(key)
  return translated === key ? value : translated
}

const graphVisible = ref(false)
const graphLoading = ref(false)
const neighborhood = ref<TerminologyNeighborhood | null>(null)

const KIND_COLOR: Record<string, string> = {
  term: '#3b82f6',
  mirror: '#10b981',
  ko: '#f59e0b',
}

const graphOption = computed<EChartsCoreOption>(() => {
  const data = neighborhood.value
  if (!data) return {}
  const categories = [
    { name: t('terminology.graph.kindTerm') },
    { name: t('terminology.graph.kindMirror') },
    { name: t('terminology.graph.kindKo') },
  ]
  const kindIndex: Record<string, number> = { term: 0, mirror: 1, ko: 2 }
  return {
    tooltip: {},
    // Legend lives in `.graph-legend` (dots match node colors); skip ECharts blocks.
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        categories,
        label: { show: true, position: 'right', fontSize: 12 },
        force: { repulsion: 260, edgeLength: [80, 160], gravity: 0.08 },
        data: data.nodes.map((n) => ({
          id: n.id,
          name: n.label,
          category: kindIndex[n.kind] ?? 0,
          itemStyle: { color: KIND_COLOR[n.kind] ?? '#64748b' },
          symbolSize: n.kind === 'term' ? 46 : n.kind === 'ko' ? 30 : 24,
        })),
        links: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          label: { show: true, formatter: e.relation, fontSize: 10 },
        })),
        lineStyle: { color: 'source', curveness: 0.1 },
      },
    ],
  }
})

async function openGraph(entity: TerminologyEntity): Promise<void> {
  graphVisible.value = true
  graphLoading.value = true
  neighborhood.value = null
  try {
    neighborhood.value = await getTerminologyNeighborhood(entity.id)
  } finally {
    graphLoading.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <div>
          <div>{{ t('terminology.title') }}</div>
          <div class="hint">{{ t('terminology.hint') }}</div>
        </div>
        <div class="header-actions">
          <el-button link type="primary" :title="t('terminology.ontologyHint')" @click="ontologyVisible = true">
            {{ t('terminology.ontologyLink') }}
          </el-button>
          <el-button
            :loading="syncingSynonyms"
            :title="t('terminology.syncSynonymsHint')"
            @click="syncSynonyms"
          >
            {{ t('terminology.syncSynonyms') }}
          </el-button>
          <el-button type="primary" @click="openDialog(null)">{{
            t('terminology.create')
          }}</el-button>
        </div>
      </div>
    </template>

    <div class="filters">
      <el-input
        v-model="filters.q"
        clearable
        :placeholder="t('terminology.canonicalName')"
        style="width: 220px"
        @keyup.enter="search"
      />
      <el-select
        v-model="filters.entity_type"
        clearable
        :placeholder="t('terminology.entityType')"
        style="width: 160px"
      >
        <el-option
          v-for="tp in ENTITY_TYPES"
          :key="tp"
          :label="typeLabel(tp)"
          :value="tp"
        />
      </el-select>
      <el-select
        v-model="filters.status"
        clearable
        :placeholder="t('terminology.status')"
        style="width: 140px"
      >
        <el-option
          v-for="st in STATUSES"
          :key="st"
          :label="statusLabel(st)"
          :value="st"
        />
      </el-select>
      <el-button type="primary" @click="search">{{ t('common.search') }}</el-button>
    </div>

    <el-table v-loading="loading" :data="items" row-key="id">
      <template #empty>
        <EmptyState
          :description="t('terminology.empty')"
          :action-label="t('terminology.create')"
          @action="openDialog(null)"
        />
      </template>
      <el-table-column :label="t('terminology.canonicalName')" min-width="160" prop="canonical_name" />
      <el-table-column :label="t('terminology.entityType')" width="120">
        <template #default="{ row }">{{ typeLabel(row.entity_type) }}</template>
      </el-table-column>
      <el-table-column :label="t('terminology.status')" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ statusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('terminology.aliases')" min-width="280">
        <template #default="{ row }">
          <div class="aliases">
            <el-tag
              v-for="a in row.aliases"
              :key="a.id"
              class="alias-tag"
              closable
              size="small"
              @close="removeAlias(row as TerminologyEntity, a.id, a.alias)"
            >
              {{ a.alias }}
            </el-tag>
            <div class="alias-add">
              <el-input
                v-model="aliasDraft[(row as TerminologyEntity).id]"
                size="small"
                :placeholder="t('terminology.aliasPlaceholder')"
                @keyup.enter="addAlias(row as TerminologyEntity)"
              />
              <el-button size="small" @click="addAlias(row as TerminologyEntity)">{{
                t('terminology.addAlias')
              }}</el-button>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.updatedAt')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openGraph(row as TerminologyEntity)">{{
            t('terminology.graph.preview')
          }}</el-button>
          <el-button link type="primary" @click="openDialog(row as TerminologyEntity)">{{
            t('common.edit')
          }}</el-button>
          <el-button link type="danger" @click="remove(row as TerminologyEntity)">{{
            t('common.delete')
          }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="pager.page"
        v-model:page-size="pager.size"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[10, 20, 50]"
        @current-change="load"
        @size-change="
          () => {
            pager.page = 1
            load()
          }
        "
      />
    </div>
  </el-card>

  <el-dialog
    v-model="dialogVisible"
    :title="editing ? t('terminology.edit') : t('terminology.create')"
    width="520px"
    destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item :label="t('terminology.canonicalName')" prop="canonical_name">
        <el-input v-model="form.canonical_name" maxlength="256" />
      </el-form-item>
      <el-form-item :label="t('terminology.entityType')">
        <el-select v-model="form.entity_type" style="width: 100%">
          <el-option
            v-for="tp in ENTITY_TYPES"
            :key="tp"
            :label="typeLabel(tp)"
            :value="tp"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('terminology.status')">
        <el-select v-model="form.status" style="width: 100%">
          <el-option
            v-for="st in STATUSES"
            :key="st"
            :label="statusLabel(st)"
            :value="st"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('terminology.description')">
        <el-input v-model="form.description" type="textarea" :rows="2" maxlength="4000" />
      </el-form-item>
      <el-form-item v-if="!editing" :label="t('terminology.aliases')">
        <el-input
          v-model="form.aliasesText"
          type="textarea"
          :rows="3"
          :placeholder="t('terminology.aliasesHint')"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submit">{{
        t('common.save')
      }}</el-button>
    </template>
  </el-dialog>

  <el-drawer
    v-model="graphVisible"
    class="terminology-graph-drawer"
    :title="
      neighborhood
        ? t('terminology.graph.title', { name: neighborhood.entity.canonical_name })
        : t('terminology.graph.preview')
    "
    size="780px"
    destroy-on-close
  >
    <div v-loading="graphLoading" class="graph-pane">
      <p class="graph-hint">{{ t('terminology.graph.hint') }}</p>
      <EChart v-if="neighborhood?.nodes.length" :option="graphOption" height="520px" />
      <el-empty v-else-if="!graphLoading" :description="t('terminology.graph.empty')" />
      <ul v-if="neighborhood?.nodes.length" class="graph-legend" aria-label="legend">
        <li><span class="dot term" />{{ t('terminology.graph.kindTerm') }}</li>
        <li><span class="dot mirror" />{{ t('terminology.graph.kindMirror') }}</li>
        <li><span class="dot ko" />{{ t('terminology.graph.kindKo') }}</li>
      </ul>
    </div>
  </el-drawer>

  <el-dialog v-model="ontologyVisible" :title="t('terminology.ontologyTitle')" width="560px">
    <p class="ontology-body">{{ t('terminology.ontologyBody') }}</p>
    <template #footer>
      <el-button type="primary" @click="ontologyVisible = false">{{ t('common.close') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.ontology-body {
  margin: 0;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
}
.hint {
  margin-top: 4px;
  font-size: 12px;
  font-weight: normal;
  color: var(--el-text-color-secondary);
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.graph-pane {
  min-height: 200px;
}
.graph-hint {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.graph-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.graph-legend .dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: -1px;
}
.graph-legend .dot.term {
  background: #3b82f6;
}
.graph-legend .dot.mirror {
  background: #10b981;
}
.graph-legend .dot.ko {
  background: #f59e0b;
}

.aliases {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.alias-tag {
  margin: 0;
}
.alias-add {
  display: flex;
  gap: 6px;
  width: 100%;
  margin-top: 4px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>

<!-- Drawer teleports to body; keep wide on desktop, full-bleed on narrow viewports. -->
<style>
@media (max-width: 900px) {
  .terminology-graph-drawer.el-drawer {
    width: 100% !important;
  }
}
</style>
