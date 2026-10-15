<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { deleteDocument, getKnowledgeBase, listDocuments, reprocessDocument } from '@/api/knowledge'
import type { DocumentStatus, KbDocument, KnowledgeBase } from '@/api/types'
import DocumentAclDialog from '@/components/knowledge/DocumentAclDialog.vue'
import DocumentUploader from '@/components/knowledge/DocumentUploader.vue'
import KbAclDialog from '@/components/knowledge/KbAclDialog.vue'
import KbFormDialog from '@/components/knowledge/KbFormDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { PERMISSION_LABELS, atLeast, documentStatus } from '@/utils/document'
import { formatBytes } from '@/utils/file'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ kbId: string }>()
const router = useRouter()
const auth = useAuthStore()

const POLL_INTERVAL_MS = 3000
const STATUS_OPTIONS: { value: DocumentStatus; label: string }[] = [
  { value: 'uploaded', label: '排队中' },
  { value: 'parsing', label: '解析中' },
  { value: 'parsed', label: '已解析' },
  { value: 'failed', label: '失败' },
]

const kb = ref<KnowledgeBase | null>(null)
const query = reactive({ keyword: '', status: '' as DocumentStatus | '', page: 1, size: 20 })
const rows = ref<KbDocument[]>([])
const total = ref(0)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

const canEdit = computed(() => atLeast(kb.value?.my_permission, 'edit'))
const canManage = computed(() => atLeast(kb.value?.my_permission, 'manage'))
const canUpload = computed(() => canEdit.value && auth.can('doc:upload'))

async function loadKb(): Promise<void> {
  kb.value = await getKnowledgeBase(props.kbId)
}

async function loadDocuments(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const page = await listDocuments(props.kbId, {
      page: query.page,
      size: query.size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
    })
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
    schedulePoll()
  }
}

function schedulePoll(): void {
  if (timer) clearTimeout(timer)
  timer = null
  if (rows.value.some((d) => documentStatus(d).active)) {
    timer = setTimeout(() => void loadDocuments(true), POLL_INTERVAL_MS)
  }
}

function search(): void {
  query.page = 1
  void loadDocuments()
}

// ---- dialogs ---------------------------------------------------------------------

const uploadVisible = ref(false)
const kbForm = ref(false)
const kbAcl = ref(false)
const docAcl = reactive({ visible: false, document: null as KbDocument | null })

function openDocAcl(doc: KbDocument): void {
  docAcl.document = doc
  docAcl.visible = true
}

function onUploaded(): void {
  void loadDocuments(true)
}

// ---- document actions --------------------------------------------------------------

function openDocument(doc: KbDocument): void {
  void router.push({ name: 'knowledge-document', params: { kbId: props.kbId, docId: doc.id } })
}

async function reprocess(doc: KbDocument): Promise<void> {
  await reprocessDocument(doc.id)
  ElMessage.success('已重新提交处理')
  await loadDocuments(true)
}

async function remove(doc: KbDocument): Promise<void> {
  await ElMessageBox.confirm(`确定下线并删除文档「${doc.title}」吗？`, '提示', {
    type: 'warning',
  })
  await deleteDocument(doc.id)
  ElMessage.success('已删除')
  await Promise.all([loadDocuments(), loadKb()])
}

watch(
  () => props.kbId,
  async () => {
    query.page = 1
    await Promise.all([loadKb(), loadDocuments()])
  },
)

onMounted(async () => {
  await Promise.all([loadKb(), loadDocuments()])
})

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="kb-detail">
    <el-card shadow="never" class="header-card">
      <div class="header">
        <div class="title-block">
          <el-button link :icon="ArrowLeft" @click="router.push({ name: 'knowledge' })">
            返回
          </el-button>
          <h2 class="title">{{ kb?.name ?? '...' }}</h2>
          <el-tag v-if="kb" :type="kb.visibility === 'org' ? 'success' : 'info'" effect="plain">
            {{ kb.visibility === 'org' ? '组织内可读' : '仅授权成员' }}
          </el-tag>
          <el-tag v-if="kb?.my_permission" effect="plain">
            我的权限：{{ PERMISSION_LABELS[kb.my_permission] }}
          </el-tag>
        </div>
        <div class="actions">
          <el-button
            v-if="canUpload"
            type="primary"
            data-test="open-upload"
            data-guide="kb-upload"
            @click="uploadVisible = true"
          >
            上传文档
          </el-button>
          <template v-if="canManage && auth.can('kb:update')">
            <el-button @click="kbForm = true">编辑</el-button>
            <el-button data-guide="kb-acl" @click="kbAcl = true">权限设置</el-button>
          </template>
        </div>
      </div>
      <p v-if="kb?.description" class="description">{{ kb.description }}</p>
    </el-card>

    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="search">
        <el-form-item>
          <el-input v-model="query.keyword" placeholder="标题 / 文件名" clearable />
        </el-form-item>
        <el-form-item>
          <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 130px">
            <el-option
              v-for="s in STATUS_OPTIONS"
              :key="s.value"
              :label="s.label"
              :value="s.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
          <el-button @click="loadDocuments()">刷新</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="rows" data-guide="kb-docs" empty-text="暂无文档">
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="openDocument(row as KbDocument)">
              {{ (row as KbDocument).title }}
            </el-link>
            <div class="sub">{{ (row as KbDocument).filename }}</div>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="90">
          <template #default="{ row }">{{ formatBytes((row as KbDocument).size_bytes) }}</template>
        </el-table-column>
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ (row as KbDocument).version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="200">
          <template #default="{ row }">
            <div class="status">
              <el-tag :type="documentStatus(row as KbDocument).type" size="small">
                {{ documentStatus(row as KbDocument).label }}
              </el-tag>
              <el-progress
                v-if="documentStatus(row as KbDocument).active"
                :percentage="documentStatus(row as KbDocument).progress"
                :stroke-width="6"
                :show-text="false"
                class="progress"
              />
            </div>
            <el-tooltip
              v-if="(row as KbDocument).status === 'failed' && (row as KbDocument).error_message"
              :content="(row as KbDocument).error_message!"
              placement="top"
            >
              <div class="error">{{ (row as KbDocument).error_message }}</div>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="分块" width="70">
          <template #default="{ row }">{{ (row as KbDocument).chunk_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="标签" min-width="120">
          <template #default="{ row }">
            <el-tag
              v-for="tag in (row as KbDocument).tags"
              :key="tag"
              size="small"
              effect="plain"
              class="tag"
            >
              {{ tag }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="权限" width="90">
          <template #default="{ row }">
            <span class="sub">{{ (row as KbDocument).acl_inherit ? '继承' : '单独设置' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="165">
          <template #default="{ row }">{{
            formatDateTime((row as KbDocument).updated_at)
          }}</template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDocument(row as KbDocument)">详情</el-button>
            <el-button
              v-if="auth.can('doc:upload') && atLeast((row as KbDocument).my_permission, 'edit')"
              link
              type="primary"
              :disabled="(row as KbDocument).status === 'parsing'"
              @click="reprocess(row as KbDocument)"
            >
              重新处理
            </el-button>
            <el-button
              v-if="atLeast((row as KbDocument).my_permission, 'manage')"
              link
              type="primary"
              @click="openDocAcl(row as KbDocument)"
            >
              权限
            </el-button>
            <el-button
              v-if="auth.can('doc:delete') && atLeast((row as KbDocument).my_permission, 'edit')"
              link
              type="danger"
              @click="remove(row as KbDocument)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="query.page"
        v-model:page-size="query.size"
        class="pager"
        layout="total, sizes, prev, pager, next"
        :total="total"
        @current-change="loadDocuments()"
        @size-change="search"
      />
    </el-card>

    <el-dialog v-model="uploadVisible" title="上传文档" width="640px">
      <DocumentUploader :kb-id="kbId" @uploaded="onUploaded" />
    </el-dialog>
    <KbFormDialog v-model="kbForm" :kb="kb" @saved="loadKb" />
    <KbAclDialog v-model="kbAcl" :kb="kb" @saved="loadKb" />
    <DocumentAclDialog
      v-model="docAcl.visible"
      :document="docAcl.document"
      @saved="loadDocuments(true)"
    />
  </div>
</template>

<style scoped>
.kb-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.title-block {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title {
  margin: 0;
  font-size: 18px;
}
.description {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
}
.sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.status {
  display: flex;
  align-items: center;
  gap: 8px;
}
.progress {
  flex: 1;
}
.error {
  color: var(--el-color-danger);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}
.tag {
  margin: 0 4px 4px 0;
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
