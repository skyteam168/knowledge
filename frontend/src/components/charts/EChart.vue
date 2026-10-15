<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import { useTheme } from '@/composables/useTheme'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = withDefaults(defineProps<{ option: EChartsCoreOption; height?: string }>(), {
  height: '300px',
})

const el = ref<HTMLDivElement | null>(null)
const chart = shallowRef<echarts.ECharts | null>(null)
let observer: ResizeObserver | null = null
const { isDark } = useTheme()

function withBackground(option: EChartsCoreOption): EChartsCoreOption {
  return { backgroundColor: 'transparent', ...option }
}

function render(): void {
  if (!el.value) return
  chart.value?.dispose()
  chart.value = echarts.init(el.value, isDark.value ? 'dark' : undefined)
  chart.value.setOption(withBackground(props.option))
}

onMounted(() => {
  if (!el.value) return
  render()
  observer = new ResizeObserver(() => chart.value?.resize())
  observer.observe(el.value)
})

watch(isDark, render)

watch(
  () => props.option,
  (option) => chart.value?.setOption(withBackground(option), { notMerge: true }),
  { deep: true },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart.value?.dispose()
  chart.value = null
})
</script>

<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<style scoped>
.chart {
  width: 100%;
}
</style>
