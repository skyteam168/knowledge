<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import EChart from '@/components/charts/EChart.vue'

const props = defineProps<{
  option: Record<string, unknown>
}>()

const chartOption = computed(() => props.option as EChartsCoreOption)
</script>

<template>
  <div class="answer-chart" data-test="answer-chart">
    <EChart :option="chartOption" height="340px" />
  </div>
</template>

<style scoped>
.answer-chart {
  margin: 12px 0;
  padding: 8px 4px;
  border: 1px solid var(--ekb-code-border);
  border-radius: 10px;
  background: var(--ekb-bg-card, var(--el-bg-color));
}
</style>
