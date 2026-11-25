<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  createActionType,
  createOntologyRule,
  listActionTypes,
  listOntologyRules,
  patchActionType,
  patchOntologyRule,
} from '@/api/ontology'
import type { ActionType, OntologyRule } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'

const { t } = useI18n()

const loading = ref(false)
const rules = ref<OntologyRule[]>([])
const actions = ref<ActionType[]>([])

const ruleDialog = ref(false)
const ruleSaving = ref(false)
const ruleForm = reactive({
  name: '',
  priority: 100,
  verdict: 'allow',
  condition_json: '{}',
  message: '',
  enabled: true,
})

const actionDialog = ref(false)
const actionSaving = ref(false)
const actionForm = reactive({
  name: '',
  risk: 'low',
  systems: '',
  schema_json: '{}',
  enabled: true,
})

async function load(): Promise<void> {
  loading.value = true
  try {
    ;[rules.value, actions.value] = await Promise.all([listOntologyRules(), listActionTypes()])
  } finally {
    loading.value = false
  }
}

function openRule(): void {
  ruleForm.name = ''
  ruleForm.priority = 100
  ruleForm.verdict = 'allow'
  ruleForm.condition_json = '{}'
  ruleForm.message = ''
  ruleForm.enabled = true
  ruleDialog.value = true
}

async function submitRule(): Promise<void> {
  let condition: Record<string, unknown> = {}
  try {
    condition = JSON.parse(ruleForm.condition_json || '{}') as Record<string, unknown>
  } catch {
    ElMessage.error(t('governance.invalidJson'))
    return
  }
  if (!ruleForm.name.trim()) {
    ElMessage.warning(t('governance.nameRequired'))
    return
  }
  ruleSaving.value = true
  try {
    await createOntologyRule({
      name: ruleForm.name.trim(),
      priority: ruleForm.priority,
      verdict: ruleForm.verdict,
      condition,
      message: ruleForm.message.trim() || null,
      enabled: ruleForm.enabled,
    })
    ruleDialog.value = false
    ElMessage.success(t('governance.saveOk'))
    await load()
  } finally {
    ruleSaving.value = false
  }
}

async function toggleRule(row: OntologyRule): Promise<void> {
  await patchOntologyRule(row.id, { enabled: !row.enabled })
  await load()
}

function openAction(): void {
  actionForm.name = ''
  actionForm.risk = 'low'
  actionForm.systems = ''
  actionForm.schema_json = '{}'
  actionForm.enabled = true
  actionDialog.value = true
}

async function submitAction(): Promise<void> {
  let schema: Record<string, unknown> = {}
  try {
    schema = JSON.parse(actionForm.schema_json || '{}') as Record<string, unknown>
  } catch {
    ElMessage.error(t('governance.invalidJson'))
    return
  }
  if (!actionForm.name.trim()) {
    ElMessage.warning(t('governance.nameRequired'))
    return
  }
  actionSaving.value = true
  try {
    await createActionType({
      name: actionForm.name.trim(),
      risk: actionForm.risk,
      systems: actionForm.systems
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      input_schema: schema,
      enabled: actionForm.enabled,
    })
    actionDialog.value = false
    ElMessage.success(t('governance.saveOk'))
    await load()
  } finally {
    actionSaving.value = false
  }
}

async function toggleAction(row: ActionType): Promise<void> {
  await patchActionType(row.id, { enabled: !row.enabled })
  await load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" class="gov-page">
    <template #header>
      <div>
        <div class="title">{{ t('governance.title') }}</div>
        <div class="hint">{{ t('governance.hint') }}</div>
      </div>
    </template>

    <section class="block">
      <div class="block-head">
        <h3>{{ t('governance.rules') }}</h3>
        <el-button size="small" type="primary" @click="openRule">{{ t('governance.addRule') }}</el-button>
      </div>
      <el-table v-loading="loading" :data="rules" size="small">
        <el-table-column prop="priority" :label="t('governance.priority')" width="90" />
        <el-table-column prop="name" :label="t('governance.name')" min-width="160" />
        <el-table-column prop="verdict" :label="t('governance.verdict')" width="120" />
        <el-table-column prop="enabled" :label="t('common.status')" width="100">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleRule(row)" />
          </template>
        </el-table-column>
        <el-table-column prop="message" :label="t('governance.message')" min-width="160" />
        <template #empty>
          <EmptyState :description="t('governance.emptyRules')" />
        </template>
      </el-table>
    </section>

    <section class="block">
      <div class="block-head">
        <h3>{{ t('governance.actions') }}</h3>
        <el-button size="small" type="primary" @click="openAction">{{ t('governance.addAction') }}</el-button>
      </div>
      <el-table v-loading="loading" :data="actions" size="small">
        <el-table-column prop="name" :label="t('governance.name')" min-width="180" />
        <el-table-column prop="risk" :label="t('governance.risk')" width="100" />
        <el-table-column :label="t('governance.systems')" min-width="140">
          <template #default="{ row }">{{ (row.systems || []).join(', ') }}</template>
        </el-table-column>
        <el-table-column prop="enabled" :label="t('common.status')" width="100">
          <template #default="{ row }">
            <el-switch :model-value="row.enabled" @change="toggleAction(row)" />
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState :description="t('governance.emptyActions')" />
        </template>
      </el-table>
    </section>
  </el-card>

  <el-dialog v-model="ruleDialog" :title="t('governance.addRule')" width="520px" destroy-on-close>
    <el-form label-width="110px">
      <el-form-item :label="t('governance.name')">
        <el-input v-model="ruleForm.name" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('governance.priority')">
        <el-input-number v-model="ruleForm.priority" :min="1" :max="9999" />
      </el-form-item>
      <el-form-item :label="t('governance.verdict')">
        <el-select v-model="ruleForm.verdict" style="width: 100%">
          <el-option label="allow" value="allow" />
          <el-option label="deny" value="deny" />
          <el-option label="require_confirm" value="require_confirm" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('governance.condition')">
        <el-input v-model="ruleForm.condition_json" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item :label="t('governance.message')">
        <el-input v-model="ruleForm.message" maxlength="512" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="ruleDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="ruleSaving" @click="submitRule">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="actionDialog" :title="t('governance.addAction')" width="520px" destroy-on-close>
    <el-form label-width="110px">
      <el-form-item :label="t('governance.name')">
        <el-input v-model="actionForm.name" maxlength="128" placeholder="device.set_status" />
      </el-form-item>
      <el-form-item :label="t('governance.risk')">
        <el-select v-model="actionForm.risk" style="width: 100%">
          <el-option label="low" value="low" />
          <el-option label="medium" value="medium" />
          <el-option label="high" value="high" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('governance.systems')">
        <el-input v-model="actionForm.systems" placeholder="mes, erp" />
      </el-form-item>
      <el-form-item :label="t('governance.schema')">
        <el-input v-model="actionForm.schema_json" type="textarea" :rows="4" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="actionDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="actionSaving" @click="submitAction">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.title {
  font-weight: 600;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 4px;
}
.block {
  margin-bottom: 28px;
}
.block-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.block-head h3 {
  margin: 0;
  font-size: 15px;
}
</style>
