<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleCheck,
  CircleClose,
  CopyDocument,
  Loading,
  RefreshLeft,
  Remove,
  Timer,
} from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import type { AgentStepStatus } from '@/api/types'
import AnswerMermaid from '@/components/assistant/AnswerMermaid.vue'
import { issueText, localized, stepText, type AgentTurn } from './run'
import { planFlowchart } from './visual'

const props = defineProps<{ turn: AgentTurn }>()
const emit = defineEmits<{ confirm: [acknowledgeRisk: boolean]; cancel: [] }>()
const { t } = useI18n()
const ack = ref(false)
const view = ref<'list' | 'flow'>('list')
const flowchart = computed(() => planFlowchart(props.turn))

const STATUS_ICON: Record<AgentStepStatus, unknown> = {
  pending: Timer,
  running: Loading,
  done: CircleCheck,
  failed: CircleClose,
  not_run: Remove,
  rolled_back: RefreshLeft,
}

const plan = computed(() => props.turn.plan!)
const total = computed(() => plan.value.steps.length)
const done = computed(() => props.turn.steps.filter((s) => s.status === 'done').length)
const percent = computed(() => (total.value ? Math.round((done.value / total.value) * 100) : 0))

const pending = computed(
  () => props.turn.outcome === 'awaiting_approval' || props.turn.outcome === 'blocked',
)
const OUTCOMES = ['done', 'failed', 'expired', 'blocked', 'cancelled']
const outcomeText = computed(() =>
  props.turn.outcome && OUTCOMES.includes(props.turn.outcome)
    ? t(`adminAgent.plan.${props.turn.outcome}`)
    : '',
)

const steps = computed(() =>
  plan.value.steps.map((step, i) => ({
    text: stepText(step.tool, step.display),
    warnings: step.warnings.map((w) => t(`adminAgent.warnings.${w.code}`, localized(w))),
    risks: step.risk_reasons.map((r) => t(`adminAgent.risk.reason.${r.code}`, r)),
    risk: step.risk,
    state: props.turn.steps[i] ?? { status: 'pending' as const },
  })),
)

const passwords = computed(() =>
  props.turn.steps
    .filter((s) => s.status === 'done' && s.output?.temporary_password)
    .map((s) => s.output!),
)

async function copy(text: string): Promise<void> {
  await navigator.clipboard.writeText(text)
  ElMessage.success(t('common.copied'))
}
</script>

<template>
  <div class="plan" data-test="agent-plan">
    <div class="plan__head">
      <span class="plan__title">{{ t('adminAgent.plan.title') }}</span>
      <el-tag
        :type="plan.risk === 'high' ? 'danger' : plan.risk === 'medium' ? 'warning' : 'success'"
        size="small"
      >
        {{ t('adminAgent.plan.risk', { level: t(`adminAgent.risk.${plan.risk}`) }) }}
      </el-tag>
      <span class="plan__progress-text">{{ t('adminAgent.plan.progress', { done, total }) }}</span>
      <el-radio-group v-model="view" size="small" data-test="agent-plan-view">
        <el-radio-button value="list">{{ t('adminAgent.plan.list') }}</el-radio-button>
        <el-radio-button value="flow">{{ t('adminAgent.plan.flow') }}</el-radio-button>
      </el-radio-group>
    </div>
    <el-progress
      :percentage="percent"
      :status="turn.outcome === 'failed' ? 'exception' : percent === 100 ? 'success' : undefined"
      :show-text="false"
      :stroke-width="6"
      class="plan__bar"
    />
    <AnswerMermaid v-if="view === 'flow'" :source="flowchart" />
    <ol v-show="view === 'list'" class="plan__steps">
      <li
        v-for="(step, i) in steps"
        :key="i"
        class="plan__step"
        :class="`plan__step--${step.state.status}`"
        :data-test="`agent-step-${i}`"
      >
        <div class="plan__step-main">
          <el-icon class="plan__status" :class="{ 'is-loading': step.state.status === 'running' }">
            <component :is="STATUS_ICON[step.state.status]" />
          </el-icon>
          <span class="plan__text">{{ step.text }}</span>
          <span class="plan__badge">{{ t(`adminAgent.status.${step.state.status}`) }}</span>
          <span v-if="step.state.durationMs != null" class="plan__muted">
            {{ t('adminAgent.process.took', { ms: step.state.durationMs }) }}
          </span>
        </div>
        <div
          v-for="(r, j) in step.risks"
          :key="`r${j}`"
          class="plan__risk"
          :class="`plan__risk--${step.risk}`"
        >
          ⚑ {{ r }}
        </div>
        <div v-for="(w, j) in step.warnings" :key="`w${j}`" class="plan__warning">⚠ {{ w }}</div>
        <div
          v-if="step.state.check"
          class="plan__check"
          :class="{ 'plan__check--bad': !step.state.check.ok }"
        >
          ✓ {{ t(`adminAgent.check.${step.state.check.code}`, step.state.check.params) }}
        </div>
        <div v-if="step.state.error" class="plan__error">{{ issueText(step.state.error) }}</div>
      </li>
    </ol>

    <div v-for="(pw, i) in passwords" :key="i" class="plan__password">
      <div class="plan__password-title">
        {{ t('adminAgent.password.title') }} · {{ pw.username }}
      </div>
      <div class="plan__password-row">
        <code>{{ pw.temporary_password }}</code>
        <el-button size="small" :icon="CopyDocument" @click="copy(pw.temporary_password)">
          {{ t('common.copy') }}
        </el-button>
      </div>
      <div class="plan__muted">{{ t('adminAgent.password.hint', { user: pw.user }) }}</div>
    </div>

    <div v-if="pending || turn.executing" class="plan__actions">
      <span class="plan__muted">{{ t('adminAgent.plan.confirmHint') }}</span>
      <el-checkbox v-if="plan.needs_ack" v-model="ack" data-test="agent-plan-ack">
        {{ t('adminAgent.plan.ack') }}
      </el-checkbox>
      <div class="plan__buttons">
        <el-button :disabled="turn.executing" @click="emit('cancel')">
          {{ t('adminAgent.plan.cancel') }}
        </el-button>
        <el-button
          type="primary"
          :loading="turn.executing"
          :disabled="plan.needs_ack && !ack"
          data-test="agent-plan-confirm"
          @click="emit('confirm', ack)"
        >
          {{ turn.executing ? t('adminAgent.plan.executing') : t('adminAgent.plan.confirm') }}
        </el-button>
      </div>
    </div>
    <div
      v-if="outcomeText && !turn.executing"
      class="plan__outcome"
      :class="`plan__outcome--${turn.outcome}`"
    >
      {{ outcomeText }}
    </div>
  </div>
</template>

<style scoped>
.plan {
  margin-top: 10px;
  padding: 12px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.plan__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.plan__title {
  font-weight: 600;
}
.plan__progress-text {
  margin-left: auto;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.plan :deep(.answer-mermaid) {
  margin: 8px 0;
}
.plan__bar {
  margin: 8px 0 4px;
}
.plan__steps {
  margin: 0;
  padding-left: 20px;
}
.plan__step {
  margin: 8px 0;
  line-height: 1.6;
}
.plan__step-main {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.plan__status {
  margin-top: 4px;
  flex: none;
  color: var(--el-text-color-secondary);
}
.plan__step--done .plan__status {
  color: var(--el-color-success);
}
.plan__step--failed .plan__status {
  color: var(--el-color-danger);
}
.plan__step--running .plan__status {
  color: var(--el-color-primary);
}
.plan__text {
  flex: 1;
}
.plan__badge {
  flex: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.plan__muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.plan__warning,
.plan__risk--medium {
  color: var(--el-color-warning);
  font-size: 12px;
  margin-left: 22px;
}
.plan__risk--high {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-left: 22px;
}
.plan__check {
  color: var(--el-color-success);
  font-size: 12px;
  margin-left: 22px;
}
.plan__check--bad,
.plan__error {
  color: var(--el-color-danger);
  font-size: 12px;
  margin-left: 22px;
}
.plan__password {
  margin-top: 10px;
  padding: 10px;
  border-radius: 6px;
  background: var(--el-color-warning-light-9);
}
.plan__password-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.plan__password-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}
.plan__password-row code {
  font-size: 15px;
  letter-spacing: 1px;
}
.plan__actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
}
.plan__buttons {
  display: flex;
  justify-content: flex-end;
}
.plan__outcome {
  margin-top: 10px;
  font-size: 13px;
}
.plan__outcome--done {
  color: var(--el-color-success);
}
.plan__outcome--failed,
.plan__outcome--blocked {
  color: var(--el-color-danger);
}
</style>
