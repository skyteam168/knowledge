<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { getDocumentAcl, setDocumentAcl } from '@/api/knowledge'
import type { AclEntryOut, KbDocument, KbVisibility } from '@/api/types'
import AclEditor from './AclEditor.vue'

const props = defineProps<{ document: KbDocument | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [] }>()
const { t } = useI18n()

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
    :title="t('knowledge.acl.docTitle', { title: document?.title ?? '' })"
    width="720px"
  >
    <div v-loading="loading">
      <el-form label-width="100px">
        <el-form-item :label="t('knowledge.acl.inheritKb')">
          <el-switch
            v-model="inherit"
            :active-text="t('knowledge.acl.inherit')"
            :inactive-text="t('knowledge.acl.custom')"
          />
        </el-form-item>
      </el-form>
      <template v-if="inherit">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          :title="
            kbVisibility === 'org'
              ? t('knowledge.acl.inheritOrgTip')
              : t('knowledge.acl.inheritRestrictedTip')
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
          :title="t('knowledge.acl.customTip')"
          class="tip"
        />
        <AclEditor v-model="entries" />
      </template>
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
