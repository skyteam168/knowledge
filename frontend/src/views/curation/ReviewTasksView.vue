<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listReviewTasks } from '@/api/curation'
import type { ReviewStatus, ReviewTask } from '@/api/types'
import { REVIEW_STATUS_META, isWarning, metaOf } from '@/utils/curation'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const { t } = useI18n()

const status = ref<ReviewStatus>('pending')
const pager = reactive({ page: 1, size: 20 })
const items = ref<ReviewTask[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listReviewTasks({ status: status.value, ...pager })
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

function warningCount(task: ReviewTask): number {
  return task.conflicts.filter((c) => isWarning(c.verdict)).length
}

function open(task: ReviewTask): void {
  void router.push({ name: 'curation-ko', params: { koId: task.ko_id } })
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <el-radio-group v-model="status" class="filters" @change="search">
      <el-radio-button
        v-for="(meta, key) in REVIEW_STATUS_META"
        :key="key"
        :value="key"
        :label="meta.label"
      />
    </el-radio-group>
    <el-table v-loading="loading" :data="items" row-key="id" @row-click="open">
      <el-table-column :label="t('curation.reviewTasks.ko')" min-width="260">
        <template #default="{ row }">{{ row.ko_title ?? row.ko_id }}</template>
      </el-table-column>
      <el-table-column :label="t('curation.field.version')" width="70">
        <template #default="{ row }">v{{ row.ko_version }}</template>
      </el-table-column>
      <el-table-column
        :label="t('curation.reviewTasks.conflictWarnings')"
        width="100"
        align="center"
      >
        <template #default="{ row }">
          <el-tag v-if="warningCount(row as ReviewTask)" type="danger" size="small">
            {{ warningCount(row as ReviewTask) }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('curation.field.submitter')" width="110">
        <template #default="{ row }">{{ row.submitted_by?.name ?? '-' }}</template>
      </el-table-column>
      <el-table-column
        :label="t('curation.reviewTasks.submitNote')"
        prop="note"
        min-width="160"
        show-overflow-tooltip
      />
      <el-table-column :label="t('curation.field.submittedAt')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.status')" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="metaOf(REVIEW_STATUS_META, row.status).type">
            {{ metaOf(REVIEW_STATUS_META, row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('curation.reviewTasks.reviewer')" width="110">
        <template #default="{ row }">{{ row.reviewer?.name ?? '-' }}</template>
      </el-table-column>
      <el-table-column
        :label="t('curation.reviewTasks.reviewComment')"
        prop="comment"
        min-width="160"
        show-overflow-tooltip
      />
    </el-table>
    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      :total="total"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="load"
      @size-change="search"
    />
  </el-card>
</template>

<style scoped>
.filters {
  margin-bottom: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
