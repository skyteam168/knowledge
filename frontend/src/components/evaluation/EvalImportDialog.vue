<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { importEvalCases, listEvalCandidates } from '@/api/evaluation'
import type { EvalCandidate, EvalImportSource } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ datasetId: string }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ imported: [] }>()

const source = ref<EvalImportSource>('feedback')
const keyword = ref('')
const pager = reactive({ page: 1, size: 20 })
const items = ref<EvalCandidate[]>([])
const total = ref(0)
const loading = ref(false)
const selected = ref<EvalCandidate[]>([])
const importing = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listEvalCandidates({
      source: source.value,
      dataset_id: props.datasetId,
      keyword: keyword.value.trim() || undefined,
      ...pager,
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

async function submit(): Promise<void> {
  if (!selected.value.length) return
  importing.value = true
  try {
    const result = await importEvalCases(
      props.datasetId,
      source.value,
      selected.value.map((c) => c.source_id),
    )
    ElMessage.success(
      `已导入 ${result.created} 条${result.skipped ? `，跳过 ${result.skipped} 条` : ''}`,
    )
    emit('imported')
    await load()
  } finally {
    importing.value = false
  }
}

watch(visible, (open) => {
  if (open) search()
})
watch(source, search)
</script>

<template>
  <el-dialog v-model="visible" title="从问答记录导入用例" width="960px">
    <div class="toolbar">
      <el-radio-group v-model="source">
        <el-radio-button value="feedback">点赞的问答</el-radio-button>
        <el-radio-button value="gap">已解决的知识缺口</el-radio-button>
      </el-radio-group>
      <el-input
        v-model="keyword"
        placeholder="按问题搜索"
        clearable
        style="width: 260px"
        @keyup.enter="search"
        @clear="search"
      />
    </div>
    <el-table
      v-loading="loading"
      :data="items"
      row-key="source_id"
      height="420"
      empty-text="暂无可导入的记录"
      @selection-change="(rows: EvalCandidate[]) => (selected = rows)"
    >
      <el-table-column
        type="selection"
        width="44"
        :selectable="(row: EvalCandidate) => !row.imported"
      />
      <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
      <el-table-column label="参考答案" min-width="260" show-overflow-tooltip>
        <template #default="{ row }">{{ row.reference_answer ?? '—' }}</template>
      </el-table-column>
      <el-table-column label="期望文档" width="90">
        <template #default="{ row }">{{ row.expected_document_ids.length }}</template>
      </el-table-column>
      <el-table-column label="时间" width="160">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.imported" type="info" size="small">已导入</el-tag>
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
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :disabled="!selected.length" :loading="importing" @click="submit">
        导入所选（{{ selected.length }}）
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
