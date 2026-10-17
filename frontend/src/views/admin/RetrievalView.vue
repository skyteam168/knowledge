<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { HttpError } from '@/api/http'
import {
  activateRetrievalProfile,
  createRetrievalProfile,
  deleteRetrievalProfile,
  getDefaultRetrievalConfig,
  getRetrievalTrace,
  listRetrievalProfiles,
  listRetrievalTraces,
  updateRetrievalProfile,
} from '@/api/search'
import type {
  RetrievalConfig,
  RetrievalProfile,
  RetrievalTrace,
  RetrievalTraceSummary,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const { t } = useI18n()

const tab = ref('profiles')

// ---- profiles ---------------------------------------------------------------------

const profiles = ref<RetrievalProfile[]>([])
const loadingProfiles = ref(false)

async function loadProfiles(): Promise<void> {
  loadingProfiles.value = true
  try {
    profiles.value = await listRetrievalProfiles()
  } finally {
    loadingProfiles.value = false
  }
}

function summary(c: RetrievalConfig): string {
  const routes = [
    c.dense.enabled ? `Dense top${c.dense.top_k}` : null,
    c.sparse.enabled ? `BM25 top${c.sparse.top_k}` : null,
  ].filter(Boolean)
  const weights = Object.entries(c.fusion.weights)
    .map(([r, w]) => `${r}×${w}`)
    .join(' ')
  const rerank = c.rerank.enabled ? `Rerank top${c.rerank.top_n}` : t('retrieval.profiles.noRerank')
  return t('retrieval.profiles.summary', {
    routes: routes.join(' + '),
    k: c.fusion.k,
    weights,
    rerank,
    topK: c.top_k,
  })
}

const editor = reactive({
  visible: false,
  saving: false,
  id: null as string | null,
  name: '',
  description: '',
  json: '',
  error: '',
})

async function openEditor(profile?: RetrievalProfile, copy = false): Promise<void> {
  const config = profile ? profile.config : await getDefaultRetrievalConfig()
  editor.id = profile && !copy ? profile.id : null
  editor.name = profile && !copy ? profile.name : profile ? `${profile.name}-copy` : ''
  editor.description = (profile?.description ?? '') || ''
  editor.json = JSON.stringify(config, null, 2)
  editor.error = ''
  editor.visible = true
}

async function resetJson(): Promise<void> {
  editor.json = JSON.stringify(await getDefaultRetrievalConfig(), null, 2)
}

async function saveEditor(): Promise<void> {
  let config: RetrievalConfig
  try {
    config = JSON.parse(editor.json) as RetrievalConfig
  } catch (e) {
    editor.error = t('retrieval.editor.jsonError', { message: (e as Error).message })
    return
  }
  editor.saving = true
  editor.error = ''
  try {
    const body = { name: editor.name.trim(), description: editor.description || null, config }
    if (editor.id) await updateRetrievalProfile(editor.id, body)
    else await createRetrievalProfile(body)
    ElMessage.success(t('common.saved'))
    editor.visible = false
    await loadProfiles()
  } catch (e) {
    if (e instanceof HttpError && e.status === 422) {
      editor.error = JSON.stringify(e.detail, null, 2)
    }
  } finally {
    editor.saving = false
  }
}

async function activate(profile: RetrievalProfile): Promise<void> {
  await activateRetrievalProfile(profile.id ?? 'builtin')
  ElMessage.success(t('retrieval.profiles.activated', { name: profile.name }))
  await loadProfiles()
}

async function remove(profile: RetrievalProfile): Promise<void> {
  if (!profile.id) return
  await ElMessageBox.confirm(
    t('retrieval.profiles.deleteConfirm', { name: profile.name }),
    t('common.delete'),
    { type: 'warning' },
  )
  await deleteRetrievalProfile(profile.id)
  ElMessage.success(t('common.deleted'))
  await loadProfiles()
}

// ---- traces -----------------------------------------------------------------------

const traceFilters = reactive({ keyword: '', degraded_only: false })
const pager = reactive({ page: 1, size: 20 })
const traces = ref<RetrievalTraceSummary[]>([])
const total = ref(0)
const loadingTraces = ref(false)
const detail = ref<RetrievalTrace | null>(null)
const detailVisible = ref(false)

async function loadTraces(): Promise<void> {
  loadingTraces.value = true
  try {
    const page = await listRetrievalTraces({
      keyword: traceFilters.keyword || undefined,
      degraded_only: traceFilters.degraded_only || undefined,
      ...pager,
    })
    traces.value = page.items
    total.value = page.total
  } finally {
    loadingTraces.value = false
  }
}

function searchTraces(): void {
  pager.page = 1
  void loadTraces()
}

async function openTrace(row: RetrievalTraceSummary): Promise<void> {
  detail.value = await getRetrievalTrace(row.id)
  detailVisible.value = true
}

function onTab(name: string | number): void {
  if (name === 'traces' && !traces.value.length) void loadTraces()
}

onMounted(loadProfiles)
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab" @tab-change="onTab">
      <el-tab-pane :label="t('retrieval.profiles.tab')" name="profiles">
        <div class="toolbar">
          <span class="hint">{{ t('retrieval.profiles.hint') }}</span>
          <el-button type="primary" @click="openEditor()">{{
            t('retrieval.profiles.create')
          }}</el-button>
        </div>
        <el-table v-loading="loadingProfiles" :data="profiles" row-key="name">
          <el-table-column :label="t('common.name')" min-width="160">
            <template #default="{ row }">
              <span class="name">{{ row.name }}</span>
              <el-tag v-if="row.builtin" size="small" type="info">{{
                t('retrieval.profiles.builtin')
              }}</el-tag>
              <el-tag v-if="row.is_active" size="small" type="success">{{
                t('retrieval.profiles.active')
              }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column
            prop="description"
            :label="t('retrieval.profiles.note')"
            min-width="160"
            show-overflow-tooltip
          />
          <el-table-column :label="t('retrieval.profiles.params')" min-width="320">
            <template #default="{ row }">
              <span class="summary">{{ summary(row.config) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.updatedAt')" width="170">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="220" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="!row.is_active"
                link
                type="primary"
                @click="activate(row as RetrievalProfile)"
              >
                {{ t('retrieval.profiles.activate') }}
              </el-button>
              <el-button
                v-if="!row.builtin"
                link
                type="primary"
                @click="openEditor(row as RetrievalProfile)"
              >
                {{ t('common.edit') }}
              </el-button>
              <el-button link type="primary" @click="openEditor(row as RetrievalProfile, true)">
                {{ t('common.copy') }}
              </el-button>
              <el-button
                v-if="!row.builtin"
                link
                type="danger"
                :disabled="row.is_active"
                @click="remove(row as RetrievalProfile)"
              >
                {{ t('common.delete') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="t('retrieval.traces.tab')" name="traces">
        <div class="toolbar">
          <el-input
            v-model="traceFilters.keyword"
            :placeholder="t('retrieval.traces.keywordPlaceholder')"
            clearable
            class="keyword"
            @keyup.enter="searchTraces"
            @clear="searchTraces"
          />
          <el-checkbox v-model="traceFilters.degraded_only" @change="searchTraces">
            {{ t('retrieval.traces.degradedOnly') }}
          </el-checkbox>
          <el-button @click="searchTraces">{{ t('retrieval.traces.search') }}</el-button>
        </div>
        <el-table v-loading="loadingTraces" :data="traces" @row-click="openTrace">
          <el-table-column :label="t('retrieval.traces.time')" width="170">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column
            prop="query"
            :label="t('retrieval.traces.query')"
            min-width="200"
            show-overflow-tooltip
          />
          <el-table-column prop="profile_name" :label="t('retrieval.traces.profile')" width="130" />
          <el-table-column prop="result_count" :label="t('retrieval.traces.results')" width="70" />
          <el-table-column :label="t('retrieval.traces.duration')" width="90">
            <template #default="{ row }">{{ row.total_ms }} ms</template>
          </el-table-column>
          <el-table-column :label="t('common.status')" min-width="180">
            <template #default="{ row }">
              <el-tag v-if="row.cache_hit" size="small" type="info">{{
                t('retrieval.traces.cached')
              }}</el-tag>
              <el-tag v-for="d in row.degraded" :key="d" size="small" type="warning">{{
                d
              }}</el-tag>
              <el-tag v-if="row.truncated" size="small">{{
                t('retrieval.traces.truncated')
              }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="pager.page"
          v-model:page-size="pager.size"
          :total="total"
          layout="total, sizes, prev, pager, next"
          class="pager"
          @current-change="loadTraces"
          @size-change="searchTraces"
        />
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="editor.visible"
      :title="editor.id ? t('retrieval.editor.editTitle') : t('retrieval.editor.createTitle')"
      width="720px"
    >
      <el-form label-width="70px">
        <el-form-item :label="t('common.name')" required>
          <el-input v-model="editor.name" maxlength="64" />
        </el-form-item>
        <el-form-item :label="t('retrieval.profiles.note')">
          <el-input v-model="editor.description" maxlength="2000" />
        </el-form-item>
        <el-form-item :label="t('retrieval.editor.config')">
          <el-input v-model="editor.json" type="textarea" :rows="18" class="json-input" />
          <el-button link type="primary" @click="resetJson">{{
            t('retrieval.editor.resetDefault')
          }}</el-button>
        </el-form-item>
      </el-form>
      <pre v-if="editor.error" class="error">{{ editor.error }}</pre>
      <template #footer>
        <el-button @click="editor.visible = false">{{ t('common.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="editor.saving"
          :disabled="!editor.name.trim()"
          @click="saveEditor"
        >
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" :title="t('retrieval.detail.title')" size="50%">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item :label="t('retrieval.detail.query')" :span="2">{{
            detail.query
          }}</el-descriptions-item>
          <el-descriptions-item :label="t('retrieval.detail.normalized')" :span="2">
            {{ detail.normalized_query }}
          </el-descriptions-item>
          <el-descriptions-item :label="t('retrieval.detail.profile')">{{
            detail.profile_name
          }}</el-descriptions-item>
          <el-descriptions-item :label="t('retrieval.detail.generation')">{{
            detail.generation ?? '-'
          }}</el-descriptions-item>
          <el-descriptions-item :label="t('retrieval.detail.user')">{{
            detail.user_id ?? '-'
          }}</el-descriptions-item>
          <el-descriptions-item :label="t('retrieval.detail.duration')"
            >{{ detail.total_ms }} ms</el-descriptions-item
          >
        </el-descriptions>
        <el-collapse :model-value="['stages']" class="raw">
          <el-collapse-item :title="t('retrieval.detail.filters')" name="filters">
            <pre class="json">{{ JSON.stringify(detail.filters, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item :title="t('retrieval.detail.timings')" name="timings">
            <pre class="json">{{ JSON.stringify(detail.timings, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item :title="t('retrieval.detail.stages')" name="stages">
            <pre class="json">{{ JSON.stringify(detail.stages, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item :title="t('retrieval.detail.config')" name="config">
            <pre class="json">{{ JSON.stringify(detail.config, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.hint {
  flex: 1;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.keyword {
  width: 260px;
}
.name {
  margin-right: 6px;
  font-weight: 500;
}
.name + .el-tag {
  margin-right: 4px;
}
.summary {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.json-input :deep(textarea),
.json,
.error {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.json,
.error {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow: auto;
}
.error {
  color: var(--el-color-danger);
  max-height: 200px;
}
.raw {
  margin-top: 16px;
}
</style>
