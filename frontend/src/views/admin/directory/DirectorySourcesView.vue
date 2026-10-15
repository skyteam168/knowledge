<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
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
  SOURCE_LABEL,
  STATUS_INFO,
  USER_STAT_KEYS,
  statLine,
} from './meta'

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
        ? `将按「${source.name}」更新部门树、人员、部门归属与职务，上游已删除的部门会归档、离职人员会停用。建议先预览。确定直接应用吗？`
        : `将按「${source.name}」为已有用户绑定身份（扫码登录用），不会修改部门和人员。确定应用吗？`,
      '应用同步',
      { type: 'warning' },
    )
  }
  busy.value = source.id
  try {
    const run = await startDirectorySync(source.id, mode)
    ElMessage.success(mode === 'preview' ? '已开始预览，完成后可查看差异' : '已开始同步')
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
  ElMessage.success(source.enabled ? '已停用' : '已启用')
  await load()
}

async function makePrimary(source: DirectorySource): Promise<void> {
  await ElMessageBox.confirm(
    `设为主数据源后，「${source.name}」将接管部门树和人员信息；原主数据源同步的部门和人员改为本地可编辑。`,
    '设为主数据源',
    { type: 'warning' },
  )
  await updateDirectorySource(source.id, { is_primary: true })
  ElMessage.success('已设为主数据源')
  await load()
}

async function remove(source: DirectorySource): Promise<void> {
  await ElMessageBox.confirm(
    `删除「${source.name}」后不再同步；已同步的部门、人员和授权都会保留并改为本地可编辑。`,
    '删除数据源',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await deleteDirectorySource(source.id)
  ElMessage.success('已删除')
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
  if (s.identities) return `身份：${statLine(s.identities, IDENTITY_STAT_KEYS)}`
  return `部门：${statLine(s.departments, DEPT_STAT_KEYS)}；人员：${statLine(s.users, USER_STAT_KEYS)}`
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
        <h2 class="page-header__title">组织同步</h2>
        <p class="page-header__desc">
          从企业微信、钉钉、泛微 OA 或 Excel
          同步部门树、人员、多部门归属与职务。主数据源管理组织架构，
          其他数据源只用于绑定身份（扫码登录）。同步不删除人员，只停用；上游删除的部门归档，原有授权保留。
        </p>
      </div>
      <div class="actions">
        <el-button :icon="Download" @click="downloadExcelTemplate">Excel 模板</el-button>
        <el-button type="primary" :icon="Plus" data-test="new-source" @click="openCreate">
          新增数据源
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!loading && sources.length && !hasPrimary"
      type="warning"
      show-icon
      :closable="false"
      class="block"
      title="还没有主数据源：同步只会绑定身份，不会建立部门和人员。在数据源的「更多」中设为主数据源。"
    />

    <el-card shadow="never" class="block">
      <template #header>数据源</template>
      <el-table
        v-loading="loading"
        :data="sources"
        empty-text="暂无数据源"
        data-test="source-table"
      >
        <el-table-column label="名称" min-width="200">
          <template #default="{ row }">
            <div class="name">
              {{ row.name }}
              <el-tag v-if="row.is_primary" size="small" type="success" effect="dark"
                >主数据源</el-tag
              >
              <el-tag v-if="!row.enabled" size="small" type="info">已停用</el-tag>
            </div>
            <div class="muted small">
              {{ SOURCE_LABEL[(row as DirectorySource).type] }}
              <template v-if="row.login_supported">
                · 扫码登录{{ row.login_configured ? '已配置' : '未配置' }}
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="自动同步" width="120">
          <template #default="{ row }">
            <span class="small">
              {{
                row.type === 'excel'
                  ? '上传导入'
                  : row.sync_interval_minutes
                    ? `每 ${row.sync_interval_minutes} 分钟`
                    : '仅手动'
              }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="上次同步" width="190">
          <template #default="{ row }">
            <template v-if="row.last_sync_at">
              <el-tag
                v-if="row.last_status"
                size="small"
                :type="STATUS_INFO[(row as DirectorySource).last_status!].type"
              >
                {{ STATUS_INFO[(row as DirectorySource).last_status!].label }}
              </el-tag>
              <div class="muted small">{{ formatDateTime(row.last_sync_at) }}</div>
            </template>
            <span v-else class="muted small">从未同步</span>
          </template>
        </el-table-column>
        <el-table-column label="下次同步" width="160">
          <template #default="{ row }">
            <span class="small">{{
              row.next_sync_at ? formatDateTime(row.next_sync_at) : '—'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <template v-if="row.type === 'excel'">
              <el-button
                link
                type="primary"
                :loading="busy === row.id"
                data-test="upload-preview"
                @click="pickFile(row as DirectorySource, 'preview')"
              >
                上传并预览
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
                预览差异
              </el-button>
            </template>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onCommand(row as DirectorySource, cmd)"
            >
              <el-button link type="primary">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item v-if="row.type === 'excel'" command="upload_apply">
                    上传并直接应用
                  </el-dropdown-item>
                  <el-dropdown-item v-else command="apply" :disabled="!row.enabled">
                    直接应用同步
                  </el-dropdown-item>
                  <el-dropdown-item command="edit">编辑配置</el-dropdown-item>
                  <el-dropdown-item v-if="!row.is_primary" command="primary"
                    >设为主数据源</el-dropdown-item
                  >
                  <el-dropdown-item command="toggle">{{
                    row.enabled ? '停用' : '启用'
                  }}</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <span class="danger">删除</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>同步历史</template>
      <el-table
        :data="runs"
        empty-text="暂无同步记录"
        class="run-table"
        data-test="run-table"
        @row-click="openRun"
      >
        <el-table-column label="时间" width="170">
          <template #default="{ row }">
            <span class="small">{{ formatDateTime(row.started_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="数据源" width="140">
          <template #default="{ row }">
            {{ sourceName.get(row.source_id)?.name ?? '（已删除）' }}
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            {{ row.mode === 'preview' ? '预览' : row.forced ? '强制应用' : '应用' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_INFO[(row as SyncRun).status].type">
              {{ STATUS_INFO[(row as SyncRun).status].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="结果" min-width="280">
          <template #default="{ row }">
            <span class="small">{{ runSummary(row as SyncRun) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90" align="right">
          <template #default="{ row }">
            <span class="small">{{
              row.finished_at ? `${(row.duration_ms / 1000).toFixed(1)}s` : '…'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column label="触发人" width="120" prop="triggered_by" />
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
