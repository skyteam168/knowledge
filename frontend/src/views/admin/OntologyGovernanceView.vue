<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  approveAction,
  createActionType,
  createOntologyRule,
  dryRunAction,
  invokeAction,
  listActionExecutions,
  listActionTypes,
  listOntologyRules,
  patchActionType,
  patchOntologyRule,
} from '@/api/ontology'
import type {
  ActionExecutionListItem,
  ActionExecutionOut,
  ActionType,
  OntologyRule,
} from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'

const { t } = useI18n()

const loading = ref(false)
const rules = ref<OntologyRule[]>([])
const actions = ref<ActionType[]>([])
const executions = ref<ActionExecutionListItem[]>([])

const ruleDialog = ref(false)
const ruleSaving = ref(false)
const ruleForm = reactive({
  name: '',
  priority: 100,
  verdict: 'allow',
  condition_json: '{"action":"material.transfer","cross_plant":true}',
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

const runDialog = ref(false)
const runSaving = ref(false)
const runMode = ref<'dry_run' | 'approve' | 'invoke'>('dry_run')
const runForm = reactive({
  action_type: '',
  payload_json: '{}',
  idempotency_key: '',
  approval_id: '',
  acknowledge_risk: true,
})
const lastResult = ref<ActionExecutionOut | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try {
    ;[rules.value, actions.value, executions.value] = await Promise.all([
      listOntologyRules(),
      listActionTypes(),
      listActionExecutions(50),
    ])
  } finally {
    loading.value = false
  }
}

function openRule(): void {
  ruleForm.name = ''
  ruleForm.priority = 100
  ruleForm.verdict = 'allow'
  ruleForm.condition_json = '{"action":"material.transfer","cross_plant":true}'
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

function payloadTemplate(row: ActionType): string {
  if (row.name === 'material.transfer') {
    return '{\n  "source_inventory_id": "",\n  "target_inventory_id": "",\n  "qty": 100,\n  "production_order_id": "",\n  "material_external_id": "MAT-3001"\n}'
  }
  if (row.name === 'production.query_risk') {
    return '{\n  "risk_status": "at_risk"\n}'
  }
  if (row.name === 'device.record_note') {
    return '{\n  "canonical_id": "",\n  "note": ""\n}'
  }
  if (row.name === 'device.set_status') {
    return '{\n  "canonical_id": "",\n  "to_status": "RUNNING"\n}'
  }
  const required = Array.isArray((row.input_schema as { required?: unknown })?.required)
    ? ((row.input_schema as { required: string[] }).required ?? [])
    : []
  if (required.length) {
    const obj: Record<string, string> = {}
    for (const key of required) obj[key] = ''
    return `${JSON.stringify(obj, null, 2)}\n`
  }
  return '{}'
}

function openRun(row: ActionType, mode: 'dry_run' | 'approve' | 'invoke'): void {
  runMode.value = mode
  runForm.action_type = row.name
  runForm.payload_json = payloadTemplate(row)
  runForm.idempotency_key = `${row.name}-${Date.now()}`
  runForm.approval_id = ''
  runForm.acknowledge_risk = true
  lastResult.value = null
  runDialog.value = true
}

async function submitRun(): Promise<void> {
  let payload: Record<string, unknown> = {}
  try {
    payload = JSON.parse(runForm.payload_json || '{}') as Record<string, unknown>
  } catch {
    ElMessage.error(t('governance.invalidJson'))
    return
  }
  runSaving.value = true
  try {
    if (runMode.value === 'approve') {
      const approval = await approveAction({
        action_type: runForm.action_type,
        payload,
        acknowledge_risk: runForm.acknowledge_risk,
      })
      runForm.approval_id = approval.id
      ElMessage.success(`${t('governance.approve')}: ${approval.id}`)
      return
    }
    const body: {
      action_type: string
      payload: Record<string, unknown>
      idempotency_key: string
      approval_id?: string
      dry_run: boolean
    } = {
      action_type: runForm.action_type,
      payload,
      idempotency_key: runForm.idempotency_key.trim() || `${runForm.action_type}-${Date.now()}`,
      dry_run: runMode.value === 'dry_run',
    }
    const approvalId = runForm.approval_id.trim()
    if (approvalId) body.approval_id = approvalId
    const result =
      runMode.value === 'dry_run' ? await dryRunAction(body) : await invokeAction(body)
    lastResult.value = result
    if (result.status === 'awaiting_approval') {
      ElMessage.warning(t('governance.needApproval'))
    } else {
      ElMessage.success(t('governance.runOk'))
    }
    await load()
  } finally {
    runSaving.value = false
  }
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
            <el-switch
              :model-value="(row as OntologyRule).enabled"
              @change="toggleRule(row as OntologyRule)"
            />
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
          <template #default="{ row }">{{ ((row as ActionType).systems || []).join(', ') }}</template>
        </el-table-column>
        <el-table-column prop="enabled" :label="t('common.status')" width="100">
          <template #default="{ row }">
            <el-switch
              :model-value="(row as ActionType).enabled"
              @change="toggleAction(row as ActionType)"
            />
          </template>
        </el-table-column>
        <el-table-column :label="t('governance.runAction')" width="280" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openRun(row as ActionType, 'dry_run')">
              {{ t('governance.dryRun') }}
            </el-button>
            <el-button link type="warning" size="small" @click="openRun(row as ActionType, 'approve')">
              {{ t('governance.approve') }}
            </el-button>
            <el-button link type="danger" size="small" @click="openRun(row as ActionType, 'invoke')">
              {{ t('governance.invoke') }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState :description="t('governance.emptyActions')" />
        </template>
      </el-table>
    </section>

    <section class="block">
      <div class="block-head">
        <h3>{{ t('governance.executions') }}</h3>
        <el-button size="small" @click="load">{{ t('common.refresh') || 'Refresh' }}</el-button>
      </div>
      <el-table v-loading="loading" :data="executions" size="small">
        <el-table-column prop="created_at" :label="t('governance.status')" width="180">
          <template #default="{ row }">
            {{ new Date((row as ActionExecutionListItem).created_at).toLocaleString() }}
          </template>
        </el-table-column>
        <el-table-column prop="action_type" :label="t('governance.name')" min-width="160" />
        <el-table-column prop="status" :label="t('governance.status')" width="140" />
        <el-table-column prop="idempotency_key" :label="t('governance.idempotencyKey')" min-width="160" />
        <el-table-column prop="error" :label="t('governance.message')" min-width="160" />
        <template #empty>
          <EmptyState :description="t('governance.emptyExecutions')" />
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

  <el-dialog v-model="runDialog" :title="t('governance.runAction')" width="560px" destroy-on-close>
    <el-form label-width="120px">
      <el-form-item :label="t('governance.name')">
        <el-input v-model="runForm.action_type" disabled />
      </el-form-item>
      <el-form-item :label="t('governance.payload')">
        <el-input v-model="runForm.payload_json" type="textarea" :rows="8" />
      </el-form-item>
      <el-form-item v-if="runMode !== 'approve'" :label="t('governance.idempotencyKey')">
        <el-input v-model="runForm.idempotency_key" />
      </el-form-item>
      <el-form-item v-if="runMode === 'invoke'" label="approval_id">
        <el-input v-model="runForm.approval_id" placeholder="from approve step" />
      </el-form-item>
      <el-form-item v-if="runMode === 'approve'" :label="t('governance.acknowledgeRisk')">
        <el-switch v-model="runForm.acknowledge_risk" />
      </el-form-item>
      <el-form-item v-if="lastResult" :label="t('governance.status')">
        <pre class="result">{{ JSON.stringify(lastResult, null, 2) }}</pre>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="runDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="runSaving" @click="submitRun">
        {{
          runMode === 'dry_run'
            ? t('governance.dryRun')
            : runMode === 'approve'
              ? t('governance.approve')
              : t('governance.invoke')
        }}
      </el-button>
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
.result {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  font-size: 12px;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
  width: 100%;
}
</style>
