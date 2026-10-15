<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getKnowledgeBaseAcl, setKnowledgeBaseAcl } from '@/api/knowledge'
import type { AclEntryOut, KbVisibility, KnowledgeBase } from '@/api/types'
import AclEditor from './AclEditor.vue'

const props = defineProps<{ kb: KnowledgeBase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()

const loading = ref(false)
const saving = ref(false)
const visibility = ref<KbVisibility>('restricted')
const entries = ref<AclEntryOut[]>([])

watch(visible, async (open) => {
  if (!open || !props.kb) return
  loading.value = true
  try {
    const acl = await getKnowledgeBaseAcl(props.kb.id)
    visibility.value = acl.visibility
    entries.value = acl.entries
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (!props.kb) return
  saving.value = true
  try {
    await setKnowledgeBaseAcl(props.kb.id, {
      visibility: visibility.value,
      entries: entries.value.map(({ principal_type, principal_id, permission }) => ({
        principal_type,
        principal_id,
        permission,
      })),
    })
    ElMessage.success('权限已更新')
    visible.value = false
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" :title="`权限设置：${kb?.name ?? ''}`" width="720px">
    <div v-loading="loading">
      <el-form label-width="88px">
        <el-form-item label="可见范围">
          <el-radio-group v-model="visibility">
            <el-radio value="restricted">仅授权成员</el-radio>
            <el-radio value="org">组织内所有人可读</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="此处授权为知识库的默认权限，文档默认继承；授予部门时其下级部门同样生效。"
        class="tip"
      />
      <AclEditor v-if="visible" v-model="entries" />
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tip {
  margin-bottom: 12px;
}
</style>
