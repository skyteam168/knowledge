<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { getSyncRun, listDirectorySources, startDirectorySync } from '@/api/directory'
import type { DirectorySource, SyncChange, SyncRunDetail } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import {
  DEPT_STAT_KEYS,
  IDENTITY_STAT_KEYS,
  USER_STAT_KEYS,
  actionLabel,
  matchLabel,
  sourceLabel,
  statLine,
  statusInfo,
} from './meta'

const { t } = useI18n()
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
        { name: 'identities', label: t('directory.run.tabs.identities') },
        { name: 'unmatched', label: t('directory.run.tabs.unmatched') },
      ]
    : [
        { name: 'departments', label: t('directory.run.tabs.departments') },
        { name: 'users', label: t('directory.run.tabs.users') },
        { name: 'disabled', label: t('directory.run.tabs.disabled') },
      ],
)
const sourceInfo = computed(() => {
  const s = source.value
  if (!s) return ''
  const named = { name: s.name, type: sourceLabel(s.type) }
  return s.is_primary
    ? t('directory.run.sourceInfoPrimary', named)
    : t('directory.run.sourceInfo', named)
})

async function load(): Promise<void> {
  loading.value = true
  try {
    run.value = await getSyncRun(props.runId)
    const sources = await listDirectorySources()
    source.value = sources.find((s) => s.id === run.value?.source_id) ?? null
    if (!tabs.value.some((item) => item.name === tab.value)) tab.value = tabs.value[0].name
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
    return DEPT_STAT_KEYS.reduce((n, k) => n + (d[k] ?? 0), 0)
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
  return (change.changes ?? [change.action]).map(actionLabel)
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
      ? t('directory.run.forceConfirm')
      : t('directory.run.applyConfirm', { name: source.value.name }),
    force ? t('directory.run.forceApply') : t('directory.run.applyTitle'),
    {
      type: 'warning',
      confirmButtonText: force ? t('directory.run.forceApply') : t('directory.run.apply'),
    },
  )
  const next = await startDirectorySync(source.value.id, 'apply', force)
  ElMessage.success(t('directory.sources.syncStarted'))
  void router.replace({ name: 'admin-directory-run', params: { runId: next.id } })
}
</script>

<template>
  <div v-loading="loading && !run" class="page">
    <div class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push({ name: 'admin-directory' })">
          {{ t('directory.run.back') }}
        </el-button>
        <h2 class="page-header__title">
          {{
            run?.mode === 'preview'
              ? t('directory.run.previewTitle')
              : t('directory.run.resultTitle')
          }}
          <el-tag v-if="run" :type="statusInfo(run.status).type">{{
            statusInfo(run.status).label
          }}</el-tag>
        </h2>
        <p v-if="run" class="page-header__desc">
          {{ sourceInfo }}
          · {{ formatDateTime(run.started_at) }} · {{ run.triggered_by ?? '—' }}
          <template v-if="run.finished_at">
            ·
            {{
              t('directory.run.duration', { seconds: (run.duration_ms / 1000).toFixed(1) })
            }}</template
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
          {{ t('directory.run.forceApply') }}
        </el-button>
        <el-button
          v-else-if="run?.status === 'succeeded'"
          type="primary"
          data-test="apply"
          @click="apply(false).catch(() => undefined)"
        >
          {{ t('directory.run.applyChanges') }}
        </el-button>
      </div>
    </div>

    <template v-if="run">
      <el-alert
        v-if="run.status === 'running'"
        type="info"
        :closable="false"
        show-icon
        :title="t('directory.run.running')"
        class="block"
      />
      <el-alert
        v-if="run.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        :title="run.error ?? t('directory.run.failed')"
        class="block"
      />
      <el-alert
        v-if="run.status === 'aborted'"
        type="warning"
        :closable="false"
        show-icon
        :title="t('directory.run.aborted', { error: run.error })"
        :description="t('directory.run.abortedDesc')"
        class="block"
      />
      <el-alert
        v-if="run.mode === 'preview' && run.status === 'succeeded' && source?.type === 'excel'"
        type="info"
        :closable="false"
        show-icon
        :title="t('directory.run.excelPreview')"
        class="block"
      />

      <div v-if="stats" class="stats block">
        <template v-if="identityMode">
          <el-card shadow="never" class="stat">
            <div class="stat__label">{{ t('directory.run.tabs.identities') }}</div>
            <div class="stat__value">{{ statLine(stats.identities, IDENTITY_STAT_KEYS) }}</div>
          </el-card>
        </template>
        <template v-else>
          <el-card shadow="never" class="stat">
            <div class="stat__label">
              {{ t('directory.run.departmentsTotal', { total: stats.departments?.total ?? 0 }) }}
            </div>
            <div class="stat__value">{{ statLine(stats.departments, DEPT_STAT_KEYS) }}</div>
          </el-card>
          <el-card shadow="never" class="stat">
            <div class="stat__label">
              {{ t('directory.run.usersTotal', { total: stats.users?.total ?? 0 }) }}
            </div>
            <div class="stat__value">{{ statLine(stats.users, USER_STAT_KEYS) }}</div>
          </el-card>
        </template>
      </div>

      <el-alert
        v-if="run.stats.warnings?.length"
        type="warning"
        :closable="false"
        class="block"
        :title="t('directory.run.warnings', { count: run.stats.warnings.length })"
      >
        <ul class="warnings">
          <li v-for="w in run.stats.warnings.slice(0, 20)" :key="w">{{ w }}</li>
        </ul>
      </el-alert>

      <el-card v-if="run.status !== 'running' && run.status !== 'failed'" shadow="never">
        <el-tabs v-model="tab">
          <el-tab-pane
            v-for="item in tabs"
            :key="item.name"
            :name="item.name"
            :label="`${item.label} (${count(item.name)})`"
          >
            <el-table
              :data="rows(item.name)"
              size="small"
              max-height="560"
              :empty-text="t('directory.stat.noChange')"
            >
              <el-table-column :label="t('directory.run.change')" width="200">
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
              <template v-if="item.name === 'departments'">
                <el-table-column :label="t('directory.run.department')" min-width="280">
                  <template #default="{ row }">
                    {{ row.path ?? row.name }}
                    <span v-if="row.before && row.before !== row.name" class="muted small">
                      {{ t('directory.run.renamedFrom', { name: row.before }) }}
                    </span>
                  </template>
                </el-table-column>
                <el-table-column
                  :label="t('directory.run.externalId')"
                  width="160"
                  prop="external_id"
                />
              </template>
              <template v-else-if="item.name === 'unmatched'">
                <el-table-column :label="t('directory.run.personName')" width="140" prop="name" />
                <el-table-column
                  :label="t('directory.run.employeeNo')"
                  width="120"
                  prop="employee_no"
                />
                <el-table-column :label="t('directory.run.mobile')" width="140" prop="mobile" />
                <el-table-column :label="t('directory.run.email')" min-width="180" prop="email" />
                <el-table-column
                  :label="t('directory.run.externalId')"
                  width="160"
                  prop="external_id"
                />
              </template>
              <template v-else>
                <el-table-column :label="t('directory.run.personName')" width="140" prop="name" />
                <el-table-column :label="t('directory.run.username')" width="160" prop="username" />
                <el-table-column
                  v-if="item.name === 'users'"
                  :label="t('directory.run.employeeNo')"
                  width="110"
                  prop="employee_no"
                />
                <el-table-column
                  v-if="item.name === 'users'"
                  :label="t('directory.run.jobTitle')"
                  width="130"
                  prop="title"
                />
                <el-table-column :label="t('directory.run.matchMethod')" min-width="120">
                  <template #default="{ row }">
                    <span class="small">{{
                      row.match ? t('directory.run.matchBy', { field: matchLabel(row.match) }) : ''
                    }}</span>
                  </template>
                </el-table-column>
              </template>
            </el-table>
            <div v-if="rows(item.name).length < count(item.name)" class="muted small more">
              {{ t('directory.run.showingFirst', { n: rows(item.name).length }) }}
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
