<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import {
  getDocument,
  getPreviewUrl,
  listChunks,
  reprocessDocument,
  updateDocument,
} from '@/api/knowledge'
import type { Chunk, DocumentDetail, Preview } from '@/api/types'
import ChunkViewer from '@/components/knowledge/ChunkViewer.vue'
import { useAuthStore } from '@/stores/auth'
import { atLeast, documentStatus } from '@/utils/document'
import { fileExtension, formatBytes } from '@/utils/file'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ kbId: string; docId: string }>()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const POLL_INTERVAL_MS = 3000
const INLINE_EXTENSIONS = ['.pdf', '.txt', '.md', '.markdown', '.csv', '.html', '.htm']

const doc = ref<DocumentDetail | null>(null)
const chunks = ref<Chunk[]>([])
const preview = ref<Preview | null>(null)
const loadingChunks = ref(false)
const tab = ref('chunks')
let timer: ReturnType<typeof setTimeout> | null = null

const status = computed(() => (doc.value ? documentStatus(doc.value) : null))
const canEdit = computed(() => auth.can('doc:upload') && atLeast(doc.value?.my_permission, 'edit'))
const inlinePreview = computed(
  () => !!doc.value && INLINE_EXTENSIONS.includes(fileExtension(doc.value.filename)),
)
// Uploaded HTML is untrusted: render it without scripts. (PDF viewers refuse sandboxed frames.)
const isHtml = computed(
  () => !!doc.value && ['.html', '.htm'].includes(fileExtension(doc.value.filename)),
)
// Deep links from search results: ?chunk=<id>&page=<n>
const focusChunk = computed(() =>
  typeof route.query.chunk === 'string' ? route.query.chunk : null,
)
const focusPage = computed(() => {
  const page = Number(route.query.page)
  return Number.isInteger(page) && page > 0 ? page : null
})
const isPdf = computed(() => !!doc.value && fileExtension(doc.value.filename) === '.pdf')
const previewSrc = computed(() => {
  if (!preview.value) return ''
  return isPdf.value && focusPage.value
    ? `${preview.value.url}#page=${focusPage.value}`
    : preview.value.url
})
const parseInfo = computed(
  () => (doc.value?.metadata?.parse as Record<string, unknown> | undefined) ?? null,
)

async function loadDocument(): Promise<void> {
  const previous = doc.value
  doc.value = await getDocument(props.docId)
  const changed =
    !previous ||
    previous.version !== doc.value.version ||
    previous.chunk_count !== doc.value.chunk_count
  if (changed) {
    await Promise.all([loadChunks(), loadPreview()])
  }
  schedulePoll()
}

async function loadChunks(): Promise<void> {
  loadingChunks.value = true
  try {
    chunks.value = await listChunks(props.docId)
  } finally {
    loadingChunks.value = false
  }
}

async function loadPreview(): Promise<void> {
  preview.value = await getPreviewUrl(props.docId)
}

function schedulePoll(): void {
  if (timer) clearTimeout(timer)
  timer = status.value?.active ? setTimeout(() => void loadDocument(), POLL_INTERVAL_MS) : null
}

async function reprocess(): Promise<void> {
  await reprocessDocument(props.docId)
  ElMessage.success('已重新提交处理')
  await loadDocument()
}

// ---- metadata editor ---------------------------------------------------------------

const editor = reactive({
  visible: false,
  saving: false,
  title: '',
  tags: [] as string[],
  effective: null as [string, string] | null,
})

function openEditor(): void {
  if (!doc.value) return
  editor.title = doc.value.title
  editor.tags = [...doc.value.tags]
  editor.effective =
    doc.value.effective_from && doc.value.effective_to
      ? [doc.value.effective_from, doc.value.effective_to]
      : null
  editor.visible = true
}

async function saveEditor(): Promise<void> {
  editor.saving = true
  try {
    await updateDocument(props.docId, {
      title: editor.title,
      tags: editor.tags,
      effective_from: editor.effective?.[0] ?? null,
      effective_to: editor.effective?.[1] ?? null,
    })
    ElMessage.success('保存成功')
    editor.visible = false
    await loadDocument()
  } finally {
    editor.saving = false
  }
}

watch(() => props.docId, loadDocument)
onMounted(loadDocument)
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="doc-detail">
    <el-card shadow="never">
      <div class="header">
        <div class="title-block">
          <el-button
            link
            :icon="ArrowLeft"
            @click="router.push({ name: 'knowledge-base', params: { kbId } })"
          >
            {{ doc?.kb_name ?? '返回' }}
          </el-button>
          <h2 class="title">{{ doc?.title ?? '...' }}</h2>
          <el-tag v-if="doc" effect="plain">v{{ doc.version }}</el-tag>
          <el-tag v-if="status" :type="status.type">{{ status.label }}</el-tag>
        </div>
        <div class="actions">
          <el-button v-if="canEdit" @click="openEditor">编辑信息</el-button>
          <el-button v-if="canEdit" :disabled="doc?.status === 'parsing'" @click="reprocess">
            重新处理
          </el-button>
          <el-button v-if="preview" tag="a" :href="preview.url" target="_blank">下载原文</el-button>
        </div>
      </div>
      <el-progress
        v-if="status?.active"
        :percentage="status.progress"
        :stroke-width="6"
        class="progress"
      />
      <el-alert
        v-if="doc?.status === 'failed'"
        type="error"
        :closable="false"
        show-icon
        :title="doc.error_message ?? '处理失败'"
        class="progress"
      />
    </el-card>

    <div class="body">
      <el-card shadow="never" class="preview-card" body-class="preview-body">
        <template #header>原文预览</template>
        <iframe
          v-if="preview && inlinePreview"
          :key="previewSrc"
          :src="previewSrc"
          class="preview-frame"
          :sandbox="isHtml ? '' : undefined"
          title="preview"
        />
        <el-empty
          v-else-if="preview"
          description="该格式暂不支持在线预览，请下载原文查看，或在右侧查看解析后的分块"
        />
      </el-card>

      <el-card shadow="never" class="side-card">
        <el-tabs v-model="tab">
          <el-tab-pane label="分块" name="chunks">
            <ChunkViewer :chunks="chunks" :loading="loadingChunks" :focus="focusChunk" />
          </el-tab-pane>
          <el-tab-pane label="文档信息" name="info">
            <el-descriptions v-if="doc" :column="1" border size="small">
              <el-descriptions-item label="文件名">{{ doc.filename }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ doc.mime_type }}</el-descriptions-item>
              <el-descriptions-item label="大小">{{
                formatBytes(doc.size_bytes)
              }}</el-descriptions-item>
              <el-descriptions-item label="SHA-256">
                <span class="mono">{{ doc.sha256 }}</span>
              </el-descriptions-item>
              <el-descriptions-item label="标签">
                <el-tag v-for="t in doc.tags" :key="t" size="small" class="tag">{{ t }}</el-tag>
                <span v-if="!doc.tags.length">-</span>
              </el-descriptions-item>
              <el-descriptions-item label="生效时间">
                {{ formatDateTime(doc.effective_from) }} ~ {{ formatDateTime(doc.effective_to) }}
              </el-descriptions-item>
              <el-descriptions-item label="权限">
                {{ doc.acl_inherit ? '继承知识库' : '单独设置' }}
              </el-descriptions-item>
              <el-descriptions-item label="解析器">
                {{ parseInfo?.parser ?? '-' }}
              </el-descriptions-item>
              <el-descriptions-item v-if="parseInfo?.pages" label="页数">
                {{ parseInfo.pages }}
              </el-descriptions-item>
              <el-descriptions-item
                v-if="
                  Array.isArray(parseInfo?.ocr_pages) && (parseInfo.ocr_pages as number[]).length
                "
                label="OCR 页"
              >
                {{ (parseInfo.ocr_pages as number[]).join(', ') }}
              </el-descriptions-item>
              <el-descriptions-item label="分块数">{{
                doc.chunk_count ?? '-'
              }}</el-descriptions-item>
              <el-descriptions-item label="解析时间">{{
                formatDateTime(doc.parsed_at)
              }}</el-descriptions-item>
              <el-descriptions-item label="切分时间">{{
                formatDateTime(doc.chunked_at)
              }}</el-descriptions-item>
              <el-descriptions-item label="上传时间">{{
                formatDateTime(doc.created_at)
              }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
          <el-tab-pane label="版本历史" name="versions">
            <el-table :data="doc?.versions ?? []" size="small">
              <el-table-column label="版本" width="70">
                <template #default="{ row }">v{{ row.version }}</template>
              </el-table-column>
              <el-table-column prop="filename" label="文件名" min-width="140" />
              <el-table-column label="大小" width="90">
                <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
              </el-table-column>
              <el-table-column label="上传时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>

    <el-dialog v-model="editor.visible" title="编辑文档信息" width="520px">
      <el-form label-width="80px">
        <el-form-item label="标题">
          <el-input v-model="editor.title" maxlength="512" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select
            v-model="editor.tags"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入后回车添加"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="生效期">
          <el-date-picker
            v-model="editor.effective"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            start-placeholder="生效时间"
            end-placeholder="失效时间"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button type="primary" :loading="editor.saving" @click="saveEditor">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.doc-detail {
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
  min-width: 0;
}
.title {
  margin: 0;
  font-size: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.progress {
  margin-top: 12px;
}
.body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.preview-card :deep(.preview-body) {
  padding: 0;
}
.preview-frame {
  width: 100%;
  height: calc(100vh - 260px);
  min-height: 480px;
  border: 0;
  display: block;
}
.side-card {
  max-height: calc(100vh - 200px);
  overflow: auto;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  word-break: break-all;
}
.tag {
  margin-right: 4px;
}
@media (max-width: 1200px) {
  .body {
    grid-template-columns: 1fr;
  }
}
</style>
