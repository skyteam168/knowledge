<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getVersionPreviewUrl, getVersionText } from '@/api/knowledge'
import type { DocumentVersion, Preview, Protection, VersionText } from '@/api/types'
import ProtectedArea from '@/components/knowledge/ProtectedArea.vue'
import { inlinePreviewable, isHtmlFile } from '@/utils/document'

/** One older version: its file (or watermarked page images) and its parsed text. */
const props = defineProps<{
  docId: string
  version: DocumentVersion | null
  protection: Protection | null
}>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const tab = ref('preview')
const preview = ref<Preview | null>(null)
const text = ref<VersionText | null>(null)
const loading = ref(false)

const visible = computed({
  get: () => props.version !== null,
  set: (open) => {
    if (!open) emit('close')
  },
})
const showFile = computed(
  () =>
    preview.value?.mode === 'file' &&
    !!preview.value.url &&
    inlinePreviewable(preview.value.filename),
)

watch(
  () => props.version,
  async (version) => {
    preview.value = null
    text.value = null
    if (!version) return
    loading.value = true
    try {
      ;[preview.value, text.value] = await Promise.all([
        getVersionPreviewUrl(props.docId, version.version),
        getVersionText(props.docId, version.version),
      ])
      tab.value = showFile.value || preview.value.mode === 'pages' ? 'preview' : 'text'
    } finally {
      loading.value = false
    }
  },
)
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="
      version
        ? t('knowledge.version.viewTitle', { n: version.version, filename: version.filename })
        : ''
    "
    width="80%"
    top="5vh"
    destroy-on-close
  >
    <!-- Page images carry a server-side watermark; the overlay covers the text. -->
    <ProtectedArea
      v-loading="loading"
      :copy-protect="protection?.copy_protect"
      class="version-view"
    >
      <el-tabs v-model="tab">
        <el-tab-pane :label="t('knowledge.version.tabPreview')" name="preview">
          <iframe
            v-if="preview && showFile"
            :src="preview.url ?? ''"
            class="version-frame"
            :sandbox="isHtmlFile(preview.filename) ? '' : undefined"
            title="version-preview"
          />
          <div
            v-else-if="preview?.mode === 'pages'"
            class="version-pages"
            data-test="version-pages"
          >
            <img
              v-for="page in preview.pages"
              :key="page.url"
              :src="page.url"
              :alt="t('knowledge.protect.pageAlt', { n: page.index })"
              loading="lazy"
              draggable="false"
              class="version-page"
            />
          </div>
          <el-empty v-else-if="preview" :description="t('knowledge.doc.previewUnsupported')" />
        </el-tab-pane>
        <el-tab-pane :label="t('knowledge.version.tabText')" name="text">
          <el-alert
            v-if="text?.truncated"
            type="info"
            :closable="false"
            :title="t('knowledge.version.truncated')"
          />
          <ProtectedArea v-if="text?.available" :watermark="protection?.watermark">
            <pre class="version-text" data-test="version-text">{{ text.lines.join('\n') }}</pre>
          </ProtectedArea>
          <el-empty v-else-if="text" :description="t('knowledge.version.textUnavailable')" />
        </el-tab-pane>
      </el-tabs>
    </ProtectedArea>
  </el-dialog>
</template>

<style scoped>
.version-view {
  min-height: 300px;
}
.version-frame,
.version-pages,
.version-text {
  height: 70vh;
  width: 100%;
}
.version-frame {
  border: 0;
  display: block;
}
.version-pages {
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-light);
}
.version-page {
  display: block;
  width: 100%;
  height: auto;
  margin: 0 auto 12px;
  background: #fff;
  box-shadow: var(--ekb-shadow-sm);
}
.version-text {
  margin: 0;
  overflow: auto;
  padding: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}
</style>
