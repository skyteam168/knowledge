<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Download, Plus } from '@element-plus/icons-vue'
import {
  deleteDirectorySource,
  downloadExcelTemplate,
  listDirectorySources,
  listSyncRuns,
  startDirectorySync,
  updateDirectorySource,
  uploadDirectoryExcel,
} from '@/api/directory'
import type { DirectorySource, SyncMode, SyncRun } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import DirectorySourceEditor from './DirectorySourceEditor.vue'
import {
  DEPT_STAT_KEYS,
  IDENTITY_STAT_KEYS,
  USER_STAT_KEYS,
  sourceLabel,
  statLine,
  statusInfo,
} from './meta'

const { t } = useI18n()
const router = useRouter()
const sources = ref<DirectorySource[]>([])
const runs = ref<SyncRun[]>([])
const runsTotal = ref(0)
const runQuery = reactive({ page: 1, size: 10 })
const loading = ref(false)
const busy = ref<string | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const sourceName = computed(() => new Map(sources.value.map((s) => [s.id, s])))
const usedTypes = computed(() => sources.value.map((s) => s.type))
const hasPrimary = computed(() => sources.value.some((s) => s.is_primary))

async function loadRuns(): Promise<void> {
  const page = await listSyncRuns({ page: runQuery.page, size: runQuery.size })
  runs.value = page.items
  runsTotal.value = page.total
  schedulePoll()
}

async function load(): Promise<void> {
  loading.value = true
  try {
    sources.value = await listDirectorySources()
    await loadRuns()
  } finally {
    loading.value = false
  }
}

function schedulePoll(): void {
  const running = runs.value.some((r) => r.status === 'running')
  if (running && !timer) {
    timer = setInterval(() => {
      void listDirectorySources().then((s) => (sources.value = s))
      void loadRuns()
    }, 3000)
  } else if (!running && timer) {
    clearInterval(timer)
    timer = null
  }
}

const editor = reactive({ visible: false, source: null as DirectorySource | null })

function openCreate(): void {
  editor.source = null
  editor.visible = true
}

function openEdit(source: DirectorySource): void {
  editor.source = source
  editor.visible = true
}

async function sync(source: DirectorySource, mode: SyncMode): Promise<void> {
  if (mode === 'apply') {
    await ElMessageBox.confirm(
      source.is_primary
        ? t('directory.sources.applyPrimaryConfirm', { name: source.name })
        : t('directory.sources.applyIdentityConfirm', { name: source.name }),
      t('directory.sources.applyTitle'),
      { type: 'warning' },
    )
  }
  busy.value = source.id
  try {
    const run = await startDirectorySync(source.id, mode)
    ElMessage.success(
      mode === 'preview'
        ? t('directory.sources.previewStarted')
        : t('directory.sources.syncStarted'),
    )
    runQuery.page = 1
    await loadRuns()
    if (mode === 'preview') watchRun(run.id)
  } finally {
    busy.value = null
  }
}

function watchRun(runId: string): void {
  const check = setInterval(() => {
    const run = runs.value.find((r) => r.id === runId)
    if (run && run.status !== 'running') {
      clearInterval(check)
      if (run.status !== 'failed')
        void router.push({ name: 'admin-directory-run', params: { runId } })
    }
  }, 1000)
  setTimeout(() => clearInterval(check), 10 * 60 * 1000)
}

const fileInput = ref<HTMLInputElement | null>(null)
const upload = reactive({ source: null as DirectorySource | null, mode: 'preview' as SyncMode })

function pickFile(source: DirectorySource, mode: SyncMode): void {
  upload.source = source
  upload.mode = mode
  fileInput.value?.click()
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !upload.source) return
  busy.value = upload.source.id
  try {
    const run = await uploadDirectoryExcel(upload.source.id, file, upload.mode)
    await load()
    void router.push({ name: 'admin-directory-run', params: { runId: run.id } })
  } finally {
    busy.value = null
  }
}

async function toggle(source: DirectorySource): Promise<void> {
  await updateDirectorySource(source.id, { enabled: !source.enabled })
  ElMessage.success(
    source.enabled ? t('directory.sources.disabledMsg') : t('directory.sources.enabledMsg'),
  )
  await load()
}

async function makePrimary(source: DirectorySource): Promise<void> {
  await ElMessageBox.confirm(
    t('directory.sources.primaryConfirm', { name: source.name }),
    t('directory.sources.makePrimary'),
    { type: 'warning' },
  )
  await updateDirectorySource(source.id, { is_primary: true })
  ElMessage.success(t('directory.sources.primarySet'))
  await load()
}

async function remove(source: DirectorySource): Promise<void> {
  await ElMessageBox.confirm(
    t('directory.sources.deleteConfirm', { name: source.name }),
    t('directory.sources.deleteTitle'),
    {
      type: 'warning',
      confirmButtonText: t('common.delete'),
      confirmButtonClass: 'el-button--danger',
    },
  )
  await deleteDirectorySource(source.id)
  ElMessage.success(t('common.deleted'))
  await load()
}

function onCommand(source: DirectorySource, command: string): void {
  const actions: Record<string, (s: DirectorySource) => Promise<void> | void> = {
    edit: openEdit,
    toggle,
    primary: makePrimary,
    delete: remove,
    upload_apply: (s) => pickFile(s, 'apply'),
    apply: (s) => sync(s, 'apply'),
  }
  void Promise.resolve(actions[command]?.(source)).catch(() => undefined)
}

function runSummary(run: SyncRun): string {
  const s = run.stats.stats
  if (!s) return run.error ?? '—'
  if (s.identities)
    return t('directory.runs.summaryIdentities', {
      stats: statLine(s.identities, IDENTITY_STAT_KEYS),
    })
  return t('directory.runs.summary', {
    departments: statLine(s.departments, DEPT_STAT_KEYS),
    users: statLine(s.users, USER_STAT_KEYS),
  })
}

function openRun(run: SyncRun): void {
  void router.push({ name: 'admin-directory-run', params: { runId: run.id } })
}

let firstActivation = true
onMounted(load)
onActivated(() => {
  if (firstActivation) firstActivation = false
  else void load()
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-header__title">{{ t('directory.sources.title') }}</h2>
        <p class="page-header__desc">{{ t('directory.sources.desc') }}</p>
      </div>
      <div class="actions">
        <el-button :icon="Download" @click="downloadExcelTemplate">
          {{ t('directory.sources.excelTemplate') }}
        </el-button>
        <el-button type="primary" :icon="Plus" data-test="new-source" @click="openCreate">
          {{ t('directory.sources.newSource') }}
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!loading && sources.length && !hasPrimary"
      type="warning"
      show-icon
      :closable="false"
      class="block"
      :title="t('directory.sources.noPrimary')"
    />

    <el-card shadow="never" class="block">
      <template #header>{{ t('directory.sources.card') }}</template>
      <el-table
        v-loading="loading"
        :data="sources"
        :empty-text="t('directory.sources.empty')"
        data-test="source-table"
      >
        <el-table-column :label="t('common.name')" min-width="200">
          <template #default="{ row }">
            <div class="name">
              {{ row.name }}
              <el-tag v-if="row.is_primary" size="small" type="success" effect="dark">{{
                t('directory.sources.primaryTag')
              }}</el-tag>
              <el-tag v-if="!row.enabled" size="small" type="info">{{
                t('directory.sources.disabledTag')
              }}</el-tag>
            </div>
            <div class="muted small">
              {{ sourceLabel((row as DirectorySource).type) }}
              <template v-if="row.login_supported">
                ·
                {{
                  row.login_configured
                    ? t('directory.sources.loginConfigured')
                    : t('directory.sources.loginNotConfigured')
                }}
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.sources.autoSync')" width="120">
          <template #default="{ row }">
            <span class="small">
              {{
                row.type === 'excel'
                  ? t('directory.sources.uploadImport')
                  : row.sync_interval_minutes
                    ? t('directory.sources.everyMinutes', { n: row.sync_interval_minutes })
                    : t('directory.sources.manualOnly')
              }}
            </span>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.sources.lastSync')" width="190">
          <template #default="{ row }">
            <template v-if="row.last_sync_at">
              <el-tag
                v-if="row.last_status"
                size="small"
                :type="statusInfo((row as DirectorySource).last_status!).type"
              >
                {{ statusInfo((row as DirectorySource).last_status!).label }}
              </el-tag>
              <div class="muted small">{{ formatDateTime(row.last_sync_at) }}</div>
            </template>
            <span v-else class="muted small">{{ t('directory.sources.neverSynced') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.sources.nextSync')" width="160">
          <template #default="{ row }">
            <span class="small">{{
              row.next_sync_at ? formatDateTime(row.next_sync_at) : '—'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="230" fixed="right">
          <template #default="{ row }">
            <template v-if="row.type === 'excel'">
              <el-button
                link
                type="primary"
                :loading="busy === row.id"
                data-test="upload-preview"
                @click="pickFile(row as DirectorySource, 'preview')"
              >
                {{ t('directory.sources.uploadPreview') }}
              </el-button>
            </template>
            <template v-else>
              <el-button
                link
                type="primary"
                :loading="busy === row.id"
                :disabled="!row.enabled"
                data-test="preview"
                @click="sync(row as DirectorySource, 'preview')"
              >
                {{ t('directory.sources.preview') }}
              </el-button>
            </template>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onCommand(row as DirectorySource, cmd)"
            >
              <el-button link type="primary">{{ t('directory.sources.more') }}</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="row.type === 'excel'" command="upload_apply">
                    {{ t('directory.sources.uploadApply') }}
                  </el-dropdown-item>
                  <el-dropdown-item v-else command="apply" :disabled="!row.enabled">
                    {{ t('directory.sources.applySync') }}
                  </el-dropdown-item>
                  <el-dropdown-item command="edit">{{
                    t('directory.sources.editConfig')
                  }}</el-dropdown-item>
                  <el-dropdown-item v-if="!row.is_primary" command="primary">{{
                    t('directory.sources.makePrimary')
                  }}</el-dropdown-item>
                  <el-dropdown-item command="toggle">{{
                    row.enabled ? t('directory.sources.disable') : t('directory.sources.enable')
                  }}</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <span class="danger">{{ t('common.delete') }}</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>{{ t('directory.runs.history') }}</template>
      <el-table
        :data="runs"
        :empty-text="t('directory.runs.empty')"
        class="run-table"
        data-test="run-table"
        @row-click="openRun"
      >
        <el-table-column :label="t('directory.runs.time')" width="170">
          <template #default="{ row }">
            <span class="small">{{ formatDateTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.runs.source')" width="140">
          <template #default="{ row }">
            {{ sourceName.get(row.source_id)?.name ?? t('directory.runs.deletedSource') }}
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.runs.type')" width="100">
          <template #default="{ row }">
            {{
              row.mode === 'preview'
                ? t('directory.runs.modePreview')
                : row.forced
                  ? t('directory.runs.modeForced')
                  : t('directory.runs.modeApply')
            }}
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="statusInfo((row as SyncRun).status).type">
              {{ statusInfo((row as SyncRun).status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.runs.result')" min-width="280">
          <template #default="{ row }">
            <span class="small">{{ runSummary(row as SyncRun) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.runs.duration')" width="90" align="right">
          <template #default="{ row }">
            <span class="small">{{
              row.finished_at ? `${(row.duration_ms / 1000).toFixed(1)}s` : '…'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('directory.runs.triggeredBy')" width="120" prop="triggered_by" />
      </el-table>
      <el-pagination
        v-model:current-page="runQuery.page"
        v-model:page-size="runQuery.size"
        class="pager"
        layout="total, prev, pager, next"
        :total="runsTotal"
        @current-change="loadRuns"
      />
    </el-card>

    <input
      ref="fileInput"
      type="file"
      accept=".xlsx"
      hidden
      data-test="excel-file"
      @change="onFile"
    />
    <DirectorySourceEditor
      v-model="editor.visible"
      :source="editor.source"
      :used-types="usedTypes"
      @saved="load"
    />
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}
.page-header__title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
}
.page-header__desc {
  max-width: 760px;
  margin: 0;
  font-size: 13px;
  color: var(--ekb-text-3);
}
.actions {
  display: flex;
  gap: 8px;
}
.block {
  margin-bottom: 16px;
}
.name {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.small {
  font-size: 12px;
}
.danger {
  color: var(--el-color-danger);
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
.run-table :deep(.el-table__row) {
  cursor: pointer;
}
</style>
