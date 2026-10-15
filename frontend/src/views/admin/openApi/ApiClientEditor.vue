<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
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
import { SCOPE_INFO } from './meta'

const props = defineProps<{ client?: ApiClient | null }>()
const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ saved: [client: ApiClient] }>()

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
    : cb(new Error('至少绑定一个部门、用户组或角色'))

const rules: FormRules = {
  name: [{ required: true, message: '请输入应用名称', trigger: 'blur' }],
  kb_ids: [{ type: 'array', required: true, min: 1, message: '至少授权一个知识库' }],
  principals: [{ validator: principalsValid }],
  scopes: [{ type: 'array', required: true, min: 1, message: '至少开通一项能力' }],
}

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
    ElMessage.success(editing.value ? '已保存' : '已创建，请在详情页签发密钥')
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
    :title="editing ? '编辑接入应用' : '新建接入应用'"
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
      <div class="editor__section">基本信息</div>
      <el-form-item label="应用名称" prop="name">
        <el-input v-model="form.name" maxlength="128" placeholder="如：财务部报销助手 Agent" />
      </el-form-item>
      <div class="editor__row">
        <el-form-item label="所属部门">
          <el-select v-model="form.owner_department_id" clearable filterable placeholder="可选">
            <el-option
              v-for="d in options?.departments ?? []"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="负责人 / 联系方式">
          <el-input v-model="form.contact" maxlength="255" placeholder="可选" />
        </el-form-item>
      </div>
      <el-form-item label="用途说明">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="2"
          maxlength="2000"
          placeholder="申请用途、调用场景，便于后续审计"
        />
      </el-form-item>

      <div class="editor__section">
        授权范围
        <span class="editor__hint">实际可见 = 授权知识库 ∩ 绑定身份在 ACL 中可读的内容</span>
      </div>
      <el-form-item label="授权知识库（上限）" prop="kb_ids">
        <el-select
          v-model="form.kb_ids"
          multiple
          filterable
          placeholder="选择可被该应用检索的知识库"
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
      <el-form-item label="代理身份（按部门 / 用户组 / 角色的文档权限过滤）" prop="principals">
        <div class="editor__principals">
          <el-select v-model="form.dept" multiple filterable placeholder="部门（含上级继承）">
            <el-option
              v-for="d in options?.departments ?? []"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
          <el-select v-model="form.group" multiple filterable placeholder="用户组">
            <el-option
              v-for="g in options?.groups ?? []"
              :key="g.id"
              :label="g.name"
              :value="g.id"
            />
          </el-select>
          <el-select v-model="form.role" multiple filterable placeholder="角色（仅用于文档 ACL）">
            <el-option
              v-for="r in options?.roles ?? []"
              :key="r.id"
              :label="r.name"
              :value="r.id"
            />
          </el-select>
        </div>
      </el-form-item>
      <el-form-item label="开通能力" prop="scopes">
        <el-checkbox-group v-model="form.scopes" class="editor__scopes">
          <el-checkbox
            v-for="(info, scope) in SCOPE_INFO"
            :key="scope"
            :value="scope"
            border
            class="editor__scope"
          >
            <span class="editor__scope-label">{{ info.label }}</span>
            <span class="editor__scope-desc">{{ info.desc }}</span>
          </el-checkbox>
        </el-checkbox-group>
      </el-form-item>

      <div class="editor__section">安全与配额</div>
      <div class="editor__row">
        <el-form-item label="每分钟请求上限">
          <el-input-number v-model="form.rate_limit_per_minute" :min="0" :max="6000" />
          <div class="editor__tip">
            0 = 使用默认值（{{ options?.default_rate_per_minute ?? '—' }} 次/分钟）
          </div>
        </el-form-item>
        <el-form-item label="每日调用配额">
          <el-input-number v-model="form.daily_quota" :min="0" :max="10000000" :step="100" />
          <div class="editor__tip">0 = 不限</div>
        </el-form-item>
      </div>
      <el-form-item label="IP 白名单">
        <el-input
          v-model="form.ip_text"
          type="textarea"
          :rows="2"
          placeholder="每行一个 IP 或 CIDR，如 10.20.0.0/16；留空表示不限制"
        />
      </el-form-item>
      <el-form-item label="应用有效期">
        <el-date-picker
          v-model="form.expires_at"
          type="datetime"
          value-format="YYYY-MM-DDTHH:mm:ssZ"
          placeholder="留空表示长期有效"
          clearable
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" data-test="save-client" @click="submit">
        {{ editing ? '保存' : '创建应用' }}
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
