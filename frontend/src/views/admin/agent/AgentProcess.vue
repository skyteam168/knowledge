<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  ArrowDown,
  ArrowRight,
  CircleCheck,
  CircleClose,
  Clock,
  Loading,
  Search,
  Warning,
} from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import type { AgentStageStatus } from '@/api/types'
import AnswerMermaid from '@/components/assistant/AnswerMermaid.vue'
import AnswerTable from '@/components/assistant/AnswerTable.vue'
import { issueText, localized, type AgentTurn, type ToolCall } from './run'
import { accessGraph, resultTables, type ResultTable } from './visual'

const props = defineProps<{ turn: AgentTurn; live: boolean }>()
const { t } = useI18n()

const open = ref(true)
const expanded = ref<Record<string, boolean>>({})

const ICONS: Record<AgentStageStatus, unknown> = {
  running: Loading,
  done: CircleCheck,
  failed: CircleClose,
  blocked: Warning,
  waiting: Clock,
  skipped: CircleCheck,
}

const DETAIL_STAGES = ['understand', 'resolve', 'risk', 'execute']

const items = computed(() =>
  props.turn.stages.map((s) => ({
    ...s,
    title: t(`adminAgent.stage.${s.stage}`),
    detail:
      DETAIL_STAGES.includes(s.stage) &&
      (s.status === 'done' || s.status === 'failed') &&
      Object.keys(s.detail).length
        ? t(`adminAgent.detail.${s.stage}`, localized(s.detail))
        : '',
    thoughts: s.stage === 'understand' ? props.turn.thoughts : [],
    tools: s.stage === 'query' ? props.turn.tools : [],
  })),
)

function json(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

type ResultView = 'table' | 'graph' | 'json'
const views = ref<Record<string, ResultView>>({})
const tables = computed(
  () => new Map(props.turn.tools.map((c) => [c.id, resultTables(c.result)] as const)),
)
const graphs = computed(
  () => new Map(props.turn.tools.map((c) => [c.id, accessGraph(c.tool, c.result)] as const)),
)

function tablesOf(call: ToolCall): ResultTable[] {
  return tables.value.get(call.id) ?? []
}

function graphOf(call: ToolCall): string | null {
  return graphs.value.get(call.id) ?? null
}

function viewOf(call: ToolCall): ResultView {
  return views.value[call.id] ?? (tablesOf(call).length ? 'table' : 'json')
}
</script>

<template>
  <div class="process" data-test="agent-process">
    <button type="button" class="process__toggle" @click="open = !open">
      <el-icon><component :is="open ? ArrowDown : ArrowRight" /></el-icon>
      <span>{{ t('adminAgent.process.title') }}</span>
      <el-icon v-if="live" class="is-loading"><Loading /></el-icon>
    </button>
    <ol v-show="open" class="process__list">
      <li
        v-for="item in items"
        :key="item.stage"
        class="process__item"
        :class="`process__item--${item.status}`"
        :data-test="`agent-stage-${item.stage}`"
      >
        <div class="process__row">
          <el-icon class="process__icon" :class="{ 'is-loading': item.status === 'running' }">
            <component :is="ICONS[item.status]" />
          </el-icon>
          <span class="process__title">{{ item.title }}</span>
          <span class="process__status">{{ t(`adminAgent.stageStatus.${item.status}`) }}</span>
          <span v-if="item.durationMs != null" class="process__time">
            {{ t('adminAgent.process.took', { ms: item.durationMs }) }}
          </span>
        </div>
        <div v-if="item.detail" class="process__detail">{{ item.detail }}</div>
        <div v-for="(th, i) in item.thoughts" :key="i" class="process__thought">💭 {{ th }}</div>

        <div
          v-for="call in item.tools"
          :key="call.id"
          class="process__tool"
          :class="`process__tool--${call.status}`"
        >
          <button
            type="button"
            class="process__tool-head"
            @click="expanded[call.id] = !expanded[call.id]"
          >
            <el-icon :class="{ 'is-loading': call.status === 'running' }">
              <component
                :is="
                  call.status === 'running'
                    ? Loading
                    : call.status === 'done'
                      ? Search
                      : CircleClose
                "
              />
            </el-icon>
            <span class="process__tool-name">{{ t(`adminAgent.toolNames.${call.tool}`) }}</span>
            <code class="process__tool-args">{{ JSON.stringify(call.args) }}</code>
            <span v-if="call.count != null" class="process__time">
              {{ t('adminAgent.process.count', { count: call.count }) }}
            </span>
            <span v-if="call.durationMs != null" class="process__time">
              {{ t('adminAgent.process.took', { ms: call.durationMs }) }}
            </span>
          </button>
          <div v-if="call.error" class="process__error">{{ issueText(call.error) }}</div>
          <div
            v-if="expanded[call.id] && call.result != null"
            class="process__result"
            :data-test="`agent-tool-result-${call.tool}`"
          >
            <el-radio-group v-model="views[call.id]" size="small" class="process__views">
              <el-radio-button v-if="tablesOf(call).length" value="table">
                {{ t('adminAgent.result.table') }}
              </el-radio-button>
              <el-radio-button v-if="graphOf(call)" value="graph">
                {{ t('adminAgent.result.graph') }}
              </el-radio-button>
              <el-radio-button value="json">JSON</el-radio-button>
            </el-radio-group>
            <template v-if="viewOf(call) === 'table'">
              <template v-for="(table, ti) in tablesOf(call)" :key="ti">
                <div v-if="table.title" class="process__table-title">{{ table.title }}</div>
                <AnswerTable :headers="table.headers" :rows="table.rows" />
              </template>
            </template>
            <AnswerMermaid v-else-if="viewOf(call) === 'graph'" :source="graphOf(call)!" />
            <pre v-else class="process__json">{{ json(call.result) }}</pre>
          </div>
        </div>
      </li>
      <li v-if="live && !items.length" class="process__item process__item--running">
        <div class="process__row">
          <el-icon class="process__icon is-loading"><Loading /></el-icon>
          <span class="process__title">{{ t('adminAgent.process.running') }}</span>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.process {
  margin-bottom: 8px;
  font-size: 13px;
}
.process__toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: none;
  background: none;
  color: var(--el-text-color-secondary);
  cursor: pointer;
}
.process__list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0 0 0 4px;
  border-left: 2px solid var(--el-border-color-lighter);
}
.process__item {
  position: relative;
  margin: 0 0 6px 10px;
}
.process__row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.process__icon {
  flex: none;
}
.process__item--done .process__icon {
  color: var(--el-color-success);
}
.process__item--failed .process__icon {
  color: var(--el-color-danger);
}
.process__item--blocked .process__icon,
.process__item--waiting .process__icon {
  color: var(--el-color-warning);
}
.process__item--running .process__icon {
  color: var(--el-color-primary);
}
.process__title {
  color: var(--el-text-color-primary);
}
.process__status,
.process__time {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.process__detail,
.process__thought {
  margin: 2px 0 0 22px;
  color: var(--el-text-color-secondary);
}
.process__tool {
  margin: 6px 0 0 22px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}
.process__tool--failed {
  border-color: var(--el-color-danger-light-5);
}
.process__tool-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 6px 8px;
  border: none;
  background: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.process__tool--done .process__tool-head .el-icon {
  color: var(--el-color-success);
}
.process__tool--failed .process__tool-head .el-icon {
  color: var(--el-color-danger);
}
.process__tool-name {
  font-weight: 600;
  flex: none;
}
.process__tool-args {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.process__error {
  padding: 0 8px 6px 30px;
  color: var(--el-color-danger);
}
.process__result {
  padding: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.process__views {
  margin-bottom: 4px;
}
.process__table-title {
  margin-top: 8px;
  font-weight: 600;
}
.process__result :deep(.answer-table),
.process__result :deep(.answer-mermaid) {
  margin: 6px 0;
}
.process__json {
  margin: 6px 0 0;
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
}
</style>
