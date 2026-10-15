<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  draftFromGap,
  getGap,
  linkGapDocuments,
  markGapDuplicate,
  patchGap,
  rejectGap,
  reopenGap,
} from '@/api/curation'
import { listKnowledgeBases } from '@/api/knowledge'
import type { GapDetail, KnowledgeBase, KoType } from '@/api/types'
import DocumentPicker from '@/components/curation/DocumentPicker.vue'
import UserPicker from '@/components/curation/UserPicker.vue'
import { useAuthStore } from '@/stores/auth'
import {
  GAP_STATUS_META,
  GAP_TYPE_META,
  KO_STATUS_META,
  KO_TYPE_LABEL,
  metaOf,
} from '@/utils/curation'
import { formatDateTime } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{ gapId: string }>()
const router = useRouter()
const auth = useAuthStore()

const gap = ref<GapDetail | null>(null)
const loading = ref(false)
const kbOptions = ref<KnowledgeBase[]>([])

const active = computed(() => gap.value?.status === 'open' || gap.value?.status === 'in_review')
const canDraft = computed(() => auth.can('ko:edit'))
const question = computed(() => gap.value?.rewritten_query || gap.value?.query || '')

async function load(): Promise<void> {
  loading.value = true
  try {
    gap.value = await getGap(props.gapId)
    assignee.value = gap.value.assignee?.id ?? null
    kbId.value = gap.value.kb_id
  } finally {
    loading.value = false
  }
}

// ---- triage ---------------------------------------------------------------------

const assignee = ref<string | null>(null)
const kbId = ref<string | null>(null)
const saving = ref(false)

async function saveTriage(): Promise<void> {
  if (!gap.value) return
  saving.value = true
  try {
    await patchGap(gap.value.id, { assignee_id: assignee.value, kb_id: kbId.value })
    ElMessage.success('已保存')
    await load()
  } finally {
    saving.value = false
  }
}

async function assignToMe(): Promise<void> {
  assignee.value = auth.profile?.id ?? null
  await saveTriage()
}

// ---- actions --------------------------------------------------------------------

const draftDialog = ref(false)
const drafting = ref(false)
const draftForm = reactive({
  kb_id: null as string | null,
  ko_type: 'faq' as KoType,
  notes: '',
  document_ids: [] as string[],
})

function openDraft(): void {
  draftForm.kb_id = gap.value?.kb_id ?? null
  draftForm.notes = ''
  draftForm.document_ids = []
  draftDialog.value = true
}

async function submitDraft(): Promise<void> {
  if (!gap.value) return
  if (!draftForm.kb_id) {
    ElMessage.warning('请选择知识条目所属的知识库')
    return
  }
  drafting.value = true
  try {
    const ko = await draftFromGap(gap.value.id, {
      kb_id: draftForm.kb_id,
      ko_type: draftForm.ko_type,
      notes: draftForm.notes.trim() || null,
      document_ids: draftForm.document_ids,
    })
    draftDialog.value = false
    if (ko.ai_draft.method === 'fallback') {
      ElMessage.warning('AI 生成失败，已创建空白草稿，请手工补充答案')
    } else {
      ElMessage.success('已生成知识条目草稿')
    }
    await router.push({ name: 'curation-ko', params: { koId: ko.id } })
  } finally {
    drafting.value = false
  }
}

const linkDialog = ref(false)
const linking = ref(false)
const linkForm = reactive({ kb_id: null as string | null, document_ids: [] as string[], note: '' })

function openLink(): void {
  linkForm.kb_id = gap.value?.kb_id ?? null
  linkForm.document_ids = []
  linkForm.note = ''
  linkDialog.value = true
}

async function submitLink(): Promise<void> {
  if (!gap.value || !linkForm.document_ids.length) {
    ElMessage.warning('请选择至少一个文档')
    return
  }
  linking.value = true
  try {
    await linkGapDocuments(gap.value.id, linkForm.document_ids, linkForm.note.trim())
    linkDialog.value = false
    ElMessage.success('已关联文档，问题已记录为检索问题')
    await load()
  } finally {
    linking.value = false
  }
}

const duplicateDialog = ref(false)
const duplicateForm = reactive({ duplicate_of_id: '', note: '' })

function openDuplicate(): void {
  duplicateForm.duplicate_of_id = gap.value?.similar[0]?.id ?? ''
  duplicateForm.note = ''
  duplicateDialog.value = true
}

async function submitDuplicate(): Promise<void> {
  if (!gap.value || !duplicateForm.duplicate_of_id.trim()) return
  await markGapDuplicate(
    gap.value.id,
    duplicateForm.duplicate_of_id.trim(),
    duplicateForm.note.trim(),
  )
  duplicateDialog.value = false
  ElMessage.success('已标记为重复')
  await load()
}

async function reject(): Promise<void> {
  if (!gap.value) return
  const { value } = await ElMessageBox.prompt('驳回原因（可选）', '驳回缺口', {
    inputType: 'textarea',
    inputValue: '',
  })
  await rejectGap(gap.value.id, value)
  ElMessage.success('已驳回')
  await load()
}

async function reopen(): Promise<void> {
  if (!gap.value) return
  await reopenGap(gap.value.id)
  ElMessage.success('已重新打开')
  await load()
}

// ---- trace ----------------------------------------------------------------------

const traceSteps = computed(() => {
  const steps = (gap.value?.qa_trace?.steps ?? {}) as Record<string, unknown>
  return Object.entries(steps)
})

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

watch(
  () => props.gapId,
  () => void load(),
)

onMounted(async () => {
  void load()
  kbOptions.value = (await listKnowledgeBases({ page: 1, size: 100 })).items
})
</script>

<template>
  <div v-loading="loading" class="workbench">
    <template v-if="gap">
      <div class="workbench__main">
        <el-card shadow="never">
          <template #header>
            <div class="workbench__header">
              <el-button text @click="router.push({ name: 'curation-gaps' })">← 返回</el-button>
              <el-tag :type="metaOf(GAP_TYPE_META, gap.gap_type).type">
                {{ metaOf(GAP_TYPE_META, gap.gap_type).label }}
              </el-tag>
              <el-tag :type="metaOf(GAP_STATUS_META, gap.status).type">
                {{ metaOf(GAP_STATUS_META, gap.status).label }}
              </el-tag>
            </div>
          </template>
          <h2 class="workbench__question" data-test="gap-question">{{ question }}</h2>
          <p v-if="gap.rewritten_query && gap.rewritten_query !== gap.query" class="muted">
            用户原问：{{ gap.query }}
          </p>
          <el-descriptions :column="3" size="small" border>
            <el-descriptions-item label="出现次数">{{ gap.occurrences }}</el-descriptions-item>
            <el-descriptions-item label="同类频次">
              {{ gap.cluster_occurrences ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="最高相关分">
              {{ gap.top_score == null ? '-' : gap.top_score.toFixed(3) }}
            </el-descriptions-item>
            <el-descriptions-item label="知识库">{{ gap.kb_name ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="首次出现">
              {{ formatDateTime(gap.created_at) }}
            </el-descriptions-item>
            <el-descriptions-item label="最近出现">
              {{ formatDateTime(gap.last_seen_at) }}
            </el-descriptions-item>
          </el-descriptions>
          <el-alert
            v-if="gap.description"
            type="info"
            :closable="false"
            class="workbench__desc"
            :title="`用户描述：${gap.description}`"
          />
          <el-alert
            v-if="gap.resolution && Object.keys(gap.resolution).length"
            type="success"
            :closable="false"
            class="workbench__desc"
            :title="`处理结果：${pretty(gap.resolution)}`"
          />
        </el-card>

        <el-card shadow="never" header="原始对话">
          <el-empty v-if="!gap.conversation.length" description="对话已删除或不可见" />
          <div
            v-for="m in gap.conversation"
            :key="m.id"
            class="msg"
            :class="[`msg--${m.role}`, { 'msg--gap': m.is_gap_message }]"
          >
            <div class="msg__meta">
              {{ m.role === 'user' ? '用户' : 'AI 助手' }} · {{ formatDateTime(m.created_at) }}
              <el-tag v-if="m.grounding" size="small" type="info">{{ m.grounding }}</el-tag>
              <el-tag v-if="m.is_gap_message" size="small" type="danger">产生缺口</el-tag>
            </div>
            <el-alert
              v-if="m.redacted"
              type="warning"
              :closable="false"
              title="该回答引用了你无权查看的内容，已隐藏"
            />
            <!-- eslint-disable-next-line vue/no-v-html -- markdown-it with html disabled -->
            <div v-else class="msg__content markdown" v-html="renderMarkdown(m.content)" />
          </div>
        </el-card>

        <el-card shadow="never" header="检索与问答 Trace">
          <el-empty v-if="!gap.qa_trace" description="无 trace 记录" />
          <template v-else>
            <el-descriptions :column="3" size="small" class="workbench__trace-head">
              <el-descriptions-item label="状态">
                {{ String(gap.qa_trace.status ?? '-') }}
              </el-descriptions-item>
              <el-descriptions-item label="依据">
                {{ String(gap.qa_trace.grounding ?? '-') }}
              </el-descriptions-item>
              <el-descriptions-item label="Trace ID">{{ gap.trace_id }}</el-descriptions-item>
            </el-descriptions>
            <el-collapse>
              <el-collapse-item
                v-for="[name, step] in traceSteps"
                :key="name"
                :title="name"
                :name="name"
              >
                <pre class="workbench__pre">{{ pretty(step) }}</pre>
              </el-collapse-item>
            </el-collapse>
          </template>
        </el-card>
      </div>

      <div class="workbench__side">
        <el-card shadow="never" header="分派">
          <el-form label-position="top" size="small">
            <el-form-item label="负责人">
              <UserPicker v-model="assignee" :initial="gap.assignee" />
            </el-form-item>
            <el-form-item label="所属知识库">
              <el-select v-model="kbId" clearable filterable style="width: 100%">
                <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
              </el-select>
            </el-form-item>
            <el-button type="primary" :loading="saving" @click="saveTriage">保存</el-button>
            <el-button @click="assignToMe">分派给我</el-button>
          </el-form>
        </el-card>

        <el-card shadow="never" header="处理">
          <div class="workbench__actions">
            <el-button
              v-if="canDraft"
              type="primary"
              :disabled="!active"
              data-test="draft-ko"
              @click="openDraft"
            >
              AI 生成知识条目
            </el-button>
            <el-button :disabled="!active" @click="openLink">关联已有文档（检索问题）</el-button>
            <el-button :disabled="!active" @click="openDuplicate">标记为重复</el-button>
            <el-button type="danger" plain :disabled="!active" @click="reject">驳回</el-button>
            <el-button v-if="!active" @click="reopen">重新打开</el-button>
          </div>
        </el-card>

        <el-card shadow="never" header="关联知识条目">
          <el-empty v-if="!gap.knowledge_objects.length" :image-size="60" description="暂无" />
          <div v-for="ko in gap.knowledge_objects" :key="ko.id" class="workbench__ko">
            <el-link
              type="primary"
              @click="router.push({ name: 'curation-ko', params: { koId: ko.id } })"
            >
              {{ ko.title }}
            </el-link>
            <el-tag size="small" :type="metaOf(KO_STATUS_META, ko.status).type">
              {{ metaOf(KO_STATUS_META, ko.status).label }}
            </el-tag>
          </div>
        </el-card>

        <el-card v-if="gap.cluster" shadow="never" header="同类问题">
          <p class="muted">
            聚类共 {{ gap.cluster.gap_count }} 个问题，{{ gap.cluster.occurrences }} 次提问
          </p>
          <div v-for="s in gap.similar" :key="s.id" class="workbench__similar">
            <el-link @click="router.push({ name: 'curation-gap', params: { gapId: s.id } })">
              {{ s.rewritten_query || s.query }}
            </el-link>
            <span class="muted">
              ×{{ s.occurrences }} · {{ metaOf(GAP_STATUS_META, s.status).label }}
            </span>
          </div>
        </el-card>
      </div>
    </template>

    <el-dialog v-model="draftDialog" title="AI 生成知识条目草稿" width="640px">
      <el-form label-width="96px">
        <el-form-item label="问题">{{ question }}</el-form-item>
        <el-form-item label="知识库" required>
          <el-select v-model="draftForm.kb_id" filterable style="width: 100%">
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="draftForm.ko_type">
            <el-radio-button v-for="(label, key) in KO_TYPE_LABEL" :key="key" :value="key">
              {{ label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="指定文档">
          <DocumentPicker v-model="draftForm.document_ids" :kb-id="draftForm.kb_id" />
          <div class="muted">不指定时，将在知识库中检索相关资料</div>
        </el-form-item>
        <el-form-item label="补充资料">
          <el-input
            v-model="draftForm.notes"
            type="textarea"
            :rows="5"
            maxlength="8000"
            show-word-limit
            placeholder="审核人提供的答案要点或资料原文，会作为生成依据"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="draftDialog = false">取消</el-button>
        <el-button type="primary" :loading="drafting" @click="submitDraft">生成草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="linkDialog" title="关联已有文档" width="560px">
      <el-alert
        type="info"
        :closable="false"
        title="答案已存在于文档中但未被检索到：记录为检索问题，用于后续调优。"
        class="workbench__desc"
      />
      <el-form label-width="80px">
        <el-form-item label="知识库">
          <el-select v-model="linkForm.kb_id" filterable style="width: 100%">
            <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档" required>
          <DocumentPicker v-model="linkForm.document_ids" :kb-id="linkForm.kb_id" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="linkForm.note" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="linkDialog = false">取消</el-button>
        <el-button type="primary" :loading="linking" @click="submitLink">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="duplicateDialog" title="标记为重复" width="520px">
      <el-form label-width="96px">
        <el-form-item label="重复于" required>
          <el-select
            v-model="duplicateForm.duplicate_of_id"
            filterable
            allow-create
            placeholder="选择同类问题或输入缺口 ID"
            style="width: 100%"
          >
            <el-option
              v-for="s in gap?.similar ?? []"
              :key="s.id"
              :label="s.rewritten_query || s.query"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="duplicateForm.note" type="textarea" :rows="3" maxlength="2000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="duplicateDialog = false">取消</el-button>
        <el-button type="primary" @click="submitDuplicate">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 16px;
  align-items: start;
  min-height: 200px;
}

.workbench__main,
.workbench__side {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.workbench__header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workbench__question {
  margin: 0 0 8px;
  font-size: 18px;
}

.workbench__desc {
  margin-top: 12px;
}

.workbench__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.workbench__actions .el-button + .el-button {
  margin-left: 0;
}

.workbench__ko,
.workbench__similar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
}

.workbench__trace-head {
  margin-bottom: 8px;
}

.workbench__pre {
  max-height: 360px;
  overflow: auto;
  margin: 0;
  padding: 8px;
  font-size: 12px;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}

.msg {
  padding: 8px 12px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}

.msg--user {
  background: var(--el-color-primary-light-9);
}

.msg--gap {
  outline: 1px solid var(--el-color-danger-light-5);
}

.msg__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
