<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Clock, Delete, MagicStick, Promotion, VideoPause } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { cancelAgentRun, executeAgentRun, startAgentRun } from '@/api/adminAgent'
import { HttpError } from '@/api/http'
import type { AgentMessage, AgentRunDetail } from '@/api/types'
import AnswerContent from '@/components/assistant/AnswerContent.vue'
import AgentClarify from './AgentClarify.vue'
import AgentHistory from './AgentHistory.vue'
import AgentPlanCard from './AgentPlanCard.vue'
import AgentProcess from './AgentProcess.vue'
import { applyEvent, issueText, newTurn, stepText, type AgentTurn } from './run'
import { replayTurn } from './visual'

interface Message {
  role: 'user' | 'assistant'
  text: string
  turn?: AgentTurn
}

const { t } = useI18n()
const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const scroller = ref<HTMLElement>()
let controller: AbortController | null = null

const EXAMPLES = ['onboard', 'explain', 'kbAccess', 'group', 'audit', 'platform'] as const
const examples = computed(() => EXAMPLES.map((key) => t(`adminAgent.examples.${key}`)))

/** What the understanding stage sees of earlier turns: text + system notes on outcomes. */
function summary(turn: AgentTurn): string {
  const parts: string[] = []
  if (turn.answer) parts.push(turn.answer)
  if (turn.clarify.length) {
    parts.push(t('adminAgent.history.clarify', { items: turn.clarify.map(issueText).join('; ') }))
  }
  if (turn.plan) {
    const steps = turn.plan.steps.map((s) => stepText(s.tool, s.display)).join('; ')
    parts.push(
      t('adminAgent.history.plan', { steps, outcome: turn.outcome ?? 'awaiting_approval' }),
    )
  }
  if (turn.error) parts.push(issueText(turn.error))
  return parts.join('\n')
}

function history(): AgentMessage[] {
  return messages.value.map((m) => ({
    role: m.role,
    content: m.turn ? summary(m.turn) : m.text,
  }))
}

async function scrollToEnd(): Promise<void> {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}

function failure(turn: AgentTurn, err: unknown): void {
  if (err instanceof DOMException && err.name === 'AbortError') return
  const message = err instanceof HttpError ? err.message : String(err)
  turn.error = { reason: 'error', params: { message } }
  turn.outcome = 'error'
}

async function send(text?: string): Promise<void> {
  const message = (text ?? input.value).trim()
  if (!message || loading.value) return
  const past = history()
  messages.value.push({ role: 'user', text: message })
  messages.value.push({ role: 'assistant', text: '', turn: newTurn() })
  // The reactive proxy, not the plain object pushed above, so updates re-render.
  const turn = messages.value[messages.value.length - 1].turn!
  input.value = ''
  loading.value = true
  controller = new AbortController()
  void scrollToEnd()
  try {
    await startAgentRun(
      message,
      past,
      (type, data) => {
        applyEvent(turn, type, data)
        void scrollToEnd()
      },
      controller.signal,
    )
  } catch (err) {
    failure(turn, err)
  } finally {
    loading.value = false
    controller = null
  }
}

function stop(): void {
  controller?.abort()
}

function onKeydown(evt: Event | KeyboardEvent): void {
  const event = evt as KeyboardEvent
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

async function confirm(entry: Message, acknowledgeRisk: boolean): Promise<void> {
  const turn = entry.turn
  if (!turn?.plan) return
  turn.executing = true
  try {
    await executeAgentRun(turn.plan.run_id, acknowledgeRisk, (type, data) => {
      if (type === 'run' || type === 'done') return
      applyEvent(turn, type, data)
      void scrollToEnd()
    })
  } catch (err) {
    failure(turn, err)
  } finally {
    turn.executing = false
  }
}

async function cancel(entry: Message): Promise<void> {
  const turn = entry.turn
  if (!turn?.plan) return
  turn.outcome = 'cancelled'
  await cancelAgentRun(turn.plan.run_id).catch(() => undefined)
}

function clear(): void {
  for (const m of messages.value) {
    if (m.turn?.plan && m.turn.outcome === 'awaiting_approval') void cancel(m)
  }
  messages.value = []
}

const historyOpen = ref(false)

/** Shows a stored run as the conversation; a still-valid plan can be confirmed again. */
function replay(run: AgentRunDetail): void {
  messages.value = [
    { role: 'user', text: run.message },
    { role: 'assistant', text: '', turn: replayTurn(run) },
  ]
  void scrollToEnd()
}

function errorText(turn: AgentTurn): string {
  if (!turn.error) return ''
  return turn.error.reason === 'error'
    ? t('adminAgent.outcome.error', { message: turn.error.params.message })
    : issueText(turn.error)
}
</script>

<template>
  <div class="agent">
    <div ref="scroller" class="agent__messages" data-test="agent-messages">
      <div v-if="!messages.length" class="agent__empty">
        <el-icon :size="36" class="agent__logo"><MagicStick /></el-icon>
        <h2>{{ t('adminAgent.title') }}</h2>
        <p>{{ t('adminAgent.intro') }}</p>
        <div class="agent__examples">
          <button
            v-for="(ex, i) in examples"
            :key="i"
            type="button"
            class="agent__example"
            @click="send(ex)"
          >
            {{ ex }}
          </button>
        </div>
      </div>

      <div
        v-for="(m, i) in messages"
        :key="i"
        class="agent__turn"
        :class="`agent__turn--${m.role}`"
      >
        <div class="agent__who">
          {{ m.role === 'user' ? t('adminAgent.you') : t('adminAgent.assistant') }}
        </div>
        <div class="agent__bubble">
          <div v-if="m.role === 'user'" class="agent__user-text">{{ m.text }}</div>
          <template v-else-if="m.turn">
            <AgentProcess :turn="m.turn" :live="loading && i === messages.length - 1" />
            <div v-if="m.turn.answer" class="agent__answer" data-test="agent-answer">
              <AnswerContent :content="m.turn.answer" :citations="[]" />
            </div>
            <div v-if="m.turn.outcome === 'out_of_scope' && !m.turn.answer" class="agent__muted">
              {{ t('adminAgent.outcome.out_of_scope') }}
            </div>
            <AgentClarify
              v-if="m.turn.clarify.length"
              :items="m.turn.clarify"
              :disabled="loading"
              @pick="send"
            />
            <AgentPlanCard
              v-if="m.turn.plan"
              :turn="m.turn"
              @confirm="(ack: boolean) => confirm(m, ack)"
              @cancel="cancel(m)"
            />
            <div v-if="m.turn.error" class="agent__error">{{ errorText(m.turn) }}</div>
          </template>
        </div>
      </div>
    </div>

    <div class="agent__composer">
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        resize="none"
        maxlength="2000"
        :placeholder="t('adminAgent.placeholder')"
        data-test="agent-input"
        @keydown="onKeydown"
      />
      <div class="agent__composer-actions">
        <el-button
          :icon="Clock"
          :disabled="loading"
          class="agent__history"
          data-test="agent-history"
          @click="historyOpen = true"
        >
          {{ t('adminAgent.runs.open') }}
        </el-button>
        <el-button :icon="Delete" :disabled="!messages.length || loading" @click="clear">
          {{ t('adminAgent.clear') }}
        </el-button>
        <el-button v-if="loading" :icon="VideoPause" @click="stop">
          {{ t('adminAgent.stop') }}
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="Promotion"
          :disabled="!input.trim()"
          data-test="agent-send"
          @click="send()"
        >
          {{ t('adminAgent.send') }}
        </el-button>
      </div>
    </div>
    <AgentHistory v-model="historyOpen" @open="replay" />
  </div>
</template>

<style scoped>
.agent {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  max-width: 980px;
  margin: 0 auto;
}
.agent__messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 4px 16px;
}
.agent__empty {
  text-align: center;
  padding: 40px 16px 8px;
  color: var(--el-text-color-regular);
}
.agent__empty h2 {
  margin: 10px 0 6px;
}
.agent__empty p {
  max-width: 680px;
  margin: 0 auto 18px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.agent__logo {
  color: var(--el-color-primary);
}
.agent__examples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 10px;
  text-align: left;
}
.agent__example {
  padding: 12px 14px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color);
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.5;
  cursor: pointer;
  text-align: left;
}
.agent__example:hover {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
}
.agent__turn {
  display: flex;
  flex-direction: column;
  margin: 14px 0;
}
.agent__turn--user {
  align-items: flex-end;
}
.agent__who {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
}
.agent__bubble {
  max-width: 92%;
  min-width: 320px;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}
.agent__turn--user .agent__bubble {
  min-width: 0;
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}
.agent__user-text {
  white-space: pre-wrap;
  line-height: 1.6;
}
.agent__muted {
  color: var(--el-text-color-secondary);
}
.agent__error {
  margin-top: 8px;
  color: var(--el-color-danger);
}
.agent__composer {
  flex: none;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.agent__composer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.agent__history {
  margin-right: auto;
}
.agent__answer {
  margin-top: 6px;
}
.agent__answer :deep(.answer-content) {
  font-size: 14px;
}
</style>
