<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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

const denyEntries = computed({
  get: () => entries.value.filter((e) => (e.effect ?? 'allow') === 'deny'),
  set: (rows: AclEntryOut[]) => {
    const allows = entries.value.filter((e) => (e.effect ?? 'allow') !== 'deny')
    entries.value = [...allows, ...rows.map((r) => ({ ...r, effect: 'deny' as const, permission: 'read' as const }))]
  },
})

const allowEntries = computed({
  get: () => entries.value.filter((e) => (e.effect ?? 'allow') !== 'deny'),
  set: (rows: AclEntryOut[]) => {
    const denies = entries.value.filter((e) => (e.effect ?? 'allow') === 'deny')
    entries.value = [...rows.map((r) => ({ ...r, effect: r.effect ?? ('allow' as const) })), ...denies]
  },
})

watch(visible, async (open) => {
  if (!open || !props.document) return
  loading.value = true
  try {
    const acl = await getDocumentAcl(props.document.id)
    inherit.value = acl.inherit
    kbVisibility.value = acl.kb_visibility
    kbEntries.value = acl.kb_entries
    entries.value = acl.entries.map((e) => ({ ...e, effect: e.effect ?? 'allow' }))
  } finally {
    loading.value = false
  }
})

async function submit(): Promise<void> {
  if (!props.document) return
  saving.value = true
  try {
    const payload = inherit.value
      ? denyEntries.value
      : entries.value
    await setDocumentAcl(props.document.id, {
      inherit: inherit.value,
      entries: payload.map(({ principal_type, principal_id, permission, effect }) => ({
        principal_type,
        principal_id,
        permission: effect === 'deny' ? 'read' : permission,
        effect: effect ?? 'allow',
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
    width="760px"
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
        <h4 class="deny-title">{{ t('knowledge.acl.denySection') }}</h4>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          :title="t('knowledge.acl.denyTip')"
          class="tip"
        />
        <AclEditor v-model="denyEntries" deny-only />
      </template>
      <template v-else>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          :title="t('knowledge.acl.customTip')"
          class="tip"
        />
        <AclEditor v-model="allowEntries" />
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
.deny-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
</style>
