<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
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
const rules: FormRules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

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
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(dataset: EvalDataset): Promise<void> {
  await ElMessageBox.confirm(
    `删除评测集「${dataset.name}」将同时删除其用例和评测记录，确定继续？`,
    '删除评测集',
    { type: 'warning' },
  )
  await deleteEvalDataset(dataset.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <span>评测集</span>
        <el-button type="primary" @click="openDialog(null)">新建评测集</el-button>
      </div>
    </template>

    <el-table v-loading="loading" :data="items" row-key="id" empty-text="暂无评测集">
      <el-table-column label="名称" min-width="200">
        <template #default="{ row }">
          <RouterLink :to="`/admin/eval-datasets/${row.id}`">{{ row.name }}</RouterLink>
        </template>
      </el-table-column>
      <el-table-column label="说明" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.description ?? '' }}</template>
      </el-table-column>
      <el-table-column prop="case_count" label="用例数" width="90" />
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/admin/eval-datasets/${row.id}`)">
            用例
          </el-button>
          <el-button
            link
            type="primary"
            @click="router.push(`/admin/eval-runs?dataset_id=${row.id}`)"
          >
            评测记录
          </el-button>
          <el-button link @click="openDialog(row as EvalDataset)">编辑</el-button>
          <el-button link type="danger" @click="remove(row as EvalDataset)">删除</el-button>
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

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑评测集' : '新建评测集'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
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
