<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getDocumentAcl, setDocumentAcl } from '@/api/knowledge'
import type { AclEntryOut, KbDocument, KbVisibility } from '@/api/types'
import AclEditor from './AclEditor.vue'

const props = defineProps<{ document: KbDocument | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()

const loading = ref(false)
const saving = ref(false)
const inherit = ref(true)
const kbVisibility = ref<KbVisibility>('restricted')
const kbEntries = ref<AclEntryOut[]>([])
const entries = ref<AclEntryOut[]>([])

watch(visible, async (open) => {
  if (!open || !props.document) return
  loading.value = true
  try {
    const acl = await getDocumentAcl(props.document.id)
    inherit.value = acl.inherit
    kbVisibility.value = acl.kb_visibility
    kbEntries.value = acl.kb_entries
    entries.value = acl.entries
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (!props.document) return
  saving.value = true
  try {
    await setDocumentAcl(props.document.id, {
      inherit: inherit.value,
      entries: inherit.value
        ? []
        : entries.value.map(({ principal_type, principal_id, permission }) => ({
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
  <el-dialog v-model="visible" :title="`文档权限：${document?.title ?? ''}`" width="720px">
    <div v-loading="loading">
      <el-form label-width="100px">
        <el-form-item label="继承知识库">
          <el-switch v-model="inherit" active-text="继承" inactive-text="单独设置" />
        </el-form-item>
      </el-form>
      <template v-if="inherit">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          :title="
            kbVisibility === 'org'
              ? '继承知识库权限：组织内所有人可读，以及以下授权'
              : '继承知识库权限：仅以下授权成员可访问'
          "
          class="tip"
        />
        <AclEditor v-model="kbEntries" disabled />
      </template>
      <template v-else>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="单独设置后仅以下成员（及知识库管理员）可访问该文档"
          class="tip"
        />
        <AclEditor v-model="entries" />
      </template>
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
