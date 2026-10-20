<script setup lang="ts">
import {
  computed,
  onActivated,
  onBeforeUnmount,
  onDeactivated,
  onMounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import {
  createMarkdownDocument,
  getDocument,
  getDocumentContent,
  saveDocumentContent,
} from '@/api/knowledge'
import { HttpError } from '@/api/http'
import { renderMarkdown } from '@/utils/markdown'

/** Online Markdown document: create (no docId) or edit; every save is a new version. */
const props = defineProps<{ kbId: string; docId?: string }>()
const router = useRouter()
const { t } = useI18n()

const NO_CITATIONS: ReadonlySet<number> = new Set()
const form = reactive({ title: '', tags: [] as string[], content: '' })
const baseVersion = ref(0)
const saved = ref('')
const loading = ref(false)
const saving = ref(false)
const textarea = ref<{ textarea?: HTMLTextAreaElement }>()

const creating = computed(() => !props.docId)
const dirty = computed(() => form.content !== saved.value)
const preview = computed(() => renderMarkdown(form.content, { citations: NO_CITATIONS }))

async function load(): Promise<void> {
  if (!props.docId) {
    form.title = ''
    form.content = saved.value = ''
    return
  }
  loading.value = true
  try {
    const [doc, content] = await Promise.all([
      getDocument(props.docId),
      getDocumentContent(props.docId),
    ])
    form.title = doc.title
    form.content = saved.value = content.content
    baseVersion.value = content.version
  } finally {
    loading.value = false
  }
}

function failed(err: unknown): void {
  if (err instanceof HttpError && err.code === 'VERSION_CONFLICT') {
    const current = (err.detail as { current_version?: number } | null)?.current_version
    ElMessage.error({ message: t('collab.online.conflict', { n: current ?? '?' }), duration: 8000 })
  } else if (err instanceof HttpError && err.code === 'DOCUMENT_EXISTS') {
    ElMessage.error(t('collab.online.exists'))
  } else {
    ElMessage.error(err instanceof Error ? err.message : String(err))
  }
}

async function save(): Promise<void> {
  if (saving.value || !form.content.trim() || (creating.value && !form.title.trim())) return
  saving.value = true
  try {
    if (!props.docId) {
      const result = await createMarkdownDocument(props.kbId, {
        title: form.title.trim(),
        content: form.content,
        tags: form.tags,
      })
      saved.value = form.content
      ElMessage.success(t('collab.online.created'))
      await router.replace({
        name: 'knowledge-document-edit',
        params: { kbId: props.kbId, docId: result.document.id },
      })
      return
    }
    const result = await saveDocumentContent(props.docId, form.content, baseVersion.value)
    saved.value = form.content
    if (result.duplicate) {
      ElMessage.info(t('collab.online.unchanged'))
      return
    }
    baseVersion.value = result.document.version
    ElMessage.success(t('collab.online.saved', { n: result.document.version }))
  } catch (err) {
    failed(err)
  } finally {
    saving.value = false
  }
}

function back(): void {
  void router.push(
    props.docId
      ? { name: 'knowledge-document', params: { kbId: props.kbId, docId: props.docId } }
      : { name: 'knowledge-base', params: { kbId: props.kbId } },
  )
}

// ---- toolbar ------------------------------------------------------------------------

function insert(before: string, after = '', placeholder = ''): void {
  const el = textarea.value?.textarea
  if (!el) {
    form.content += before + placeholder + after
    return
  }
  const { selectionStart: start, selectionEnd: end } = el
  const selected = form.content.slice(start, end) || placeholder
  form.content = form.content.slice(0, start) + before + selected + after + form.content.slice(end)
  requestAnimationFrame(() => {
    el.focus()
    el.setSelectionRange(start + before.length, start + before.length + selected.length)
  })
}

const sample = (key: string) => t(`collab.online.sample.${key}`)
const TOOLS = computed(() => [
  { label: 'H2', run: () => insert('\n## ', '\n', sample('heading')) },
  { label: 'B', run: () => insert('**', '**', sample('bold')) },
  { label: '•', run: () => insert('\n- ', '', sample('item')) },
  { label: '1.', run: () => insert('\n1. ', '', sample('step')) },
  {
    label: t('collab.online.tool.table'),
    run: () => insert(`\n| ${sample('col1')} | ${sample('col2')} |\n| --- | --- |\n| `, ' |  |\n'),
  },
  { label: t('collab.online.tool.link'), run: () => insert('[', '](https://)', sample('text')) },
  { label: t('collab.online.tool.code'), run: () => insert('\n```\n', '\n```\n') },
])

// ---- unsaved changes ------------------------------------------------------------------

function onKey(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
    event.preventDefault()
    void save()
  }
}

function onUnload(event: BeforeUnloadEvent): void {
  if (dirty.value) event.preventDefault()
}

onBeforeRouteLeave(async () => {
  if (!dirty.value) return true
  return ElMessageBox.confirm(t('collab.online.leaveConfirm'), t('common.tip'), {
    type: 'warning',
  })
    .then(() => true)
    .catch(() => false)
})

// Pages are kept alive: listen only while this one is on screen.
function listen(on: boolean): void {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('beforeunload', onUnload)
  if (!on) return
  window.addEventListener('keydown', onKey)
  window.addEventListener('beforeunload', onUnload)
}

watch(() => props.docId, load)
onMounted(() => {
  listen(true)
  void load()
})
onActivated(() => listen(true))
onDeactivated(() => listen(false))
onBeforeUnmount(() => listen(false))
</script>

<template>
  <div v-loading="loading" class="editor-page">
    <el-card shadow="never">
      <div class="header">
        <el-button link :icon="ArrowLeft" @click="back">{{ t('common.back') }}</el-button>
        <el-input
          v-if="creating"
          v-model="form.title"
          maxlength="200"
          :placeholder="t('collab.online.titlePlaceholder')"
          class="title-input"
          data-test="online-title"
        />
        <h2 v-else class="title">{{ form.title }}</h2>
        <el-tag v-if="!creating && baseVersion" effect="plain">{{
          t('collab.online.basedOn', { n: baseVersion })
        }}</el-tag>
        <el-select
          v-if="creating"
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          :placeholder="t('collab.online.tags')"
          class="tags"
        />
        <span class="spacer" />
        <span class="hint">{{ t('collab.online.saveHint') }}</span>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="
            !form.content.trim() || (creating && !form.title.trim()) || (!creating && !dirty)
          "
          data-test="online-save"
          @click="save"
          >{{ t('collab.online.save') }}</el-button
        >
      </div>
    </el-card>

    <div class="panes">
      <el-card shadow="never" body-class="pane-body">
        <template #header>
          <div class="pane-head">
            <span>{{ t('collab.online.editor') }}</span>
            <span class="tools">
              <el-button
                v-for="tool in TOOLS"
                :key="tool.label"
                size="small"
                text
                @click="tool.run"
                >{{ tool.label }}</el-button
              >
            </span>
          </div>
        </template>
        <el-input
          ref="textarea"
          v-model="form.content"
          type="textarea"
          resize="none"
          :placeholder="t('collab.online.placeholder')"
          class="source"
          data-test="online-content"
        />
      </el-card>
      <el-card shadow="never" :header="t('collab.online.preview')" body-class="pane-body">
        <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
        <div class="markdown preview" data-test="online-preview" v-html="preview" />
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.editor-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.header {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title {
  margin: 0;
  font-size: 18px;
}
.title-input {
  max-width: 360px;
}
.tags {
  width: 220px;
}
.spacer {
  flex: 1;
}
.hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.panes {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.pane-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.panes :deep(.pane-body) {
  padding: 0;
}
.source :deep(textarea) {
  height: calc(100vh - 280px);
  min-height: 420px;
  border: 0;
  box-shadow: none;
  padding: 14px 16px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13.5px;
  line-height: 1.7;
}
.preview {
  height: calc(100vh - 280px);
  min-height: 420px;
  overflow: auto;
  padding: 14px 18px;
}
.preview :deep(table) {
  border-collapse: collapse;
  margin: 8px 0 12px;
}
.preview :deep(th),
.preview :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 6px 12px;
  text-align: left;
}
.preview :deep(th) {
  background: var(--el-fill-color-light);
}
@media (max-width: 1100px) {
  .panes {
    grid-template-columns: 1fr;
  }
}
</style>
