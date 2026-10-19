<script setup lang="ts">
import { Warning } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import type { AgentIssue } from '@/api/types'
import { issueText } from './run'

defineProps<{ items: AgentIssue[]; disabled?: boolean }>()
const emit = defineEmits<{ pick: [text: string] }>()
const { t } = useI18n()

const PICK_REASONS = ['user_ambiguous', 'dept_ambiguous', 'role_ambiguous']

function pick(item: AgentIssue, option: string): void {
  emit('pick', t('adminAgent.clarify.picked', { mention: item.params.mention ?? '', option }))
}
</script>

<template>
  <div class="clarify" data-test="agent-clarify">
    <div class="clarify__title">
      <el-icon><Warning /></el-icon>{{ t('adminAgent.clarify.title') }}
    </div>
    <ul class="clarify__list">
      <li v-for="(item, i) in items" :key="i">
        <div>{{ issueText(item) }}</div>
        <div v-if="item.options?.length" class="clarify__options">
          <span class="clarify__hint">
            {{
              PICK_REASONS.includes(item.reason)
                ? t('adminAgent.clarify.pickHint')
                : t('adminAgent.clarify.suggestions')
            }}
          </span>
          <el-button
            v-for="option in item.options"
            :key="option"
            size="small"
            :disabled="disabled"
            data-test="agent-clarify-option"
            @click="pick(item, option)"
          >
            {{ option }}
          </el-button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.clarify {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
}
.clarify__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-color-warning-dark-2);
}
.clarify__list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.7;
}
.clarify__options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin: 4px 0;
}
.clarify__options .el-button + .el-button {
  margin-left: 0;
}
.clarify__hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
