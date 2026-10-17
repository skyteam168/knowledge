<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createEvalRun, listEvalDatasets } from '@/api/evaluation'
import { listRetrievalProfiles } from '@/api/search'
import type { EvalDataset, EvalRun, EvalRunCreate, RetrievalProfile } from '@/api/types'

const BUILTIN = 'builtin'

const props = defineProps<{ datasetId?: string }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ created: [EvalRun] }>()
const { t } = useI18n()

const formRef = ref<FormInstance>()
const form = reactive<EvalRunCreate>({
  dataset_id: '',
  profile_id: BUILTIN,
  name: '',
  judge_enabled: true,
})
const rules = computed<FormRules>(() => ({
  dataset_id: [
    { required: true, message: t('evaluation.runDialog.datasetRequired'), trigger: 'change' },
  ],
}))
const datasets = ref<EvalDataset[]>([])
const profiles = ref<RetrievalProfile[]>([])
const saving = ref(false)

function profileValue(p: RetrievalProfile): string {
  return p.id ?? BUILTIN
}

watch(visible, async (open) => {
  if (!open) return
  form.dataset_id = props.datasetId ?? ''
  form.name = ''
  form.judge_enabled = true
  const [ds, ps] = await Promise.all([
    listEvalDatasets({ page: 1, size: 100 }),
    listRetrievalProfiles(),
  ])
  datasets.value = ds.items
  profiles.value = ps
  const active = ps.find((p) => p.is_active) ?? ps[0]
  form.profile_id = active ? profileValue(active) : BUILTIN
  formRef.value?.clearValidate()
})

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const run = await createEvalRun({ ...form, name: form.name?.trim() || null })
    ElMessage.success(t('evaluation.runDialog.submitted'))
    emit('created', run)
    visible.value = false
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="t('evaluation.shared.runEval')" width="560px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-form-item :label="t('evaluation.shared.dataset')" prop="dataset_id">
        <el-select v-model="form.dataset_id" filterable style="width: 100%">
          <el-option
            v-for="ds in datasets"
            :key="ds.id"
            :label="t('evaluation.runDialog.datasetOption', { name: ds.name, n: ds.case_count })"
            :value="ds.id"
            :disabled="!ds.case_count"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('evaluation.shared.profile')">
        <el-select v-model="form.profile_id" style="width: 100%">
          <el-option
            v-for="p in profiles"
            :key="profileValue(p)"
            :label="p.name"
            :value="profileValue(p)"
          >
            <span>{{ p.name }}</span>
            <el-tag v-if="p.is_active" size="small" type="success" class="tag">{{
              t('evaluation.runDialog.active')
            }}</el-tag>
            <el-tag v-if="p.builtin" size="small" type="info" class="tag">{{
              t('evaluation.runDialog.builtin')
            }}</el-tag>
          </el-option>
        </el-select>
      </el-form-item>
      <el-form-item :label="t('evaluation.runDialog.name')">
        <el-input
          v-model="form.name"
          maxlength="128"
          :placeholder="t('evaluation.runDialog.namePlaceholder')"
        />
      </el-form-item>
      <el-form-item :label="t('evaluation.shared.judge')">
        <el-switch v-model="form.judge_enabled" />
        <span class="hint">{{ t('evaluation.runDialog.judgeHint') }}</span>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submit">{{
        t('evaluation.runDialog.start')
      }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tag {
  margin-left: 8px;
}

.hint {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
