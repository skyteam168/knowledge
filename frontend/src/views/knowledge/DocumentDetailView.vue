<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import {
  getDocument,
  getDownloadUrl,
  getPreviewUrl,
  getVersionDownloadUrl,
  listChunks,
  reprocessDocument,
  restoreVersion,
  reviewDocument,
  searchPrincipals,
  updateDocument,
} from '@/api/knowledge'
import type {
  AclPermission,
  Chunk,
  DocumentDetail,
  DocumentVersion,
  Preview,
  PrincipalOption,
} from '@/api/types'
import ChunkViewer from '@/components/knowledge/ChunkViewer.vue'
import ProtectedArea from '@/components/knowledge/ProtectedArea.vue'
import VersionCompareDialog from '@/components/knowledge/VersionCompareDialog.vue'
import VersionViewDialog from '@/components/knowledge/VersionViewDialog.vue'
import { useAuthStore } from '@/stores/auth'
import {
  REVIEW_INTERVALS,
  atLeast,
  documentStatus,
  inlinePreviewable,
  isHtmlFile,
  reviewIntervalLabel,
  reviewStatus,
} from '@/utils/document'
import { fileExtension, formatBytes } from '@/utils/file'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ kbId: string; docId: string }>()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t } = useI18n()

const POLL_INTERVAL_MS = 3000

const doc = ref<DocumentDetail | null>(null)
const chunks = ref<Chunk[]>([])
const preview = ref<Preview | null>(null)
const loadingChunks = ref(false)
const tab = ref('chunks')
let timer: ReturnType<typeof setTimeout> | null = null

const status = computed(() => (doc.value ? documentStatus(doc.value) : null))
const canEdit = computed(() => auth.can('doc:upload') && atLeast(doc.value?.my_permission, 'edit'))
const canManage = computed(() => atLeast(doc.value?.my_permission, 'manage'))
const protection = computed(() => doc.value?.protection ?? null)
const isProtected = computed(
  () =>
    !!protection.value &&
    (protection.value.watermark ||
      protection.value.copy_protect ||
      protection.value.download_permission !== 'read'),
)
const pagesBox = ref<HTMLElement>()
const inlinePreview = computed(() => !!doc.value && inlinePreviewable(doc.value.filename))
const isHtml = computed(() => !!doc.value && isHtmlFile(doc.value.filename))
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
  if (!preview.value?.url) return ''
  return isPdf.value && focusPage.value
    ? `${preview.value.url}#page=${focusPage.value}`
    : preview.value.url
})
const showFile = computed(() => preview.value?.mode === 'file' && inlinePreview.value)
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
  if (preview.value.mode === 'pages' && focusPage.value) {
    await nextTick()
    pagesBox.value
      ?.querySelector<HTMLElement>(`[data-page="${focusPage.value}"]`)
      ?.scrollIntoView({ block: 'start' })
  }
}

async function download(): Promise<void> {
  const file = await getDownloadUrl(props.docId)
  if (file.url) window.location.assign(file.url)
}

function schedulePoll(): void {
  if (timer) clearTimeout(timer)
  timer = status.value?.active ? setTimeout(() => void loadDocument(), POLL_INTERVAL_MS) : null
}

async function reprocess(): Promise<void> {
  await reprocessDocument(props.docId)
  ElMessage.success(t('knowledge.doc.reprocessed'))
  await loadDocument()
}

// ---- review ------------------------------------------------------------------------

const review = computed(() => (doc.value ? reviewStatus(doc.value.review_state) : null))
const needsReview = computed(() =>
  ['due_soon', 'overdue'].includes(doc.value?.review_state ?? 'none'),
)

async function confirmReview(): Promise<void> {
  const { value } = await ElMessageBox.prompt(
    t('knowledge.review.confirmPrompt'),
    t('knowledge.review.confirm'),
    { inputPlaceholder: t('knowledge.review.notePlaceholder'), inputValidator: () => true },
  )
  const updated = await reviewDocument(props.docId, value)
  ElMessage.success(
    t('knowledge.review.confirmed', { date: formatDateTime(updated.review_due_at) }),
  )
  await loadDocument()
}

// ---- versions ----------------------------------------------------------------------

const viewing = ref<DocumentVersion | null>(null)
const comparing = ref<[number, number] | null>(null)
const versions = computed(() => doc.value?.versions ?? [])

/** Compare `version` (default: the latest) with the version before it (newest first list). */
function openCompare(version?: number): void {
  const list = versions.value
  if (list.length < 2) return
  const at = Math.max(
    0,
    list.findIndex((v) => v.version === version),
  )
  const [older, newer] = at < list.length - 1 ? [list[at + 1], list[at]] : [list[at], list[at - 1]]
  comparing.value = [older.version, newer.version]
}

async function downloadVersion(version: number): Promise<void> {
  const file = await getVersionDownloadUrl(props.docId, version)
  if (file.url) window.location.assign(file.url)
}

async function restore(version: number): Promise<void> {
  if (!doc.value) return
  await ElMessageBox.confirm(
    t('knowledge.version.restoreConfirm', { from: version, to: doc.value.version + 1 }),
    t('knowledge.version.restoreTitle'),
    { type: 'warning' },
  )
  const restored = await restoreVersion(props.docId, version)
  ElMessage.success(t('knowledge.version.restored', { n: restored.version }))
  await loadDocument()
}

// ---- metadata editor ---------------------------------------------------------------

/** Select value for "no own setting, as the knowledge base" (options cannot be null). */
const INHERIT = 'inherit' as const

const editor = reactive({
  visible: false,
  saving: false,
  title: '',
  tags: [] as string[],
  effective: null as [string, string] | null,
  watermark: INHERIT as typeof INHERIT | 'on',
  copyProtect: INHERIT as typeof INHERIT | 'on',
  download: INHERIT as typeof INHERIT | AclPermission,
  ownerId: '',
  /** inherit = as the knowledge base, 0 = never, otherwise days. */
  reviewInterval: INHERIT as typeof INHERIT | number,
})
const ownerOptions = ref<PrincipalOption[]>([])
const searchingOwner = ref(false)

async function searchOwner(keyword: string): Promise<void> {
  searchingOwner.value = true
  try {
    ownerOptions.value = await searchPrincipals('user', keyword || undefined)
  } finally {
    searchingOwner.value = false
  }
}

function openEditor(): void {
  if (!doc.value) return
  editor.title = doc.value.title
  editor.tags = [...doc.value.tags]
  editor.ownerId = doc.value.owner_id ?? ''
  ownerOptions.value = doc.value.owner_id
    ? [
        {
          type: 'user',
          id: doc.value.owner_id,
          name: doc.value.owner_name ?? doc.value.owner_id,
          description: null,
        },
      ]
    : []
  editor.reviewInterval = doc.value.review_interval_days ?? INHERIT
  editor.watermark = doc.value.watermark ? 'on' : INHERIT
  editor.copyProtect = doc.value.copy_protect ? 'on' : INHERIT
  editor.download = doc.value.download_permission ?? INHERIT
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
      owner_id: editor.ownerId || null,
      review_interval_days: editor.reviewInterval === INHERIT ? null : editor.reviewInterval,
      ...(canManage.value
        ? {
            watermark: editor.watermark === 'on' ? true : null,
            copy_protect: editor.copyProtect === 'on' ? true : null,
            download_permission: editor.download === INHERIT ? null : editor.download,
          }
        : {}),
    })
    ElMessage.success(t('knowledge.kb.savedSuccess'))
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
            {{ doc?.kb_name ?? t('common.back') }}
          </el-button>
          <h2 class="title">{{ doc?.title ?? '...' }}</h2>
          <el-tag v-if="doc" effect="plain">v{{ doc.version }}</el-tag>
          <el-tag v-if="status" :type="status.type">{{ status.label }}</el-tag>
          <el-tooltip v-if="isProtected && protection" placement="bottom">
            <template #content>
              <div v-if="protection.watermark">{{ t('knowledge.protect.watermarkOn') }}</div>
              <div v-if="protection.copy_protect">{{ t('knowledge.protect.copyOn') }}</div>
              <div>
                {{
                  t('knowledge.protect.downloadBy', {
                    level: t(`knowledge.protect.download.${protection.download_permission}`),
                  })
                }}
              </div>
            </template>
            <el-tag type="warning" effect="plain" data-test="doc-protected">{{
              t('knowledge.protect.tag')
            }}</el-tag>
          </el-tooltip>
          <el-tag v-if="needsReview && review" :type="review.type" data-test="doc-review-state">{{
            review.label
          }}</el-tag>
        </div>
        <div class="actions">
          <el-button
            v-if="canEdit && doc?.review_interval"
            :type="needsReview ? 'warning' : 'default'"
            data-test="doc-confirm-review"
            @click="confirmReview"
            >{{ t('knowledge.review.confirm') }}</el-button
          >
          <el-button v-if="canEdit" @click="openEditor">{{
            t('knowledge.doc.editInfo')
          }}</el-button>
          <el-button v-if="canEdit" :disabled="doc?.status === 'parsing'" @click="reprocess">
            {{ t('knowledge.doc.reprocess') }}
          </el-button>
          <el-button v-if="doc?.can_download" data-test="doc-download" @click="download">{{
            t('knowledge.doc.download')
          }}</el-button>
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
        :title="doc.error_message ?? t('knowledge.doc.processFailed')"
        class="progress"
      />
    </el-card>

    <!-- Page images carry a server-side watermark; the overlay covers the text side panel. -->
    <ProtectedArea class="body" :copy-protect="protection?.copy_protect">
      <el-card shadow="never" class="preview-card" body-class="preview-body">
        <template #header>{{ t('knowledge.doc.preview') }}</template>
        <iframe
          v-if="preview && showFile"
          :key="previewSrc"
          :src="previewSrc"
          class="preview-frame"
          :sandbox="isHtml ? '' : undefined"
          title="preview"
        />
        <div
          v-else-if="preview?.mode === 'pages'"
          ref="pagesBox"
          class="preview-pages"
          data-test="preview-pages"
        >
          <img
            v-for="page in preview.pages"
            :key="page.url"
            :src="page.url"
            :data-page="page.index"
            :alt="t('knowledge.protect.pageAlt', { n: page.index })"
            loading="lazy"
            draggable="false"
            class="preview-page"
          />
        </div>
        <el-empty
          v-else-if="preview?.mode === 'none'"
          :description="t('knowledge.protect.textOnly')"
        />
        <el-empty v-else-if="preview" :description="t('knowledge.doc.previewUnsupported')" />
      </el-card>

      <ProtectedArea :watermark="protection?.watermark" class="side-card">
        <el-card shadow="never" class="side-card__inner">
          <el-tabs v-model="tab">
            <el-tab-pane :label="t('knowledge.doc.chunks')" name="chunks">
              <ChunkViewer :chunks="chunks" :loading="loadingChunks" :focus="focusChunk" />
            </el-tab-pane>
            <el-tab-pane :label="t('knowledge.doc.info')" name="info">
              <el-descriptions v-if="doc" :column="1" border size="small">
                <el-descriptions-item :label="t('knowledge.doc.filename')">{{
                  doc.filename
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.type')">{{
                  doc.mime_type
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.size')">{{
                  formatBytes(doc.size_bytes)
                }}</el-descriptions-item>
                <el-descriptions-item label="SHA-256">
                  <span class="mono">{{ doc.sha256 }}</span>
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.tags')">
                  <el-tag v-for="tag in doc.tags" :key="tag" size="small" class="tag">{{
                    tag
                  }}</el-tag>
                  <span v-if="!doc.tags.length">-</span>
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.effectiveTime')">
                  {{ formatDateTime(doc.effective_from) }} ~ {{ formatDateTime(doc.effective_to) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.review.owner')">
                  {{ doc.owner_name ?? t('knowledge.review.ownerNone') }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.review.interval')">
                  {{ reviewIntervalLabel(doc.review_interval) }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.review.lastReviewed')">
                  {{ formatDateTime(doc.reviewed_at) }}
                </el-descriptions-item>
                <el-descriptions-item
                  v-if="doc.review_due_at"
                  :label="t('knowledge.review.nextReview')"
                >
                  {{ formatDateTime(doc.review_due_at) }}
                  <el-tag v-if="review" :type="review.type" size="small" class="tag-gap">{{
                    review.label
                  }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.permission')">
                  {{ doc.acl_inherit ? t('knowledge.acl.inheritKb') : t('knowledge.acl.custom') }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.parser')">
                  {{ parseInfo?.parser ?? '-' }}
                </el-descriptions-item>
                <el-descriptions-item v-if="parseInfo?.pages" :label="t('knowledge.doc.pages')">
                  {{ parseInfo.pages }}
                </el-descriptions-item>
                <el-descriptions-item
                  v-if="
                    Array.isArray(parseInfo?.ocr_pages) && (parseInfo.ocr_pages as number[]).length
                  "
                  :label="t('knowledge.doc.ocrPages')"
                >
                  {{ (parseInfo.ocr_pages as number[]).join(', ') }}
                </el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.chunkCount')">{{
                  doc.chunk_count ?? '-'
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.parsedAt')">{{
                  formatDateTime(doc.parsed_at)
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.chunkedAt')">{{
                  formatDateTime(doc.chunked_at)
                }}</el-descriptions-item>
                <el-descriptions-item :label="t('knowledge.doc.uploadedAt')">{{
                  formatDateTime(doc.created_at)
                }}</el-descriptions-item>
              </el-descriptions>
            </el-tab-pane>
            <el-tab-pane :label="t('knowledge.doc.versions')" name="versions">
              <div v-if="versions.length > 1" class="versions-bar">
                <el-button size="small" data-test="versions-compare" @click="openCompare()">{{
                  t('knowledge.version.compareTitle')
                }}</el-button>
              </div>
              <el-table :data="versions" size="small" data-test="versions-table">
                <el-table-column :label="t('knowledge.doc.version')" min-width="120">
                  <template #default="{ row }">
                    <span class="mono">v{{ row.version }}</span>
                    <el-tag
                      v-if="row.version === doc?.version"
                      size="small"
                      type="success"
                      class="tag-gap"
                      >{{ t('knowledge.version.current') }}</el-tag
                    >
                    <el-tag v-if="row.restored_from" size="small" type="info" class="tag-gap">{{
                      t('knowledge.version.restoredFrom', { n: row.restored_from })
                    }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column :label="t('knowledge.doc.size')" width="80">
                  <template #default="{ row }">{{ formatBytes(row.size_bytes) }}</template>
                </el-table-column>
                <el-table-column :label="t('knowledge.version.uploader')" min-width="130">
                  <template #default="{ row }">
                    <div>{{ row.created_by_name ?? '-' }}</div>
                    <div class="version-time">{{ formatDateTime(row.created_at) }}</div>
                  </template>
                </el-table-column>
                <el-table-column :label="t('knowledge.version.actions')" width="190">
                  <template #default="{ row }">
                    <el-button
                      link
                      type="primary"
                      size="small"
                      @click="viewing = row as DocumentVersion"
                      >{{ t('knowledge.version.view') }}</el-button
                    >
                    <el-button
                      v-if="versions.length > 1"
                      link
                      type="primary"
                      size="small"
                      @click="openCompare(row.version)"
                      >{{ t('knowledge.version.compare') }}</el-button
                    >
                    <el-button
                      v-if="doc?.can_download"
                      link
                      type="primary"
                      size="small"
                      @click="downloadVersion(row.version)"
                      >{{ t('knowledge.version.download') }}</el-button
                    >
                    <el-button
                      v-if="canEdit && row.version !== doc?.version"
                      link
                      type="warning"
                      size="small"
                      data-test="version-restore"
                      @click="restore(row.version)"
                      >{{ t('knowledge.version.restore') }}</el-button
                    >
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </ProtectedArea>
    </ProtectedArea>

    <VersionViewDialog
      :doc-id="docId"
      :version="viewing"
      :protection="protection"
      @close="viewing = null"
    />
    <VersionCompareDialog
      :doc-id="docId"
      :versions="versions"
      :pair="comparing"
      :protection="protection"
      @close="comparing = null"
    />

    <el-dialog v-model="editor.visible" :title="t('knowledge.doc.editTitle')" width="520px">
      <el-form label-width="96px">
        <el-form-item :label="t('knowledge.doc.title')">
          <el-input v-model="editor.title" maxlength="512" />
        </el-form-item>
        <el-form-item :label="t('knowledge.doc.tags')">
          <el-select
            v-model="editor.tags"
            multiple
            filterable
            allow-create
            default-first-option
            :placeholder="t('knowledge.doc.tagsPlaceholder')"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item :label="t('knowledge.doc.effectivePeriod')">
          <el-date-picker
            v-model="editor.effective"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            :start-placeholder="t('knowledge.doc.effectiveFrom')"
            :end-placeholder="t('knowledge.doc.effectiveTo')"
          />
        </el-form-item>
        <el-divider content-position="left">{{ t('knowledge.review.title') }}</el-divider>
        <el-form-item :label="t('knowledge.review.owner')">
          <el-select
            v-model="editor.ownerId"
            filterable
            remote
            clearable
            :remote-method="searchOwner"
            :loading="searchingOwner"
            :placeholder="t('knowledge.review.ownerPlaceholder')"
            style="width: 100%"
            data-test="doc-owner"
          >
            <el-option v-for="o in ownerOptions" :key="o.id" :label="o.name" :value="o.id">
              <span>{{ o.name }}</span>
              <span v-if="o.description" class="option-sub">{{ o.description }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item :label="t('knowledge.review.interval')">
          <el-select
            v-model="editor.reviewInterval"
            style="width: 100%"
            data-test="doc-review-interval"
          >
            <el-option
              :label="
                t('knowledge.review.inherit', {
                  label: reviewIntervalLabel(doc?.kb_review_interval_days),
                })
              "
              :value="INHERIT"
            />
            <el-option :label="t('knowledge.review.never')" :value="0" />
            <el-option
              v-for="days in REVIEW_INTERVALS"
              :key="days"
              :label="reviewIntervalLabel(days)"
              :value="days"
            />
          </el-select>
        </el-form-item>
        <div class="protect-hint">{{ t('knowledge.review.ownerHint') }}</div>
        <template v-if="canManage">
          <el-divider content-position="left">{{ t('knowledge.protect.title') }}</el-divider>
          <el-form-item :label="t('knowledge.protect.watermark')">
            <el-select v-model="editor.watermark" style="width: 100%">
              <el-option :label="t('knowledge.protect.inherit')" :value="INHERIT" />
              <el-option :label="t('knowledge.protect.on')" value="on" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('knowledge.protect.copy')">
            <el-select v-model="editor.copyProtect" style="width: 100%">
              <el-option :label="t('knowledge.protect.inherit')" :value="INHERIT" />
              <el-option :label="t('knowledge.protect.on')" value="on" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('knowledge.protect.downloadLabel')">
            <el-select v-model="editor.download" style="width: 100%" data-test="doc-download-level">
              <el-option :label="t('knowledge.protect.inherit')" :value="INHERIT" />
              <el-option :label="t('knowledge.protect.download.edit')" value="edit" />
              <el-option :label="t('knowledge.protect.download.manage')" value="manage" />
            </el-select>
          </el-form-item>
          <div class="protect-hint">{{ t('knowledge.protect.docHint') }}</div>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editor.visible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="editor.saving" @click="saveEditor">{{
          t('common.save')
        }}</el-button>
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
.preview-pages {
  height: calc(100vh - 260px);
  min-height: 480px;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-light);
}
.preview-page {
  display: block;
  width: 100%;
  height: auto;
  margin: 0 auto 12px;
  box-shadow: var(--ekb-shadow-sm);
  background: #fff;
}
.protect-hint {
  margin: -6px 0 0 96px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.side-card__inner {
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
.tag-gap {
  margin-left: 6px;
}
.option-sub {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.version-time {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.versions-bar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
}
@media (max-width: 1200px) {
  .body {
    grid-template-columns: 1fr;
  }
}
</style>
