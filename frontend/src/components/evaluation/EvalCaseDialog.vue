<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createEvalCase, updateEvalCase } from '@/api/evaluation'
import { listDocuments, listKnowledgeBases } from '@/api/knowledge'
import type { EvalCase, EvalCaseFields, KbDocument, KnowledgeBase } from '@/api/types'

const props = defineProps<{ datasetId: string; evalCase: EvalCase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [EvalCase] }>()
const { t } = useI18n()

const formRef = ref<FormInstance>()
const form = reactive<EvalCaseFields>({
  question: '',
  reference_answer: '',
  expected_document_ids: [],
  expected_chunk_ids: [],
  kb_ids: [],
  tags: [],
})
const saving = ref(false)
const rules = computed<FormRules>(() => ({
  question: [
    { required: true, message: t('evaluation.caseDialog.questionRequired'), trigger: 'blur' },
  ],
}))

const isEdit = computed(() => props.evalCase !== null)

const kbOptions = ref<KnowledgeBase[]>([])
const docOptions = ref<KbDocument[]>([])
const docLoading = ref(false)

async function searchKbs(keyword = ''): Promise<void> {
  kbOptions.value = (await listKnowledgeBases({ keyword, page: 1, size: 50 })).items
}

async function searchDocs(keyword = ''): Promise<void> {
  const kbIds = form.kb_ids.length ? form.kb_ids : kbOptions.value.slice(0, 5).map((kb) => kb.id)
  if (!kbIds.length) return
  docLoading.value = true
  try {
    const pages = await Promise.all(
      kbIds.map((id) => listDocuments(id, { keyword: keyword || undefined, page: 1, size: 20 })),
    )
    const found = pages.flatMap((p) => p.items)
    const kept = docOptions.value.filter((d) => form.expected_document_ids.includes(d.id))
    const ids = new Set(found.map((d) => d.id))
    docOptions.value = [...kept.filter((d) => !ids.has(d.id)), ...found]
  } finally {
    docLoading.value = false
  }
}

function docLabel(id: string): string {
  return docOptions.value.find((d) => d.id === id)?.title ?? id
}

watch(visible, async (open) => {
  if (!open) return
  const c = props.evalCase
  Object.assign(form, {
    question: c?.question ?? '',
    reference_answer: c?.reference_answer ?? '',
    expected_document_ids: [...(c?.expected_document_ids ?? [])],
    expected_chunk_ids: [...(c?.expected_chunk_ids ?? [])],
    kb_ids: [...(c?.kb_ids ?? [])],
    tags: [...(c?.tags ?? [])],
  })
  docOptions.value = []
  formRef.value?.clearValidate()
  await searchKbs()
  await searchDocs()
})

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const body: EvalCaseFields = {
      ...form,
      question: form.question.trim(),
      reference_answer: form.reference_answer?.trim() || null,
    }
    const saved = props.evalCase
      ? await updateEvalCase(props.evalCase.id, body)
      : await createEvalCase(props.datasetId, body)
    ElMessage.success(t('common.saved'))
    emit('saved', saved)
    visible.value = false
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="isEdit ? t('evaluation.caseDialog.edit') : t('evaluation.shared.addCase')"
    width="720px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
      <el-form-item :label="t('evaluation.shared.question')" prop="question">
        <el-input v-model="form.question" type="textarea" :rows="2" maxlength="2000" />
      </el-form-item>
      <el-form-item :label="t('evaluation.shared.referenceAnswer')">
        <el-input
          v-model="form.reference_answer"
          type="textarea"
          :rows="4"
          :placeholder="t('evaluation.caseDialog.referencePlaceholder')"
        />
      </el-form-item>
      <el-form-item :label="t('evaluation.shared.kbScope')">
        <el-select
          v-model="form.kb_ids"
          multiple
          filterable
          remote
          :remote-method="searchKbs"
          :placeholder="t('evaluation.caseDialog.kbPlaceholder')"
          style="width: 100%"
          @change="searchDocs()"
        >
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('evaluation.caseDialog.expectedDocs')">
        <el-select
          v-model="form.expected_document_ids"
          multiple
          filterable
          remote
          allow-create
          default-first-option
          :remote-method="searchDocs"
          :loading="docLoading"
          :placeholder="t('evaluation.caseDialog.docPlaceholder')"
          style="width: 100%"
        >
          <el-option v-for="doc in docOptions" :key="doc.id" :label="doc.title" :value="doc.id">
            <span>{{ doc.title }}</span>
            <span class="meta">{{ doc.filename }}</span>
          </el-option>
          <template #tag>
            <el-tag
              v-for="id in form.expected_document_ids"
              :key="id"
              closable
              size="small"
              @close="
                form.expected_document_ids = form.expected_document_ids.filter((x) => x !== id)
              "
            >
              {{ docLabel(id) }}
            </el-tag>
          </template>
        </el-select>
      </el-form-item>
      <el-form-item :label="t('evaluation.caseDialog.expectedChunks')">
        <el-select
          v-model="form.expected_chunk_ids"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          :placeholder="t('evaluation.caseDialog.chunkPlaceholder')"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item :label="t('evaluation.shared.tags')">
        <el-select
          v-model="form.tags"
          multiple
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          :placeholder="t('evaluation.caseDialog.tagsPlaceholder')"
          style="width: 100%"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.meta {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
