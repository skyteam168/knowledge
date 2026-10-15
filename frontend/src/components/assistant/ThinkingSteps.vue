<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, CircleCheckFilled, CircleCloseFilled, Loading } from '@element-plus/icons-vue'
import type { ChatStep, ChatStepName } from '@/api/types'

const props = defineProps<{ steps: ChatStep[]; streaming?: boolean }>()

const LABELS: Record<ChatStepName, string> = {
  rewrite: '理解问题',
  retrieve: '检索知识库',
  evidence: '筛选与校验证据',
  generate: '生成回答',
}
const INTENTS: Record<string, string> = {
  knowledge_qa: '知识问答',
  chitchat: '闲聊',
  out_of_scope: '超出知识范围',
}
const VERDICTS: Record<string, string> = {
  confident: '依据充分',
  uncertain: '依据有限',
  refuse: '依据不足，不作答',
}

const open = ref(!!props.streaming)
watch(
  () => props.streaming,
  (now, before) => {
    if (now) open.value = true
    else if (before) open.value = false
  },
)

const running = computed(() => props.steps.find((s) => s.status === 'running'))
const failed = computed(() => props.steps.some((s) => s.status === 'failed'))
const totalMs = computed(() => props.steps.reduce((sum, s) => sum + (s.ms ?? 0), 0))

const title = computed(() => {
  if (running.value) return `${LABELS[running.value.step] ?? running.value.step}…`
  if (failed.value) return '处理中断'
  return `已完成 ${props.steps.length} 个步骤 · 用时 ${seconds(totalMs.value)}`
})

function seconds(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function summary(step: ChatStep): string[] {
  const d = step.detail ?? {}
  if (step.status === 'running') return []
  switch (step.step) {
    case 'rewrite': {
      const lines = [`意图：${INTENTS[str(d.intent)] ?? (str(d.intent) || '—')}`]
      if (str(d.query)) lines.push(`检索语句：${str(d.query)}`)
      const subs = Array.isArray(d.sub_queries) ? (d.sub_queries as unknown[]).map(str) : []
      if (subs.length) lines.push(`拆分子问题：${subs.join('；')}`)
      return lines
    }
    case 'retrieve': {
      const hits = num(d.hits) ?? 0
      const docs = num(d.documents) ?? 0
      const lines = [`${num(d.queries) ?? 1} 路查询，召回 ${hits} 个片段，来自 ${docs} 篇文档`]
      const top = num(d.top_score)
      if (top !== null) lines.push(`最高相关度 ${top.toFixed(3)}`)
      return lines
    }
    case 'evidence': {
      const lines = [`保留 ${num(d.kept) ?? 0} 条证据`]
      const dropped = num(d.dropped) ?? 0
      if (dropped) lines[0] += `，按权限剔除 ${dropped} 条`
      if (str(d.verdict)) lines.push(`判定：${VERDICTS[str(d.verdict)] ?? str(d.verdict)}`)
      return lines
    }
    case 'generate': {
      const lines: string[] = []
      if (str(d.model)) lines.push(`模型：${str(d.model)}`)
      const first = num(d.first_token_ms)
      if (first !== null) lines.push(`首字耗时 ${seconds(first)}`)
      return lines
    }
    default:
      return []
  }
}
</script>

<template>
  <div v-if="steps.length" class="thinking" :class="{ open }" data-test="thinking">
    <button type="button" class="thinking__head" @click="open = !open">
      <el-icon v-if="running" class="is-loading thinking__icon"><Loading /></el-icon>
      <el-icon v-else-if="failed" class="thinking__icon failed"><CircleCloseFilled /></el-icon>
      <el-icon v-else class="thinking__icon done"><CircleCheckFilled /></el-icon>
      <span class="thinking__title">{{ title }}</span>
      <el-icon class="thinking__arrow"><ArrowDown /></el-icon>
    </button>
    <ol v-show="open" class="thinking__list">
      <li v-for="s in steps" :key="s.step" class="step" :class="s.status">
        <span class="step__dot" />
        <div class="step__body">
          <div class="step__line">
            <span class="step__name">{{ LABELS[s.step] ?? s.step }}</span>
            <span v-if="s.status === 'running'" class="step__status">进行中</span>
            <span v-else-if="s.status === 'failed'" class="step__status failed">失败</span>
            <span v-else-if="s.ms !== undefined" class="step__ms">{{ seconds(s.ms) }}</span>
          </div>
          <div v-for="line in summary(s)" :key="line" class="step__detail">{{ line }}</div>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.thinking {
  margin-bottom: 12px;
  font-size: 13px;
}
.thinking__head {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  color: var(--el-text-color-regular);
  background: var(--ekb-bg-fill);
  border: 1px solid var(--ekb-border-soft);
  border-radius: 16px;
  cursor: pointer;
  transition: background 0.2s;
}
.thinking__head:hover {
  background: var(--ekb-bg-fill-2);
}
.thinking__icon {
  color: var(--el-color-primary);
}
.thinking__icon.done {
  color: var(--el-color-success);
}
.thinking__icon.failed {
  color: var(--el-color-danger);
}
.thinking__arrow {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: transform 0.2s;
}
.thinking.open .thinking__arrow {
  transform: rotate(180deg);
}
.thinking__list {
  margin: 8px 0 0 6px;
  padding: 2px 0 2px 14px;
  list-style: none;
  border-left: 2px solid var(--ekb-border-soft);
}
.step {
  position: relative;
  display: flex;
  padding: 4px 0;
}
.step__dot {
  position: absolute;
  top: 11px;
  left: -19px;
  width: 8px;
  height: 8px;
  background: var(--el-color-success);
  border: 2px solid var(--ekb-bg-panel);
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--ekb-border-soft);
}
.step.running .step__dot {
  background: var(--el-color-primary);
  animation: pulse 1.2s ease-in-out infinite;
}
.step.failed .step__dot {
  background: var(--el-color-danger);
}
.step__body {
  flex: 1;
  min-width: 0;
}
.step__line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.step__name {
  font-weight: 500;
  color: var(--el-text-color-primary);
}
.step__ms,
.step__status {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.step__status {
  color: var(--el-color-primary);
}
.step__status.failed {
  color: var(--el-color-danger);
}
.step__detail {
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  word-break: break-all;
}
@keyframes pulse {
  50% {
    box-shadow: 0 0 0 4px var(--el-color-primary-light-7);
  }
}
</style>
