<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { listAuditLogs } from '@/api/admin'
import type { AuditDiffEntry, AuditLog } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const filters = reactive({
  action: '',
  resource_type: '',
  resource_id: '',
  actor_id: '',
  trace_id: '',
  range: null as [Date, Date] | null,
})
const pager = reactive({ page: 1, size: 20 })
const rows = ref<AuditLog[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const { range, ...rest } = filters
    const params = Object.fromEntries(Object.entries(rest).filter(([, v]) => v))
    const page = await listAuditLogs({
      ...params,
      start: range?.[0].toISOString(),
      end: range?.[1].toISOString(),
      ...pager,
    })
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function search(): void {
  pager.page = 1
  void load()
}

function reset(): void {
  Object.assign(filters, {
    action: '',
    resource_type: '',
    resource_id: '',
    actor_id: '',
    trace_id: '',
    range: null,
  })
  search()
}

function diffRows(log: AuditLog): ({ field: string } & AuditDiffEntry)[] {
  return Object.entries(log.diff ?? {}).map(([field, d]) => ({ field, ...d }))
}

function display(value: unknown): string {
  if (value === null || value === undefined) return '—'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function statusType(code: number | null): 'success' | 'warning' | 'danger' | 'info' {
  if (code === null) return 'info'
  if (code >= 500) return 'danger'
  if (code >= 400) return 'warning'
  return 'success'
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <el-form :inline="true" @submit.prevent="search">
      <el-form-item label="动作">
        <el-input v-model="filters.action" placeholder="如 user.update" clearable />
      </el-form-item>
      <el-form-item label="资源类型">
        <el-input v-model="filters.resource_type" placeholder="如 user / role" clearable />
      </el-form-item>
      <el-form-item label="资源 ID">
        <el-input v-model="filters.resource_id" clearable />
      </el-form-item>
      <el-form-item label="操作人 ID">
        <el-input v-model="filters.actor_id" clearable />
      </el-form-item>
      <el-form-item label="Trace ID">
        <el-input v-model="filters.trace_id" clearable />
      </el-form-item>
      <el-form-item label="时间">
        <el-date-picker
          v-model="filters.range"
          type="datetimerange"
          start-placeholder="开始"
          end-placeholder="结束"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无审计记录">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="detail">
            <el-descriptions :column="2" size="small" border>
              <el-descriptions-item label="请求">
                {{ row.method ?? '-' }} {{ row.path ?? '' }}
              </el-descriptions-item>
              <el-descriptions-item label="Trace ID">
                {{ row.trace_id ?? '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="User-Agent" :span="2">
                {{ row.user_agent ?? '-' }}
              </el-descriptions-item>
            </el-descriptions>
            <el-table
              v-if="diffRows(row as AuditLog).length"
              :data="diffRows(row as AuditLog)"
              size="small"
              class="detail__diff"
            >
              <el-table-column prop="field" label="字段" width="180" />
              <el-table-column label="变更前">
                <template #default="{ row: d }">
                  <span class="diff-before">{{ display(d.before) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="变更后">
                <template #default="{ row: d }">
                  <span class="diff-after">{{ display(d.after) }}</span>
                </template>
              </el-table-column>
            </el-table>
            <el-text v-else type="info" size="small" class="detail__diff">无字段变更</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作人" min-width="110">
        <template #default="{ row }">{{ row.actor_name ?? row.actor_id ?? '系统' }}</template>
      </el-table-column>
      <el-table-column prop="action" label="动作" min-width="140" />
      <el-table-column label="资源" min-width="200">
        <template #default="{ row }">
          {{ row.resource_type ?? '-' }}<span v-if="row.resource_id"> / {{ row.resource_id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="IP" width="130" />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.status_code" :type="statusType(row.status_code)" size="small">
            {{ row.status_code }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      class="pager"
      layout="total, sizes, prev, pager, next"
      :total="total"
      @current-change="load"
      @size-change="search"
    />
  </el-card>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.detail {
  padding: 8px 48px;
}

.detail__diff {
  margin-top: 12px;
  display: block;
}

.diff-before {
  color: var(--el-color-danger);
  word-break: break-all;
}

.diff-after {
  color: var(--el-color-success);
  word-break: break-all;
}
</style>
