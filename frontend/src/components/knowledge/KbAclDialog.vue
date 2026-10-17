<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getKnowledgeBaseAcl, setKnowledgeBaseAcl } from '@/api/knowledge'
import type { AclEntryOut, KbVisibility, KnowledgeBase } from '@/api/types'
import AclEditor from './AclEditor.vue'

const props = defineProps<{ kb: KnowledgeBase | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()
const { t } = useI18n()

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
    ElMessage.success(t('knowledge.acl.updated'))
    visible.value = false
    emit('saved')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="t('knowledge.acl.kbTitle', { name: kb?.name ?? '' })"
    width="720px"
  >
    <div v-loading="loading">
      <el-form label-width="88px">
        <el-form-item :label="t('knowledge.visibility.label')">
          <el-radio-group v-model="visibility">
            <el-radio value="restricted">{{ t('knowledge.visibility.restricted') }}</el-radio>
            <el-radio value="org">{{ t('knowledge.visibility.orgAll') }}</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        :title="t('knowledge.acl.kbTip')"
        class="tip"
      />
      <AclEditor v-if="visible" v-model="entries" />
    </div>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" @click="submit">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.tip {
  margin-bottom: 12px;
}
</style>
