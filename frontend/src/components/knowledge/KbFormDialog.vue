<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge'
import type { AclPermission, KbVisibility, KnowledgeBase } from '@/api/types'
import { REVIEW_INTERVALS, reviewIntervalLabel } from '@/utils/document'

const props = defineProps<{ kb?: KnowledgeBase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [kb: KnowledgeBase] }>()
const { t } = useI18n()

type PolicyTemplate = 'custom' | 'controlled'

const formRef = ref<FormInstance>()
const saving = ref(false)
const policyTemplate = ref<PolicyTemplate>('custom')
const form = reactive({
  name: '',
  description: '' as string | null,
  visibility: 'restricted' as KbVisibility,
  watermark: false,
  copy_protect: false,
  download_permission: 'read' as AclPermission,
  /** 0 = no periodic review (options cannot be null). */
  review_interval_days: 0,
})
const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('knowledge.kb.nameRequired'), trigger: 'blur' }],
}))

function applyTemplate(kind: PolicyTemplate): void {
  policyTemplate.value = kind
  if (kind === 'controlled') {
    form.visibility = 'restricted'
    form.watermark = true
    form.copy_protect = true
    form.download_permission = 'edit'
  }
}

watch(visible, (open) => {
  if (!open) return
  form.name = props.kb?.name ?? ''
  form.description = props.kb?.description ?? ''
  form.visibility = props.kb?.visibility ?? 'restricted'
  form.watermark = props.kb?.watermark ?? false
  form.copy_protect = props.kb?.copy_protect ?? false
  form.download_permission = props.kb?.download_permission ?? 'read'
  form.review_interval_days = props.kb?.review_interval_days ?? 0
  policyTemplate.value = 'custom'
})

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const description = form.description || null
    const protection = {
      watermark: form.watermark,
      copy_protect: form.copy_protect,
      download_permission: form.download_permission,
      review_interval_days: form.review_interval_days || null,
    }
    const kb = props.kb
      ? await updateKnowledgeBase(props.kb.id, { name: form.name, description, ...protection })
      : await createKnowledgeBase({
          name: form.name,
          description,
          visibility: form.visibility,
          ...protection,
        })
    ElMessage.success(t('knowledge.kb.savedSuccess'))
    visible.value = false
    emit('saved', kb)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="kb ? t('knowledge.kb.edit') : t('knowledge.kb.create')"
    width="520px"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
      <el-form-item :label="t('common.name')" prop="name">
        <el-input v-model="form.name" maxlength="128" show-word-limit />
      </el-form-item>
      <el-form-item :label="t('common.description')">
        <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
      </el-form-item>
      <el-form-item v-if="!kb" :label="t('knowledge.visibility.label')">
        <el-radio-group v-model="form.visibility">
          <el-radio value="restricted">{{ t('knowledge.visibility.restricted') }}</el-radio>
          <el-radio value="org">{{ t('knowledge.visibility.orgAll') }}</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="!kb" :label="t('knowledge.kb.templateLabel')">
        <el-radio-group
          :model-value="policyTemplate"
          data-test="kb-policy-template"
          @update:model-value="(v) => applyTemplate(v as PolicyTemplate)"
        >
          <el-radio-button value="custom">{{ t('knowledge.kb.templateCustom') }}</el-radio-button>
          <el-radio-button value="controlled">{{
            t('knowledge.kb.templateControlled')
          }}</el-radio-button>
        </el-radio-group>
        <div class="hint hint--block hint--template">{{ t('knowledge.kb.templateHint') }}</div>
      </el-form-item>
      <el-divider content-position="left">{{ t('knowledge.protect.title') }}</el-divider>
      <el-form-item :label="t('knowledge.protect.watermark')">
        <el-switch v-model="form.watermark" data-test="kb-watermark" />
        <span class="hint">{{ t('knowledge.protect.watermarkHint') }}</span>
      </el-form-item>
      <el-form-item :label="t('knowledge.protect.copy')">
        <el-switch v-model="form.copy_protect" data-test="kb-copy-protect" />
        <span class="hint">{{ t('knowledge.protect.copyHint') }}</span>
      </el-form-item>
      <el-form-item :label="t('knowledge.protect.downloadLabel')">
        <el-select v-model="form.download_permission" data-test="kb-download">
          <el-option :label="t('knowledge.protect.download.read')" value="read" />
          <el-option :label="t('knowledge.protect.download.edit')" value="edit" />
          <el-option :label="t('knowledge.protect.download.manage')" value="manage" />
        </el-select>
      </el-form-item>
      <div class="hint hint--block">{{ t('knowledge.protect.kbHint') }}</div>
      <el-divider content-position="left">{{ t('knowledge.review.kbTitle') }}</el-divider>
      <el-form-item :label="t('knowledge.review.interval')">
        <el-select v-model="form.review_interval_days" data-test="kb-review-interval">
          <el-option :label="t('knowledge.review.intervalNone')" :value="0" />
          <el-option
            v-for="days in REVIEW_INTERVALS"
            :key="days"
            :label="reviewIntervalLabel(days)"
            :value="days"
          />
        </el-select>
      </el-form-item>
      <div class="hint hint--block">{{ t('knowledge.review.kbHint') }}</div>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" data-test="kb-save" @click="submit">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hint {
  margin-left: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.hint--block {
  display: block;
  margin: -6px 0 0 96px;
}
.hint--template {
  margin-top: 8px;
  margin-left: 0;
}
</style>
