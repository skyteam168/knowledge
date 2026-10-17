<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { createApiClient, getOpenApiOptions, updateApiClient } from '@/api/openApi'
import type {
  ApiClient,
  ApiClientBody,
  ApiPrincipalRef,
  ApiPrincipalType,
  ApiScope,
  OpenApiOptions,
} from '@/api/types'
import { SCOPES, scopeDesc, scopeLabel } from './meta'

const props = defineProps<{ client?: ApiClient | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [client: ApiClient] }>()
const { t } = useI18n()

const options = ref<OpenApiOptions | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  description: '',
  owner_department_id: '' as string,
  contact: '',
  kb_ids: [] as string[],
  dept: [] as string[],
  group: [] as string[],
  role: [] as string[],
  scopes: ['retrieve'] as ApiScope[],
  rate_limit_per_minute: 0,
  daily_quota: 0,
  ip_text: '',
  expires_at: null as string | null,
})

const editing = computed(() => !!props.client)

const principalsValid = (_: unknown, __: unknown, cb: (e?: Error) => void) =>
  form.dept.length + form.group.length + form.role.length
    ? cb()
    : cb(new Error(t('openApi.editor.rules.principals')))

const rules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('openApi.editor.rules.name'), trigger: 'blur' }],
  kb_ids: [{ type: 'array', required: true, min: 1, message: t('openApi.editor.rules.kbs') }],
  principals: [{ validator: principalsValid }],
  scopes: [{ type: 'array', required: true, min: 1, message: t('openApi.editor.rules.scopes') }],
}))

function reset(): void {
  const c = props.client
  const ids = (type: ApiPrincipalType) =>
    (c?.principals ?? []).filter((p) => p.type === type).map((p) => p.id)
  Object.assign(form, {
    name: c?.name ?? '',
    description: c?.description ?? '',
    owner_department_id: c?.owner_department_id ?? '',
    contact: c?.contact ?? '',
    kb_ids: c ? c.kbs.map((k) => k.id) : [],
    dept: ids('dept'),
    group: ids('group'),
    role: ids('role'),
    scopes: c ? [...c.scopes] : ['retrieve'],
    rate_limit_per_minute: c?.rate_limit_per_minute ?? 0,
    daily_quota: c?.daily_quota ?? 0,
    ip_text: (c?.ip_allowlist ?? []).join('\n'),
    expires_at: c?.expires_at ?? null,
  })
  formRef.value?.clearValidate()
}

watch(visible, async (open) => {
  if (!open) return
  reset()
  if (!options.value) options.value = await getOpenApiOptions()
})

function principals(): ApiPrincipalRef[] {
  return [
    ...form.dept.map((id) => ({ type: 'dept' as const, id })),
    ...form.group.map((id) => ({ type: 'group' as const, id })),
    ...form.role.map((id) => ({ type: 'role' as const, id })),
  ]
}

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  const body: ApiClientBody = {
    name: form.name.trim(),
    description: form.description.trim() || null,
    owner_department_id: form.owner_department_id || null,
    contact: form.contact.trim() || null,
    kb_ids: form.kb_ids,
    principals: principals(),
    scopes: form.scopes,
    rate_limit_per_minute: form.rate_limit_per_minute,
    daily_quota: form.daily_quota,
    ip_allowlist: form.ip_text
      .split(/[\n,，\s]+/)
      .map((s) => s.trim())
      .filter(Boolean),
    expires_at: form.expires_at,
  }
  saving.value = true
  try {
    const saved = props.client
      ? await updateApiClient(props.client.id, {
          ...body,
          clear_expires_at: !form.expires_at && !!props.client.expires_at,
        })
      : await createApiClient(body)
    ElMessage.success(editing.value ? t('common.saved') : t('openApi.editor.created'))
    visible.value = false
    emit('saved', saved)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="editing ? t('openApi.editor.titleEdit') : t('openApi.editor.titleCreate')"
    size="600px"
    destroy-on-close
  >
    <el-form
      ref="formRef"
      v-loading="!options"
      :model="form"
      :rules="rules"
      label-position="top"
      class="editor"
    >
      <div class="editor__section">{{ t('openApi.editor.basicInfo') }}</div>
      <el-form-item :label="t('openApi.editor.name')" prop="name">
        <el-input
          v-model="form.name"
          maxlength="128"
          :placeholder="t('openApi.editor.namePlaceholder')"
        />
      </el-form-item>
      <div class="editor__row">
        <el-form-item :label="t('openApi.editor.ownerDepartment')">
          <el-select
            v-model="form.owner_department_id"
            clearable
            filterable
            :placeholder="t('openApi.editor.optional')"
          >
            <el-option
              v-for="d in options?.departments ?? []"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('openApi.editor.contact')">
          <el-input
            v-model="form.contact"
            maxlength="255"
            :placeholder="t('openApi.editor.optional')"
          />
        </el-form-item>
      </div>
      <el-form-item :label="t('openApi.editor.description')">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="2"
          maxlength="2000"
          :placeholder="t('openApi.editor.descriptionPlaceholder')"
        />
      </el-form-item>

      <div class="editor__section">
        {{ t('openApi.editor.scopeSection') }}
        <span class="editor__hint">{{ t('openApi.editor.scopeHint') }}</span>
      </div>
      <el-form-item :label="t('openApi.fields.kbsLimit')" prop="kb_ids">
        <el-select
          v-model="form.kb_ids"
          multiple
          filterable
          :placeholder="t('openApi.editor.kbsPlaceholder')"
          data-test="kb-select"
        >
          <el-option
            v-for="kb in options?.kbs ?? []"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('openApi.editor.principals')" prop="principals">
        <div class="editor__principals">
          <el-select
            v-model="form.dept"
            multiple
            filterable
            :placeholder="t('openApi.editor.deptPlaceholder')"
          >
            <el-option
              v-for="d in options?.departments ?? []"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
          <el-select
            v-model="form.group"
            multiple
            filterable
            :placeholder="t('openApi.editor.groupPlaceholder')"
          >
            <el-option
              v-for="g in options?.groups ?? []"
              :key="g.id"
              :label="g.name"
              :value="g.id"
            />
          </el-select>
          <el-select
            v-model="form.role"
            multiple
            filterable
            :placeholder="t('openApi.editor.rolePlaceholder')"
          >
            <el-option
              v-for="r in options?.roles ?? []"
              :key="r.id"
              :label="r.name"
              :value="r.id"
            />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item :label="t('openApi.fields.scopes')" prop="scopes">
        <el-checkbox-group v-model="form.scopes" class="editor__scopes">
          <el-checkbox
            v-for="scope in SCOPES"
            :key="scope"
            :value="scope"
            border
            class="editor__scope"
          >
            <span class="editor__scope-label">{{ scopeLabel(scope) }}</span>
            <span class="editor__scope-desc">{{ scopeDesc(scope) }}</span>
          </el-checkbox>
        </el-checkbox-group>
      </el-form-item>

      <div class="editor__section">{{ t('openApi.fields.security') }}</div>
      <div class="editor__row">
        <el-form-item :label="t('openApi.editor.ratePerMinute')">
          <el-input-number v-model="form.rate_limit_per_minute" :min="0" :max="6000" />
          <div class="editor__tip">
            {{ t('openApi.editor.rateDefaultTip', { n: options?.default_rate_per_minute ?? '—' }) }}
          </div>
        </el-form-item>
        <el-form-item :label="t('openApi.editor.dailyQuota')">
          <el-input-number v-model="form.daily_quota" :min="0" :max="10000000" :step="100" />
          <div class="editor__tip">{{ t('openApi.editor.unlimitedTip') }}</div>
        </el-form-item>
      </div>
      <el-form-item :label="t('openApi.editor.ipAllowlist')">
        <el-input
          v-model="form.ip_text"
          type="textarea"
          :rows="2"
          :placeholder="t('openApi.editor.ipPlaceholder')"
        />
      </el-form-item>
      <el-form-item :label="t('openApi.editor.expiresAt')">
        <el-date-picker
          v-model="form.expires_at"
          type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ssZ"
          :placeholder="t('openApi.editor.neverExpiresPlaceholder')"
          clearable
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" data-test="save-client" @click="submit">
        {{ editing ? t('common.save') : t('openApi.editor.createSubmit') }}
      </el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.editor__section {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 4px 0 12px;
  padding-left: 8px;
  font-weight: 600;
  color: var(--ekb-text-1);
  border-left: 3px solid var(--ekb-primary);
}
.editor__section:not(:first-child) {
  margin-top: 20px;
}
.editor__hint {
  font-size: 12px;
  font-weight: 400;
  color: var(--ekb-text-3);
}
.editor__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.editor__principals {
  display: grid;
  gap: 8px;
  width: 100%;
}
.editor__scopes {
  display: grid;
  gap: 8px;
  width: 100%;
}
.editor__scope {
  height: auto;
  margin: 0 !important;
  padding: 8px 12px;
}
.editor__scope :deep(.el-checkbox__label) {
  display: flex;
  flex-direction: column;
  white-space: normal;
}
.editor__scope-label {
  font-weight: 600;
}
.editor__scope-desc {
  font-size: 12px;
  color: var(--ekb-text-3);
}
.editor__tip {
  width: 100%;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.editor :deep(.el-select),
.editor :deep(.el-date-editor) {
  width: 100%;
}
</style>
