<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createKo, generateFaq, listKos } from '@/api/curation'
import { listKnowledgeBases } from '@/api/knowledge'
import type { KnowledgeBase, KnowledgeObject, KoStatus, KoType } from '@/api/types'
import DocumentPicker from '@/components/curation/DocumentPicker.vue'
import { useAuthStore } from '@/stores/auth'
import { KO_STATUS_META, KO_TYPE_LABEL, ORIGIN_LABEL, metaOf } from '@/utils/curation'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

const filters = reactive({
  kb_id: '',
  status: '' as KoStatus | '',
  ko_type: '' as KoType | '',
  keyword: '',
  mine: false,
})
const pager = reactive({ page: 1, size: 20 })
const items = ref<KnowledgeObject[]>([])
const total = ref(0)
const loading = ref(false)
const kbOptions = ref<KnowledgeBase[]>([])

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listKos({
      kb_id: filters.kb_id || undefined,
      status: filters.status || undefined,
      ko_type: filters.ko_type || undefined,
      keyword: filters.keyword.trim() || undefined,
      owner_id: filters.mine ? auth.profile?.id : undefined,
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

function open(ko: KnowledgeObject): void {
  void router.push({ name: 'curation-ko', params: { koId: ko.id } })
}

// ---- create ---------------------------------------------------------------------

const createDialog = ref(false)
const creating = ref(false)
const createForm = reactive({ kb_id: '', ko_type: 'faq' as KoType, question: '' })

async function submitCreate(): Promise<void> {
  if (!createForm.kb_id || !createForm.question.trim()) {
    ElMessage.warning('请选择知识库并填写标准问题')
    return
  }
  creating.value = true
  try {
    const ko = await createKo({
      kb_id: createForm.kb_id,
      ko_type: createForm.ko_type,
      question: createForm.question.trim(),
      variants: [],
      answer: '',
      sources: [],
    })
    createDialog.value = false
    await router.push({ name: 'curation-ko', params: { koId: ko.id } })
  } finally {
    creating.value = false
  }
}

// ---- FAQ from document ----------------------------------------------------------

const faqDialog = ref(false)
const generating = ref(false)
const faqForm = reactive({
  kb_id: null as string | null,
  document_ids: [] as string[],
  max_items: 5,
  ko_type: 'faq' as KoType,
})

async function submitFaq(): Promise<void> {
  const [documentId] = faqForm.document_ids
  if (!documentId) {
    ElMessage.warning('请选择文档')
    return
  }
  generating.value = true
  try {
    const created = await generateFaq(documentId, faqForm.max_items, faqForm.ko_type)
    faqDialog.value = false
    ElMessage.success(`已生成 ${created.length} 条草稿，请逐条审阅后提交审核`)
    filters.status = 'draft'
    search()
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  void load()
  kbOptions.value = (await listKnowledgeBases({ page: 1, size: 100 })).items
})
</script>

<template>
  <el-card shadow="never">
    <el-form inline @submit.prevent="search">
      <el-form-item label="知识库">
        <el-select
          v-model="filters.kb_id"
          clearable
          filterable
          placeholder="全部"
          style="width: 180px"
          @change="search"
        >
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="状态">
        <el-select
          v-model="filters.status"
          clearable
          placeholder="全部"
          style="width: 120px"
          @change="search"
        >
          <el-option
            v-for="(meta, key) in KO_STATUS_META"
            :key="key"
            :label="meta.label"
            :value="key"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="类型">
        <el-select
          v-model="filters.ko_type"
          clearable
          placeholder="全部"
          style="width: 120px"
          @change="search"
        >
          <el-option v-for="(label, key) in KO_TYPE_LABEL" :key="key" :label="label" :value="key" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-input
          v-model="filters.keyword"
          placeholder="搜索标题/问题"
          clearable
          style="width: 200px"
          @clear="search"
        />
      </el-form-item>
      <el-form-item>
        <el-checkbox v-model="filters.mine" @change="search">我负责的</el-checkbox>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
        <template v-if="auth.can('ko:edit')">
          <el-button @click="createDialog = true">新建条目</el-button>
          <el-button @click="faqDialog = true">从文档生成 FAQ</el-button>
        </template>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="items" row-key="id" @row-click="open">
      <el-table-column label="标题 / 标准问题" min-width="280">
        <template #default="{ row }">
          <div class="ko-title">{{ row.title }}</div>
          <div class="muted">{{ row.question }}</div>
        </template>
      </el-table-column>
      <el-table-column label="类型" width="100">
        <template #default="{ row }">{{ KO_TYPE_LABEL[row.ko_type as KoType] }}</template>
      </el-table-column>
      <el-table-column label="状态" width="150">
        <template #default="{ row }">
          <el-tag :type="metaOf(KO_STATUS_META, row.status).type" size="small">
            {{ metaOf(KO_STATUS_META, row.status).label }}
          </el-tag>
          <el-tag
            v-if="row.published_version && row.status !== 'published'"
            type="success"
            size="small"
            effect="plain"
            class="ko-live"
          >
            v{{ row.published_version }} 在线
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="冲突" width="70" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.conflict_count" type="danger" size="small">
            {{ row.conflict_count }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="70" align="center">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="知识库" prop="kb_name" width="140" />
      <el-table-column label="来源" width="100">
        <template #default="{ row }">{{ ORIGIN_LABEL[row.origin] ?? row.origin }}</template>
      </el-table-column>
      <el-table-column label="负责人" width="100">
        <template #default="{ row }">{{ row.owner?.name ?? '-' }}</template>
      </el-table-column>
      <el-table-column label="失效时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.effective_to) }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
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

    <el-dialog v-model="createDialog" title="新建知识条目" width="520px">
      <el-form label-width="80px">
        <el-form-item label="知识库" required>
          <el-select v-model="createForm.kb_id" filterable style="width: 100%">
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="createForm.ko_type">
            <el-radio-button v-for="(label, key) in KO_TYPE_LABEL" :key="key" :value="key">
              {{ label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标准问题" required>
          <el-input v-model="createForm.question" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="faqDialog" title="从文档批量生成 FAQ" width="560px">
      <el-form label-width="96px">
        <el-form-item label="知识库">
          <el-select v-model="faqForm.kb_id" filterable style="width: 100%">
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档" required>
          <DocumentPicker v-model="faqForm.document_ids" :kb-id="faqForm.kb_id" :multiple="false" />
        </el-form-item>
        <el-form-item label="最多条数">
          <el-input-number v-model="faqForm.max_items" :min="1" :max="20" />
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="faqForm.ko_type">
            <el-radio-button v-for="(label, key) in KO_TYPE_LABEL" :key="key" :value="key">
              {{ label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="faqDialog = false">取消</el-button>
        <el-button type="primary" :loading="generating" @click="submitFaq">生成</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.ko-title {
  font-weight: 500;
}

.ko-live {
  margin-left: 4px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
