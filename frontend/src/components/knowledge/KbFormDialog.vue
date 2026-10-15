<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createKnowledgeBase, updateKnowledgeBase } from '@/api/knowledge'
import type { KbVisibility, KnowledgeBase } from '@/api/types'

const props = defineProps<{ kb?: KnowledgeBase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [kb: KnowledgeBase] }>()

const formRef = ref<FormInstance>()
const saving = ref(false)
const form = reactive({
  name: '',
  description: '' as string | null,
  visibility: 'restricted' as KbVisibility,
})
const rules: FormRules = {
  name: [{ required: true, message: '请输入知识库名称', trigger: 'blur' }],
}

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
    ElMessage.success('保存成功')
    visible.value = false
    emit('saved', kb)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="kb ? '编辑知识库' : '新建知识库'" width="520px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" maxlength="128" show-word-limit />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="3" maxlength="2000" />
      </el-form-item>
      <el-form-item v-if="!kb" label="可见范围">
        <el-radio-group v-model="form.visibility">
          <el-radio value="restricted">仅授权成员</el-radio>
          <el-radio value="org">组织内所有人可读</el-radio>
        </el-radio-group>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" data-test="kb-save" @click="submit">
        保存
      </el-button>
    </template>
  </el-dialog>
</template>
