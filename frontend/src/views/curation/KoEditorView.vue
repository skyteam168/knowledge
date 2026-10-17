<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkKoConflicts,
  deprecateKo,
  getKo,
  reviewKo,
  submitKo,
  updateKo,
  withdrawKo,
} from '@/api/curation'
import type { KnowledgeObjectDetail, KoSource, KoSourceIn, KoType } from '@/api/types'
import DocumentPicker from '@/components/curation/DocumentPicker.vue'
import KoVersionHistory from '@/components/curation/KoVersionHistory.vue'
import UserPicker from '@/components/curation/UserPicker.vue'
import {
  KO_STATUS_META,
  KO_TYPE_LABEL,
  ORIGIN_LABEL,
  REVIEW_STATUS_META,
  VERDICT_META,
  isWarning,
  metaOf,
} from '@/utils/curation'
import { formatDateTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ koId: string }>()
const router = useRouter()
const { t } = useI18n()

const ko = ref<KnowledgeObjectDetail | null>(null)
const loading = ref(false)
const busy = ref<string | null>(null)

interface SourceRow extends KoSourceIn {
  title: string
  available: boolean
  heading_path: string[]
}

const form = reactive({
  title: '',
  ko_type: 'faq' as KoType,
  question: '',
  variants: [] as string[],
  answer: '',
  sources: [] as SourceRow[],
  effective_from: null as string | null,
  effective_to: null as string | null,
  owner_id: null as string | null,
})
const savedSnapshot = ref('')
const newVariant = ref('')
const answerTab = ref<'edit' | 'preview'>('edit')
const sideTab = ref('draft')

const editable = computed(() => !!ko.value?.can_edit && ko.value.status !== 'pending_review')
const dirty = computed(() => JSON.stringify(form) !== savedSnapshot.value)
const warnings = computed(() => (ko.value?.conflicts ?? []).filter((c) => isWarning(c.verdict)))
const aiDraft = computed(() => ko.value?.ai_draft ?? {})
const hasAiDraft = computed(() => !!aiDraft.value.method)
const pendingAlertTitle = computed(() => {
  const review = ko.value?.pending_review
  if (!review) return ''
  const named = {
    version: review.ko_version,
    name: review.submitted_by?.name ?? '-',
    time: formatDateTime(review.created_at),
  }
  return review.note
    ? t('curation.koEditor.pendingAlertNote', { ...named, note: review.note })
    : t('curation.koEditor.pendingAlert', named)
})

function toRow(s: KoSource): SourceRow {
  return {
    document_id: s.document_id,
    chunk_id: s.chunk_id,
    quote: s.quote,
    title: s.title,
    available: s.available,
    heading_path: s.heading_path,
  }
}

function fill(detail: KnowledgeObjectDetail): void {
  ko.value = detail
  form.title = detail.title
  form.ko_type = detail.ko_type
  form.question = detail.question
  form.variants = [...detail.variants]
  form.answer = detail.answer
  form.sources = detail.sources.map(toRow)
  form.effective_from = detail.effective_from
  form.effective_to = detail.effective_to
  form.owner_id = detail.owner?.id ?? null
  savedSnapshot.value = JSON.stringify(form)
}

async function load(): Promise<void> {
  loading.value = true
  try {
    fill(await getKo(props.koId))
  } finally {
    loading.value = false
  }
}

async function run(name: string, action: () => Promise<KnowledgeObjectDetail>, ok: string) {
  busy.value = name
  try {
    fill(await action())
    ElMessage.success(ok)
  } finally {
    busy.value = null
  }
}

// ---- editing --------------------------------------------------------------------

function addVariant(): void {
  const v = newVariant.value.trim()
  if (v && v !== form.question && !form.variants.includes(v)) form.variants.push(v)
  newVariant.value = ''
}

function removeVariant(i: number): void {
  form.variants.splice(i, 1)
}

const pickedDocs = ref<string[]>([])

function addSources(): void {
  for (const id of pickedDocs.value) {
    if (!form.sources.some((s) => s.document_id === id && !s.chunk_id)) {
      form.sources.push({
        document_id: id,
        chunk_id: null,
        quote: null,
        title: t('curation.koEditor.newDocumentTitle'),
        available: true,
        heading_path: [],
      })
    }
  }
  pickedDocs.value = []
}

function removeSource(i: number): void {
  form.sources.splice(i, 1)
}

function payload() {
  return {
    title: form.title.trim() || null,
    ko_type: form.ko_type,
    question: form.question.trim(),
    variants: form.variants,
    answer: form.answer,
    sources: form.sources.map((s) => ({
      document_id: s.document_id,
      chunk_id: s.chunk_id ?? null,
      quote: s.quote ?? null,
    })),
    effective_from: form.effective_from,
    effective_to: form.effective_to,
    owner_id: form.owner_id,
  }
}

async function save(): Promise<void> {
  if (!form.question.trim()) {
    ElMessage.warning(t('curation.koEditor.questionRequired'))
    return
  }
  await run('save', () => updateKo(props.koId, payload()), t('common.saved'))
}

/** Copy the compiler's answer (and its variants / sources) into the form. */
function adoptAiDraft(): void {
  const d = aiDraft.value
  if (d.answer) form.answer = d.answer
  if (d.question) form.question = d.question
  for (const v of d.variants ?? []) {
    if (v !== form.question && !form.variants.includes(v)) form.variants.push(v)
  }
  ElMessage.info(t('curation.koEditor.aiDraftAdopted'))
}

// ---- workflow -------------------------------------------------------------------

async function submit(): Promise<void> {
  if (dirty.value) await save()
  if (!form.answer.trim()) {
    ElMessage.warning(t('curation.koEditor.answerRequired'))
    return
  }
  const { value } = await ElMessageBox.prompt(
    t('curation.koEditor.submitNotePrompt'),
    t('curation.koEditor.submitReview'),
    {
      inputType: 'textarea',
      inputValue: '',
    },
  )
  await run('submit', () => submitKo(props.koId, value), t('curation.koEditor.submitted'))
  if (warnings.value.length) {
    sideTab.value = 'conflicts'
    ElMessage.warning(t('curation.koEditor.submitWarnings', { count: warnings.value.length }))
  }
}

async function withdraw(): Promise<void> {
  await run('withdraw', () => withdrawKo(props.koId), t('curation.koEditor.withdrawn'))
}

async function approve(): Promise<void> {
  if (warnings.value.length) {
    await ElMessageBox.confirm(
      t('curation.koEditor.approveWarnings', { count: warnings.value.length }),
      t('curation.koEditor.publishConfirm'),
      { type: 'warning' },
    )
  }
  const { value } = await ElMessageBox.prompt(
    t('curation.koEditor.reviewCommentPrompt'),
    t('curation.koEditor.approveTitle'),
    {
      inputType: 'textarea',
      inputValue: '',
    },
  )
  await run(
    'approve',
    () => reviewKo(props.koId, 'approve', value),
    t('curation.koEditor.approved'),
  )
}

async function reject(): Promise<void> {
  const { value } = await ElMessageBox.prompt(
    t('curation.koEditor.rejectPrompt'),
    t('curation.field.reject'),
    {
      inputType: 'textarea',
      inputValidator: (v) => (v && v.trim() ? true : t('curation.koEditor.rejectPrompt')),
    },
  )
  await run('reject', () => reviewKo(props.koId, 'reject', value), t('curation.field.rejected'))
}

async function deprecate(): Promise<void> {
  const { value } = await ElMessageBox.prompt(
    t('curation.koEditor.deprecatePrompt'),
    t('curation.koEditor.deprecateTitle'),
    {
      inputType: 'textarea',
      type: 'warning',
    },
  )
  await run('deprecate', () => deprecateKo(props.koId, value), t('curation.koEditor.deprecated'))
}

async function recheck(): Promise<void> {
  await run(
    'conflicts',
    () => checkKoConflicts(props.koId),
    t('curation.koEditor.conflictsChecked'),
  )
  sideTab.value = 'conflicts'
}

const historyOpen = ref(false)

function openDocument(documentId: string): void {
  if (!ko.value) return
  void router.push({
    name: 'knowledge-document',
    params: { kbId: ko.value.kb_id, docId: documentId },
  })
}

watch(
  () => props.koId,
  () => void load(),
)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="ko-editor">
    <template v-if="ko">
      <el-card shadow="never" class="ko-editor__head">
        <div class="ko-editor__bar">
          <div class="ko-editor__title">
            <el-button text @click="router.push({ name: 'curation-kos' })">
              ← {{ t('common.back') }}
            </el-button>
            <strong>{{ ko.title }}</strong>
            <el-tag :type="metaOf(KO_STATUS_META, ko.status).type">
              {{ metaOf(KO_STATUS_META, ko.status).label }}
            </el-tag>
            <el-tag v-if="ko.published_version" type="success" effect="plain">
              {{ t('curation.koEditor.liveVersion', { version: ko.published_version }) }}
            </el-tag>
            <span class="muted">
              {{ t('curation.koEditor.workingVersion', { version: ko.version }) }} ·
              {{ ko.kb_name }} ·
              {{ ORIGIN_LABEL[ko.origin] ?? ko.origin }}
            </span>
          </div>
          <div class="ko-editor__actions">
            <el-button @click="historyOpen = true">{{
              t('curation.koEditor.versionHistory')
            }}</el-button>
            <template v-if="editable">
              <el-button :loading="busy === 'conflicts'" @click="recheck">{{
                t('curation.koEditor.conflictCheck')
              }}</el-button>
              <el-button :loading="busy === 'save'" :disabled="!dirty" @click="save">
                {{ t('common.save') }}
              </el-button>
              <el-button
                v-if="ko.status !== 'published' || dirty"
                type="primary"
                :loading="busy === 'submit'"
                data-test="submit-ko"
                @click="submit"
              >
                {{ t('curation.koEditor.submitReview') }}
              </el-button>
            </template>
            <template v-if="ko.status === 'pending_review'">
              <el-button v-if="ko.can_edit" :loading="busy === 'withdraw'" @click="withdraw">
                {{ t('curation.koEditor.withdraw') }}
              </el-button>
              <template v-if="ko.can_review">
                <el-button type="danger" plain :loading="busy === 'reject'" @click="reject">
                  {{ t('curation.field.reject') }}
                </el-button>
                <el-button
                  type="success"
                  :loading="busy === 'approve'"
                  data-test="approve-ko"
                  @click="approve"
                >
                  {{ t('curation.koEditor.approve') }}
                </el-button>
              </template>
            </template>
            <el-button
              v-if="ko.can_edit && ko.published_version"
              type="danger"
              plain
              :loading="busy === 'deprecate'"
              @click="deprecate"
            >
              {{ t('curation.koEditor.deprecate') }}
            </el-button>
          </div>
        </div>
        <el-alert
          v-if="ko.status === 'pending_review' && ko.pending_review"
          type="warning"
          :closable="false"
          class="ko-editor__alert"
          :title="pendingAlertTitle"
        />
        <el-alert
          v-if="warnings.length"
          type="error"
          :closable="false"
          show-icon
          class="ko-editor__alert"
          :title="t('curation.koEditor.conflictAlert', { count: warnings.length })"
        >
          <a class="ko-editor__link" @click="sideTab = 'conflicts'">{{
            t('curation.koEditor.viewDetails')
          }}</a>
        </el-alert>
      </el-card>

      <div class="ko-editor__body">
        <el-card shadow="never" :header="t('curation.koEditor.content')">
          <el-form label-position="top" :disabled="!editable">
            <div class="ko-editor__row">
              <el-form-item :label="t('curation.field.title')" class="ko-editor__grow">
                <el-input
                  v-model="form.title"
                  maxlength="512"
                  :placeholder="t('curation.koEditor.titlePlaceholder')"
                />
              </el-form-item>
              <el-form-item :label="t('curation.field.type')">
                <el-select v-model="form.ko_type" style="width: 140px">
                  <el-option
                    v-for="(label, key) in KO_TYPE_LABEL"
                    :key="key"
                    :label="label"
                    :value="key"
                  />
                </el-select>
              </el-form-item>
            </div>
            <el-form-item :label="t('curation.field.question')" required>
              <el-input v-model="form.question" maxlength="2000" data-test="ko-question" />
            </el-form-item>
            <el-form-item :label="t('curation.koEditor.variantsLabel')">
              <div class="ko-editor__variants">
                <el-tag
                  v-for="(v, i) in form.variants"
                  :key="v"
                  :closable="editable"
                  @close="removeVariant(i)"
                >
                  {{ v }}
                </el-tag>
                <el-input
                  v-if="editable"
                  v-model="newVariant"
                  size="small"
                  :placeholder="t('curation.koEditor.variantPlaceholder')"
                  style="width: 220px"
                  @keyup.enter="addVariant"
                  @blur="addVariant"
                />
              </div>
            </el-form-item>
            <el-form-item :label="t('curation.koEditor.answerLabel')" required>
              <el-tabs v-model="answerTab" class="ko-editor__answer">
                <el-tab-pane :label="t('common.edit')" name="edit">
                  <el-input
                    v-model="form.answer"
                    type="textarea"
                    :autosize="{ minRows: 8, maxRows: 24 }"
                    maxlength="20000"
                    show-word-limit
                    data-test="ko-answer"
                  />
                </el-tab-pane>
                <el-tab-pane :label="t('curation.koEditor.preview')" name="preview">
                  <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
                  <div class="markdown ko-editor__preview" v-html="renderMarkdown(form.answer)" />
                </el-tab-pane>
              </el-tabs>
            </el-form-item>
            <el-form-item :label="t('curation.field.sources')">
              <div class="ko-editor__sources">
                <div
                  v-for="(s, i) in form.sources"
                  :key="`${s.document_id}:${s.chunk_id}`"
                  class="src"
                >
                  <div class="src__head">
                    <el-link
                      v-if="s.available"
                      type="primary"
                      :disabled="false"
                      @click="openDocument(s.document_id)"
                    >
                      {{ s.title }}
                    </el-link>
                    <span v-else class="muted">{{ t('curation.koEditor.sourceUnavailable') }}</span>
                    <span v-if="s.heading_path.length" class="muted">
                      {{ s.heading_path.join(' > ') }}
                    </span>
                    <el-button v-if="editable" link type="danger" @click="removeSource(i)">
                      {{ t('common.remove') }}
                    </el-button>
                  </div>
                  <div v-if="s.quote" class="src__quote">{{ s.quote }}</div>
                </div>
                <div v-if="editable" class="ko-editor__add-src">
                  <DocumentPicker v-model="pickedDocs" :kb-id="ko.kb_id" />
                  <el-button :disabled="!pickedDocs.length" @click="addSources">{{
                    t('common.add')
                  }}</el-button>
                </div>
              </div>
            </el-form-item>
            <div class="ko-editor__row">
              <el-form-item :label="t('curation.koEditor.effectiveFrom')">
                <el-date-picker
                  v-model="form.effective_from"
                  type="datetime"
                  value-format="YYYY-MM-DDTHH:mm:ssZ"
                  :placeholder="t('curation.koEditor.effectiveFromPlaceholder')"
                />
              </el-form-item>
              <el-form-item :label="t('curation.koEditor.effectiveTo')">
                <el-date-picker
                  v-model="form.effective_to"
                  type="datetime"
                  value-format="YYYY-MM-DDTHH:mm:ssZ"
                  :placeholder="t('curation.koEditor.effectiveToPlaceholder')"
                />
              </el-form-item>
              <el-form-item :label="t('curation.koEditor.ownerLabel')" class="ko-editor__grow">
                <UserPicker v-model="form.owner_id" :initial="ko.owner" />
              </el-form-item>
            </div>
          </el-form>
        </el-card>

        <el-card shadow="never" class="ko-editor__side">
          <el-tabs v-model="sideTab">
            <el-tab-pane :label="t('curation.koEditor.aiDraft')" name="draft">
              <el-empty v-if="!hasAiDraft" :description="t('curation.koEditor.notAiGenerated')" />
              <template v-else>
                <div class="side__bar">
                  <el-tag :type="aiDraft.method === 'llm' ? 'success' : 'warning'" size="small">
                    {{
                      aiDraft.method === 'llm'
                        ? t('curation.koEditor.aiGenerated')
                        : t('curation.koEditor.aiFailed')
                    }}
                  </el-tag>
                  <el-button v-if="editable && aiDraft.answer" size="small" @click="adoptAiDraft">
                    {{ t('curation.koEditor.adoptAi') }}
                  </el-button>
                </div>
                <el-alert
                  v-if="aiDraft.error"
                  type="warning"
                  :closable="false"
                  :title="aiDraft.error"
                />
                <div v-if="aiDraft.question" class="side__label">
                  {{ t('curation.field.question') }}
                </div>
                <div>{{ aiDraft.question }}</div>
                <template v-if="aiDraft.variants?.length">
                  <div class="side__label">{{ t('curation.field.variants') }}</div>
                  <el-tag v-for="v in aiDraft.variants" :key="v" size="small" class="side__tag">
                    {{ v }}
                  </el-tag>
                </template>
                <template v-if="aiDraft.answer">
                  <div class="side__label">{{ t('curation.koEditor.aiAnswer') }}</div>
                  <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
                  <div class="markdown side__answer" v-html="renderMarkdown(aiDraft.answer)" />
                </template>
                <template v-if="aiDraft.similar?.length">
                  <div class="side__label">{{ t('curation.koEditor.similarQuestions') }}</div>
                  <ul class="side__list">
                    <li v-for="q in aiDraft.similar" :key="q">{{ q }}</li>
                  </ul>
                </template>
                <template v-if="aiDraft.materials?.length">
                  <div class="side__label">{{ t('curation.koEditor.materials') }}</div>
                  <div v-for="m in aiDraft.materials" :key="m.n" class="src">
                    <div class="src__head">
                      <el-tag
                        size="small"
                        :type="aiDraft.citations?.includes(m.n) ? 'success' : 'info'"
                      >
                        {{
                          aiDraft.citations?.includes(m.n)
                            ? t('curation.koEditor.cited', { n: m.n })
                            : `[${m.n}]`
                        }}
                      </el-tag>
                      <el-link
                        v-if="m.document_id"
                        type="primary"
                        @click="openDocument(m.document_id)"
                      >
                        {{ m.title }}
                      </el-link>
                      <span v-else>{{ m.title }}</span>
                    </div>
                    <div class="src__quote">{{ m.quote }}</div>
                  </div>
                </template>
              </template>
            </el-tab-pane>

            <el-tab-pane name="conflicts">
              <template #label>
                {{ t('curation.koEditor.conflictCheck') }}
                <el-badge v-if="warnings.length" :value="warnings.length" type="danger" />
              </template>
              <div class="side__bar">
                <span class="muted">
                  {{
                    ko.conflicts_checked_at
                      ? t('curation.koEditor.checkedAt', {
                          time: formatDateTime(ko.conflicts_checked_at),
                        })
                      : t('curation.koEditor.notChecked')
                  }}
                </span>
                <el-button
                  v-if="ko.can_edit"
                  size="small"
                  :loading="busy === 'conflicts'"
                  @click="recheck"
                >
                  {{ t('curation.koEditor.recheck') }}
                </el-button>
              </div>
              <el-empty
                v-if="ko.conflicts_checked_at && !ko.conflicts.length"
                :description="t('curation.koEditor.noSimilar')"
              />
              <div
                v-for="c in ko.conflicts"
                :key="`${c.kind}:${c.id}:${c.chunk_id}`"
                class="conflict"
                :class="{ 'conflict--warn': isWarning(c.verdict) }"
              >
                <div class="src__head">
                  <el-tag size="small" :type="metaOf(VERDICT_META, c.verdict).type">
                    {{ metaOf(VERDICT_META, c.verdict).label }}
                  </el-tag>
                  <el-tag size="small" effect="plain">
                    {{
                      c.kind === 'ko'
                        ? t('curation.koEditor.kindKo')
                        : t('curation.koEditor.kindDocument')
                    }}
                  </el-tag>
                  <el-link
                    v-if="c.kind === 'ko'"
                    type="primary"
                    @click="router.push({ name: 'curation-ko', params: { koId: c.id } })"
                  >
                    {{ c.title }}
                  </el-link>
                  <el-link v-else type="primary" @click="openDocument(c.id)">{{ c.title }}</el-link>
                  <span v-if="c.score != null" class="muted">
                    {{ t('curation.koEditor.similarity', { score: c.score.toFixed(2) }) }}
                  </span>
                </div>
                <div v-if="c.reason" class="conflict__reason">{{ c.reason }}</div>
                <div class="src__quote">{{ c.excerpt }}</div>
              </div>
            </el-tab-pane>

            <el-tab-pane :label="t('curation.koEditor.reviews')" name="reviews">
              <el-empty v-if="!ko.reviews.length" :description="t('curation.koEditor.noReviews')" />
              <el-timeline>
                <el-timeline-item
                  v-for="r in ko.reviews"
                  :key="r.id"
                  :timestamp="formatDateTime(r.decided_at ?? r.created_at)"
                >
                  <div class="src__head">
                    <span>v{{ r.ko_version }}</span>
                    <el-tag size="small" :type="metaOf(REVIEW_STATUS_META, r.status).type">
                      {{ metaOf(REVIEW_STATUS_META, r.status).label }}
                    </el-tag>
                  </div>
                  <div class="muted">
                    {{
                      r.note
                        ? t('curation.koEditor.submittedByNote', {
                            name: r.submitted_by?.name ?? '-',
                            note: r.note,
                          })
                        : t('curation.koEditor.submittedBy', { name: r.submitted_by?.name ?? '-' })
                    }}
                  </div>
                  <div v-if="r.reviewer" class="muted">
                    {{
                      r.comment
                        ? t('curation.koEditor.reviewedByComment', {
                            name: r.reviewer.name,
                            comment: r.comment,
                          })
                        : t('curation.koEditor.reviewedBy', { name: r.reviewer.name })
                    }}
                  </div>
                </el-timeline-item>
              </el-timeline>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </div>

      <KoVersionHistory v-model="historyOpen" :ko-id="ko.id" />
    </template>
  </div>
</template>

<style scoped>
.ko-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 200px;
}

.ko-editor__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}

.ko-editor__title,
.ko-editor__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.ko-editor__alert {
  margin-top: 12px;
}

.ko-editor__link {
  cursor: pointer;
  color: var(--el-color-primary);
}

.ko-editor__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.ko-editor__row {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.ko-editor__grow {
  flex: 1;
  min-width: 200px;
}

.ko-editor__variants {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.ko-editor__answer {
  width: 100%;
}

.ko-editor__preview {
  min-height: 160px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}

.ko-editor__sources {
  width: 100%;
}

.ko-editor__add-src {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.ko-editor__side {
  position: sticky;
  top: 0;
}

.side__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.side__label {
  margin: 12px 0 4px;
  font-weight: 500;
  color: var(--el-text-color-secondary);
}

.side__tag {
  margin: 0 4px 4px 0;
}

.side__answer {
  padding: 8px 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
}

.side__list {
  margin: 0;
  padding-left: 18px;
}

.src,
.conflict {
  padding: 8px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.conflict--warn {
  background: var(--el-color-danger-light-9);
  padding: 8px;
  border-radius: 4px;
}

.src__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.src__quote {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  max-height: 120px;
  overflow: auto;
}

.conflict__reason {
  margin-top: 4px;
  font-size: 13px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
