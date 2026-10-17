<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  createEvalDataset,
  deleteEvalDataset,
  listEvalDatasets,
  updateEvalDataset,
} from '@/api/evaluation'
import type { EvalDataset } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const { t } = useI18n()

const pager = reactive({ page: 1, size: 20 })
const items = ref<EvalDataset[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listEvalDatasets(pager)
    items.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

// ---- create / edit ------------------------------------------------------------

const dialogVisible = ref(false)
const editing = ref<EvalDataset | null>(null)
const formRef = ref<FormInstance>()
const form = reactive({ name: '', description: '' })
const saving = ref(false)
const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('evaluation.datasets.nameRequired'), trigger: 'blur' }],
}))

function openDialog(dataset: EvalDataset | null): void {
  editing.value = dataset
  form.name = dataset?.name ?? ''
  form.description = dataset?.description ?? ''
  dialogVisible.value = true
  formRef.value?.clearValidate()
}

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const body = { name: form.name.trim(), description: form.description.trim() || null }
    if (editing.value) {
      await updateEvalDataset(editing.value.id, body)
    } else {
      const created = await createEvalDataset(body)
      void router.push(`/admin/eval-datasets/${created.id}`)
    }
    ElMessage.success(t('common.saved'))
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(dataset: EvalDataset): Promise<void> {
  await ElMessageBox.confirm(
    t('evaluation.datasets.deleteConfirm', { name: dataset.name }),
    t('evaluation.datasets.deleteTitle'),
    { type: 'warning' },
  )
  await deleteEvalDataset(dataset.id)
  ElMessage.success(t('common.deleted'))
  await load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>{{ t('evaluation.shared.datasets') }}</span>
        <el-button type="primary" @click="openDialog(null)">{{
          t('evaluation.datasets.create')
        }}</el-button>
      </div>
    </template>

    <el-table
      v-loading="loading"
      :data="items"
      row-key="id"
      :empty-text="t('evaluation.datasets.empty')"
    >
      <el-table-column :label="t('common.name')" min-width="200">
        <template #default="{ row }">
          <RouterLink :to="`/admin/eval-datasets/${row.id}`">{{ row.name }}</RouterLink>
        </template>
      </el-table-column>
      <el-table-column
        :label="t('evaluation.datasets.descriptionCol')"
        min-width="260"
        show-overflow-tooltip
      >
        <template #default="{ row }">{{ row.description ?? '' }}</template>
      </el-table-column>
      <el-table-column prop="case_count" :label="t('evaluation.datasets.caseCount')" width="90" />
      <el-table-column :label="t('common.updatedAt')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column :label="t('common.actions')" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/admin/eval-datasets/${row.id}`)">
            {{ t('evaluation.shared.cases') }}
          </el-button>
          <el-button
            link
            type="primary"
            @click="router.push(`/admin/eval-runs?dataset_id=${row.id}`)"
          >
            {{ t('evaluation.datasets.runs') }}
          </el-button>
          <el-button link @click="openDialog(row as EvalDataset)">{{ t('common.edit') }}</el-button>
          <el-button link type="danger" @click="remove(row as EvalDataset)">{{
            t('common.delete')
          }}</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      @current-change="load"
    />

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? t('evaluation.datasets.edit') : t('evaluation.datasets.create')"
      width="520px"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item :label="t('common.name')" prop="name">
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item :label="t('evaluation.datasets.descriptionCol')">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{
          t('common.save')
        }}</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
