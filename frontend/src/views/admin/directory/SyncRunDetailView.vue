<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getSyncRun, listDirectorySources, startDirectorySync } from '@/api/directory'
import type { DirectorySource, SyncChange, SyncRunDetail } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import {
  ACTION_LABEL,
  DEPT_STAT_KEYS,
  IDENTITY_STAT_KEYS,
  MATCH_LABEL,
  SOURCE_LABEL,
  STATUS_INFO,
  USER_STAT_KEYS,
  statLine,
} from './meta'

const props = defineProps<{ runId: string }>()
const router = useRouter()
const run = ref<SyncRunDetail | null>(null)
const source = ref<DirectorySource | null>(null)
const loading = ref(false)
const tab = ref('departments')
let timer: ReturnType<typeof setTimeout> | null = null

const stats = computed(() => run.value?.stats.stats)
const identityMode = computed(() => !!stats.value?.identities)
const changes = computed(() => run.value?.changes ?? {})
const tabs = computed(() =>
  identityMode.value
    ? [
        { name: 'identities', label: '身份绑定' },
        { name: 'unmatched', label: '未匹配人员' },
      ]
    : [
        { name: 'departments', label: '部门' },
        { name: 'users', label: '人员' },
        { name: 'disabled', label: '停用' },
      ],
)

async function load(): Promise<void> {
  loading.value = true
  try {
    run.value = await getSyncRun(props.runId)
    const sources = await listDirectorySources()
    source.value = sources.find((s) => s.id === run.value?.source_id) ?? null
    if (!tabs.value.some((t) => t.name === tab.value)) tab.value = tabs.value[0].name
    if (run.value.status === 'running') timer = setTimeout(load, 2000)
  } finally {
    loading.value = false
  }
}

watch(() => props.runId, load, { immediate: true })
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})

function rows(name: string): SyncChange[] {
  return changes.value[name] ?? []
}

function count(name: string): number {
  const s = stats.value
  if (!s) return rows(name).length
  if (name === 'departments') {
    const d = s.departments ?? {}
    return DEPT_STAT_KEYS.reduce((n, [k]) => n + (d[k] ?? 0), 0)
  }
  if (name === 'users') {
    const u = s.users ?? {}
    return ['created', 'updated', 'adopted', 'restored'].reduce((n, k) => n + (u[k] ?? 0), 0)
  }
  if (name === 'disabled') return s.users?.disabled ?? 0
  if (name === 'identities') return (s.identities?.bound ?? 0) + (s.identities?.removed ?? 0)
  if (name === 'unmatched') return s.identities?.unmatched ?? 0
  return rows(name).length
}

function labels(change: SyncChange): string[] {
  return (change.changes ?? [change.action]).map((c) => ACTION_LABEL[c] ?? c)
}

const canApply = computed(
  () =>
    !!run.value &&
    !!source.value &&
    source.value.type !== 'excel' &&
    run.value.status !== 'running' &&
    (run.value.mode === 'preview' || run.value.status === 'aborted'),
)

async function apply(force: boolean): Promise<void> {
  if (!source.value || !run.value) return
  await ElMessageBox.confirm(
    force
      ? `本次同步停用人数超过保护阈值。确认这是正常的人员变动（例如批量离职）后再强制应用。`
      : `将重新读取「${source.value.name}」的最新数据并应用（结果以应用时为准）。确定吗？`,
    force ? '强制应用' : '应用同步',
    { type: 'warning', confirmButtonText: force ? '强制应用' : '应用' },
  )
  const next = await startDirectorySync(source.value.id, 'apply', force)
  ElMessage.success('已开始同步')
  void router.replace({ name: 'admin-directory-run', params: { runId: next.id } })
}
</script>

<template>
  <div v-loading="loading && !run" class="page">
    <div class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push({ name: 'admin-directory' })">
          返回组织同步
        </el-button>
        <h2 class="page-header__title">
          {{ run?.mode === 'preview' ? '同步预览' : '同步结果' }}
          <el-tag v-if="run" :type="STATUS_INFO[run.status].type">{{
            STATUS_INFO[run.status].label
          }}</el-tag>
        </h2>
        <p v-if="run" class="page-header__desc">
          {{
            source
              ? `${source.name}（${SOURCE_LABEL[source.type]}${source.is_primary ? '，主数据源' : ''}）`
              : ''
          }}
          · {{ formatDateTime(run.started_at) }} · {{ run.triggered_by ?? '—' }}
          <template v-if="run.finished_at">
            · 耗时 {{ (run.duration_ms / 1000).toFixed(1) }}s</template
          >
        </p>
      </div>
      <div v-if="canApply" class="actions">
        <el-button
          v-if="run?.status === 'aborted'"
          type="danger"
          data-test="force-apply"
          @click="apply(true).catch(() => undefined)"
        >
          强制应用
        </el-button>
        <el-button
          v-else-if="run?.status === 'succeeded'"
          type="primary"
          data-test="apply"
          @click="apply(false).catch(() => undefined)"
        >
          应用这些变更
        </el-button>
      </div>
    </div>

    <template v-if="run">
      <el-alert
        v-if="run.status === 'running'"
        type="info"
        :closable="false"
        show-icon
        title="正在读取数据源并计算差异…"
        class="block"
      />
      <el-alert
        v-if="run.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        :title="run.error ?? '同步失败'"
        class="block"
      />
      <el-alert
        v-if="run.status === 'aborted'"
        type="warning"
        :closable="false"
        show-icon
        :title="`已中止：${run.error}`"
        description="没有写入任何数据。请核对下方「停用」列表，确认无误后可强制应用。"
        class="block"
      />
      <el-alert
        v-if="run.mode === 'preview' && run.status === 'succeeded' && source?.type === 'excel'"
        type="info"
        :closable="false"
        show-icon
        title="这是预览，未写入数据。确认无误后，在组织同步页用「更多 → 上传并直接应用」上传同一文件。"
        class="block"
      />

      <div v-if="stats" class="stats block">
        <template v-if="identityMode">
          <el-card shadow="never" class="stat">
            <div class="stat__label">身份绑定</div>
            <div class="stat__value">{{ statLine(stats.identities, IDENTITY_STAT_KEYS) }}</div>
          </el-card>
        </template>
        <template v-else>
          <el-card shadow="never" class="stat">
            <div class="stat__label">部门（共 {{ stats.departments?.total ?? 0 }}）</div>
            <div class="stat__value">{{ statLine(stats.departments, DEPT_STAT_KEYS) }}</div>
          </el-card>
          <el-card shadow="never" class="stat">
            <div class="stat__label">人员（共 {{ stats.users?.total ?? 0 }}）</div>
            <div class="stat__value">{{ statLine(stats.users, USER_STAT_KEYS) }}</div>
          </el-card>
        </template>
      </div>

      <el-alert
        v-if="run.stats.warnings?.length"
        type="warning"
        :closable="false"
        class="block"
        :title="`数据提示（${run.stats.warnings.length}）`"
      >
        <ul class="warnings">
          <li v-for="w in run.stats.warnings.slice(0, 20)" :key="w">{{ w }}</li>
        </ul>
      </el-alert>

      <el-card v-if="run.status !== 'running' && run.status !== 'failed'" shadow="never">
        <el-tabs v-model="tab">
          <el-tab-pane
            v-for="t in tabs"
            :key="t.name"
            :name="t.name"
            :label="`${t.label} (${count(t.name)})`"
          >
            <el-table :data="rows(t.name)" size="small" max-height="560" empty-text="无变化">
              <el-table-column label="变化" width="200">
                <template #default="{ row }">
                  <el-tag
                    v-for="l in labels(row as SyncChange)"
                    :key="l"
                    size="small"
                    effect="plain"
                    class="tag"
                  >
                    {{ l }}
                  </el-tag>
                </template>
              </el-table-column>
              <template v-if="t.name === 'departments'">
                <el-table-column label="部门" min-width="280">
                  <template #default="{ row }">
                    {{ row.path ?? row.name }}
                    <span v-if="row.before && row.before !== row.name" class="muted small">
                      （原名：{{ row.before }}）
                    </span>
                  </template>
                </el-table-column>
                <el-table-column label="外部 ID" width="160" prop="external_id" />
              </template>
              <template v-else-if="t.name === 'unmatched'">
                <el-table-column label="姓名" width="140" prop="name" />
                <el-table-column label="工号" width="120" prop="employee_no" />
                <el-table-column label="手机" width="140" prop="mobile" />
                <el-table-column label="邮箱" min-width="180" prop="email" />
                <el-table-column label="外部 ID" width="160" prop="external_id" />
              </template>
              <template v-else>
                <el-table-column label="姓名" width="140" prop="name" />
                <el-table-column label="账号" width="160" prop="username" />
                <el-table-column
                  v-if="t.name === 'users'"
                  label="工号"
                  width="110"
                  prop="employee_no"
                />
                <el-table-column v-if="t.name === 'users'" label="职务" width="130" prop="title" />
                <el-table-column label="匹配方式" min-width="120">
                  <template #default="{ row }">
                    <span class="small">{{
                      row.match ? `按${MATCH_LABEL[row.match] ?? row.match}匹配` : ''
                    }}</span>
                  </template>
                </el-table-column>
              </template>
            </el-table>
            <div v-if="rows(t.name).length < count(t.name)" class="muted small more">
              仅显示前 {{ rows(t.name).length }} 条明细
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </template>
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
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 4px;
  font-size: 18px;
  font-weight: 600;
}
.page-header__desc {
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
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.stat__label {
  font-size: 12px;
  color: var(--ekb-text-3);
}
.stat__value {
  margin-top: 6px;
  font-size: 15px;
  font-weight: 600;
}
.tag {
  margin: 2px 4px 2px 0;
}
.small {
  font-size: 12px;
}
.more {
  margin-top: 8px;
}
.warnings {
  margin: 4px 0 0;
  padding-left: 18px;
}
</style>
