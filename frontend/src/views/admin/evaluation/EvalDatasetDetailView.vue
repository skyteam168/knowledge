<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import EvalCaseDialog from '@/components/evaluation/EvalCaseDialog.vue'
import EvalImportDialog from '@/components/evaluation/EvalImportDialog.vue'
import EvalRunDialog from '@/components/evaluation/EvalRunDialog.vue'
import { deleteEvalCase, getEvalDataset, listEvalCases } from '@/api/evaluation'
import type { EvalCase, EvalCaseSource, EvalDataset, EvalRun } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const SOURCE_LABELS: Record<EvalCaseSource, string> = {
  manual: '手工',
  feedback: '点赞问答',
  gap: '知识缺口',
}

const props = defineProps<{ datasetId: string }>()
const router = useRouter()

const dataset = ref<EvalDataset | null>(null)
const keyword = ref('')
const pager = reactive({ page: 1, size: 20 })
const items = ref<EvalCase[]>([])
const total = ref(0)
const loading = ref(false)

async function loadDataset(): Promise<void> {
  dataset.value = await getEvalDataset(props.datasetId)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listEvalCases(props.datasetId, {
      ...pager,
      keyword: keyword.value.trim() || undefined,
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

function reload(): void {
  void loadDataset()
  void load()
}

const caseDialog = ref(false)
const editing = ref<EvalCase | null>(null)
const importDialog = ref(false)
const runDialog = ref(false)

function openCase(c: EvalCase | null): void {
  editing.value = c
  caseDialog.value = true
}

async function remove(c: EvalCase): Promise<void> {
  await ElMessageBox.confirm('确定删除该用例？', '删除用例', { type: 'warning' })
  await deleteEvalCase(c.id)
  ElMessage.success('已删除')
  reload()
}

function onRunCreated(run: EvalRun): void {
  void router.push(`/admin/eval-runs/${run.id}`)
}

onMounted(reload)
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <div>
          <el-button link @click="router.push('/admin/eval-datasets')">评测集</el-button>
          <span class="sep">/</span>
          <span class="title">{{ dataset?.name }}</span>
          <span v-if="dataset" class="count">{{ dataset.case_count }} 条用例</span>
        </div>
        <div>
          <el-button @click="importDialog = true">从问答导入</el-button>
          <el-button @click="openCase(null)">新增用例</el-button>
          <el-button type="primary" :disabled="!dataset?.case_count" @click="runDialog = true">
            运行评测
          </el-button>
        </div>
      </div>
      <div v-if="dataset?.description" class="desc">{{ dataset.description }}</div>
    </template>

    <el-form :inline="true" @submit.prevent="search">
      <el-form-item>
        <el-input v-model="keyword" placeholder="按问题搜索" clearable @clear="search" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" row-key="id" empty-text="暂无用例">
      <el-table-column type="expand">
        <template #default="{ row }">
          <el-descriptions :column="1" size="small" border class="detail">
            <el-descriptions-item label="标准答案">
              <div class="answer">{{ row.reference_answer ?? '—' }}</div>
            </el-descriptions-item>
            <el-descriptions-item label="期望文档">
              <code v-for="id in row.expected_document_ids" :key="id" class="mono">{{ id }}</code>
              <span v-if="!row.expected_document_ids.length">—</span>
            </el-descriptions-item>
            <el-descriptions-item label="期望 Chunk">
              <code v-for="id in row.expected_chunk_ids" :key="id" class="mono">{{ id }}</code>
              <span v-if="!row.expected_chunk_ids.length">—</span>
            </el-descriptions-item>
            <el-descriptions-item label="知识库范围">
              <code v-for="id in row.kb_ids" :key="id" class="mono">{{ id }}</code>
              <span v-if="!row.kb_ids.length">全部</span>
            </el-descriptions-item>
          </el-descriptions>
        </template>
      </el-table-column>
      <el-table-column prop="question" label="问题" min-width="280" show-overflow-tooltip />
      <el-table-column label="期望文档" width="90">
        <template #default="{ row }">{{ row.expected_document_ids.length }}</template>
      </el-table-column>
      <el-table-column label="标准答案" width="90">
        <template #default="{ row }">{{ row.reference_answer ? '有' : '—' }}</template>
      </el-table-column>
      <el-table-column label="来源" width="100">
        <template #default="{ row }">{{
          SOURCE_LABELS[row.source as EvalCaseSource] ?? row.source
        }}</template>
      </el-table-column>
      <el-table-column label="标签" min-width="140">
        <template #default="{ row }">
          <el-tag v-for="tag in row.tags" :key="tag" size="small" class="tag">{{ tag }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openCase(row as EvalCase)">编辑</el-button>
          <el-button link type="danger" @click="remove(row as EvalCase)">删除</el-button>
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

    <EvalCaseDialog
      v-model="caseDialog"
      :dataset-id="datasetId"
      :eval-case="editing"
      @saved="reload"
    />
    <EvalImportDialog v-model="importDialog" :dataset-id="datasetId" @imported="reload" />
    <EvalRunDialog v-model="runDialog" :dataset-id="datasetId" @created="onRunCreated" />
  </el-card>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.sep {
  margin: 0 8px;
  color: var(--el-text-color-secondary);
}

.title {
  font-weight: 600;
}

.count {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.desc {
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.detail {
  padding: 8px 48px;
}

.answer {
  white-space: pre-wrap;
}

.mono {
  display: block;
  font-family: var(--el-font-family-mono, monospace);
  font-size: 12px;
}

.tag {
  margin-right: 4px;
}

.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
