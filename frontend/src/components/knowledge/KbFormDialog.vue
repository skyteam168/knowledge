<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge'
import type { KbVisibility, KnowledgeBase } from '@/api/types'

const props = defineProps<{ kb?: KnowledgeBase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [kb: KnowledgeBase] }>()
const { t } = useI18n()

const formRef = ref<FormInstance>()
const saving = ref(false)
const form = reactive({
  name: '',
  description: '' as string | null,
  visibility: 'restricted' as KbVisibility,
})
const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('knowledge.kb.nameRequired'), trigger: 'blur' }],
}))

watch(visible, (open) => {
  if (!open) return
  form.name = props.kb?.name ?? ''
  form.description = props.kb?.description ?? ''
  form.visibility = props.kb?.visibility ?? 'restricted'
})

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const description = form.description || null
    const kb = props.kb
      ? await updateKnowledgeBase(props.kb.id, { name: form.name, description })
      : await createKnowledgeBase({ name: form.name, description, visibility: form.visibility })
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
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
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
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" data-test="kb-save" @click="submit">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>
</template>
