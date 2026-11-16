<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { getAgentRun, listAgentRuns } from '@/api/adminAgent'
import type { AgentRun, AgentRunDetail, AgentRunStatus } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ open: [run: AgentRunDetail] }>()
const { t } = useI18n()

const PAGE_SIZE = 20
const runs = ref<AgentRun[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const opening = ref<string | null>(null)

const TAG: Partial<Record<AgentRunStatus, 'success' | 'warning' | 'danger' | 'info'>> = {
  answered: 'success',
  done: 'success',
  clarify: 'warning',
  awaiting_approval: 'warning',
  failed: 'danger',
  error: 'danger',
}

async function load(reset: boolean): Promise<void> {
  loading.value = true
  try {
    const next = reset ? 1 : page.value + 1
    const data = await listAgentRuns(next, PAGE_SIZE)
    runs.value = reset ? data.items : [...runs.value, ...data.items]
    total.value = data.total
    page.value = next
  } finally {
    loading.value = false
  }
}

async function open(run: AgentRun): Promise<void> {
  opening.value = run.id
  try {
    emit('open', await getAgentRun(run.id))
    visible.value = false
  } catch {
    ElMessage.error(t('adminAgent.runs.loadFailed'))
  } finally {
    opening.value = null
  }
}

watch(visible, (shown) => {
  if (shown) void load(true)
})
</script>

<template>
  <el-drawer v-model="visible" :title="t('adminAgent.runs.title')" size="420px">
    <div v-loading="loading && !runs.length" class="runs" data-test="agent-runs">
      <EmptyState v-if="!loading && !runs.length" :description="t('adminAgent.runs.empty')" />
      <button
        v-for="run in runs"
        :key="run.id"
        type="button"
        class="runs__item"
        :disabled="opening !== null"
        data-test="agent-run"
        @click="open(run)"
      >
        <div class="runs__message">{{ run.message }}</div>
        <div class="runs__meta">
          <el-tag size="small" :type="TAG[run.status] ?? 'info'">
            {{ t(`adminAgent.runs.status.${run.status}`) }}
          </el-tag>
          <el-tag v-if="run.intent" size="small" effect="plain">
            {{ t(`adminAgent.intent.${run.intent}`) }}
          </el-tag>
          <el-tag v-if="run.understand_mode" size="small" effect="plain" type="info">
            {{ t(`adminAgent.mode.${run.understand_mode}`) }}
          </el-tag>
          <span v-if="run.step_count" class="runs__muted">
            {{ t('adminAgent.runs.steps', { count: run.step_count }) }}
          </span>
          <span class="runs__muted runs__time">{{ formatDateTime(run.created_at) }}</span>
        </div>
      </button>
      <el-button
        v-if="runs.length < total"
        class="runs__more"
        text
        :loading="loading"
        @click="load(false)"
      >
        {{ t('adminAgent.runs.more') }}
      </el-button>
    </div>
  </el-drawer>
</template>

<style scoped>
.runs {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 120px;
}
.runs__item {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-bg-color);
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.runs__item:hover {
  border-color: var(--el-color-primary);
}
.runs__message {
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  line-height: 1.5;
}
.runs__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.runs__muted {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.runs__time {
  margin-left: auto;
}
.runs__more {
  align-self: center;
}
</style>
