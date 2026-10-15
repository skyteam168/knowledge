<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createDirectorySource, testDirectorySource, updateDirectorySource } from '@/api/directory'
import type { DirectorySource, DirectorySourceType, DirectoryTestResult } from '@/api/types'
import { CONFIG_FIELDS, SOURCE_TYPES, type ConfigField } from './meta'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ source: DirectorySource | null; usedTypes: DirectorySourceType[] }>()
const emit = defineEmits<{ saved: [DirectorySource] }>()

const form = reactive({
  type: 'wecom' as DirectorySourceType,
  name: '',
  is_primary: false,
  enabled: true,
  sync_interval_minutes: 0,
  config: {} as Record<string, unknown>,
})
const saving = ref(false)
const testing = ref(false)
const testResult = ref<DirectoryTestResult | null>(null)

const editing = computed(() => props.source !== null)
const fields = computed(() => CONFIG_FIELDS[form.type])
const groups = computed(() => {
  const result: { title: string | null; fields: ConfigField[] }[] = []
  for (const field of fields.value) {
    const title = field.group ?? null
    const last = result[result.length - 1]
    if (last && last.title === title) last.fields.push(field)
    else result.push({ title, fields: [field] })
  }
  return result
})
const availableTypes = computed(() =>
  SOURCE_TYPES.filter((t) => editing.value || !props.usedTypes.includes(t.value)),
)

watch(visible, (open) => {
  if (!open) return
  testResult.value = null
  const s = props.source
  if (s) {
    Object.assign(form, {
      type: s.type,
      name: s.name,
      is_primary: s.is_primary,
      enabled: s.enabled,
      sync_interval_minutes: s.sync_interval_minutes,
      config: { ...s.config },
    })
  } else {
    const first = availableTypes.value[0]?.value ?? 'wecom'
    Object.assign(form, {
      type: first,
      name: SOURCE_TYPES.find((t) => t.value === first)?.label ?? '',
      is_primary: false,
      enabled: true,
      sync_interval_minutes: 0,
      config: defaults(first),
    })
  }
})

function defaults(type: DirectorySourceType): Record<string, unknown> {
  if (type === 'weaver') return { db_type: 'sqlserver', include_subcompanies: true }
  if (type === 'wecom') return { employee_no_attr: '工号' }
  return {}
}

function changeType(type: DirectorySourceType): void {
  form.config = defaults(type)
  form.name = SOURCE_TYPES.find((t) => t.value === type)?.label ?? form.name
  testResult.value = null
}

function secretSet(field: ConfigField): boolean {
  return field.type === 'password' && !!props.source?.secrets_set.includes(field.key)
}

function cleanConfig(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(form.config)) {
    if (value === '' || value === null || value === undefined) continue
    out[key] = value
  }
  return out
}

function validate(): boolean {
  for (const field of fields.value) {
    if (!field.required) continue
    const value = form.config[field.key]
    if ((value === undefined || value === '') && !secretSet(field)) {
      ElMessage.warning(`请填写「${field.label}」`)
      return false
    }
  }
  return true
}

async function test(): Promise<void> {
  if (!validate()) return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testDirectorySource({
      type: form.type,
      config: cleanConfig(),
      source_id: props.source?.id,
    })
  } finally {
    testing.value = false
  }
}

async function save(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('请填写名称')
    return
  }
  if (!validate()) return
  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      is_primary: form.is_primary,
      enabled: form.enabled,
      sync_interval_minutes: form.type === 'excel' ? 0 : form.sync_interval_minutes,
      config: cleanConfig(),
    }
    const saved = props.source
      ? await updateDirectorySource(props.source.id, body)
      : await createDirectorySource({ type: form.type, ...body })
    ElMessage.success('已保存')
    visible.value = false
    emit('saved', saved)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="editing ? '编辑数据源' : '新增数据源'"
    width="640px"
    destroy-on-close
    data-test="source-editor"
  >
    <el-form label-width="150px" @submit.prevent>
      <el-form-item label="类型">
        <el-radio-group
          v-model="form.type"
          :disabled="editing"
          class="type-group"
          @change="(v) => changeType(v as DirectorySourceType)"
        >
          <el-radio v-for="t in availableTypes" :key="t.value" :value="t.value" border>
            {{ t.label }}
          </el-radio>
        </el-radio-group>
        <div class="help">{{ SOURCE_TYPES.find((t) => t.value === form.type)?.desc }}</div>
      </el-form-item>
      <el-form-item label="名称" required>
        <el-input v-model="form.name" maxlength="128" />
      </el-form-item>
      <el-form-item label="主数据源">
        <el-switch v-model="form.is_primary" />
        <div class="help">
          主数据源管理部门树、人员、部门归属与职务（这些字段在后台变为只读）；
          非主数据源只用于绑定身份（扫码登录）。每个组织只能有一个主数据源。
        </div>
      </el-form-item>
      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
      <el-form-item v-if="form.type !== 'excel'" label="自动同步间隔">
        <el-input-number
          v-model="form.sync_interval_minutes"
          :min="0"
          :max="10080"
          :step="60"
          controls-position="right"
        />
        <span class="unit">分钟</span>
        <div class="help">0 表示只手动同步；自动同步最少 10 分钟，建议 60 或 1440。</div>
      </el-form-item>

      <template v-for="group in groups" :key="group.title ?? 'main'">
        <el-divider v-if="group.title" content-position="left">{{ group.title }}</el-divider>
        <el-form-item
          v-for="field in group.fields"
          :key="field.key"
          :label="field.label"
          :required="field.required"
        >
          <el-select
            v-if="field.type === 'select'"
            :model-value="String(form.config[field.key] ?? '')"
            style="width: 100%"
            @update:model-value="(v: string) => (form.config[field.key] = v)"
          >
            <el-option
              v-for="o in field.options"
              :key="o.value"
              :label="o.label"
              :value="o.value"
            />
          </el-select>
          <el-switch
            v-else-if="field.type === 'switch'"
            :model-value="form.config[field.key] !== false"
            @update:model-value="(v) => (form.config[field.key] = v)"
          />
          <el-input-number
            v-else-if="field.type === 'number'"
            :model-value="(form.config[field.key] as number | undefined) ?? undefined"
            :placeholder="field.placeholder"
            controls-position="right"
            style="width: 100%"
            @update:model-value="(v) => (form.config[field.key] = v ?? undefined)"
          />
          <el-input
            v-else-if="field.type === 'textarea'"
            v-model="form.config[field.key] as string"
            type="textarea"
            :rows="3"
            :placeholder="field.placeholder"
          />
          <el-input
            v-else
            v-model="form.config[field.key] as string"
            :type="field.type === 'password' ? 'password' : 'text'"
            :show-password="field.type === 'password'"
            :placeholder="secretSet(field) ? '已设置，留空保持不变' : field.placeholder"
            autocomplete="new-password"
          />
          <div v-if="field.help" class="help">{{ field.help }}</div>
        </el-form-item>
      </template>

      <el-alert
        v-if="form.type === 'excel'"
        type="info"
        :closable="false"
        show-icon
        title="Excel 数据源保存后，在列表中下载模板、填写并上传即可预览和应用。"
      />

      <el-alert
        v-if="testResult"
        :type="testResult.ok ? 'success' : 'error'"
        :closable="false"
        show-icon
        class="test-result"
        data-test="test-result"
      >
        <template #title>
          <span v-if="testResult.ok">
            连接成功：{{ testResult.departments }} 个部门，{{ testResult.users }} 人（在职
            {{ testResult.active_users }}），耗时 {{ testResult.duration_ms }} ms
          </span>
          <span v-else>连接失败：{{ testResult.error }}</span>
        </template>
        <ul v-if="testResult.warnings.length" class="warnings">
          <li v-for="w in testResult.warnings" :key="w">{{ w }}</li>
        </ul>
      </el-alert>
    </el-form>
    <template #footer>
      <el-button
        v-if="form.type !== 'excel'"
        :loading="testing"
        data-test="test-connection"
        @click="test"
      >
        测试连接
      </el-button>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" data-test="save-source" @click="save"
        >保存</el-button
      >
    </template>
  </el-dialog>
</template>

<style scoped>
.type-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.type-group :deep(.el-radio) {
  margin-right: 0;
}
.help {
  width: 100%;
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ekb-text-3);
}
.unit {
  margin-left: 8px;
  color: var(--ekb-text-3);
}
.test-result {
  margin-top: 8px;
}
.warnings {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
}
</style>
