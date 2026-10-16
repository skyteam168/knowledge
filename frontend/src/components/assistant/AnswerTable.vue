<script setup lang="ts">
import { computed, ref } from 'vue'
import type { EChartsCoreOption } from 'echarts/core'
import EChart from '@/components/charts/EChart.vue'
import { tableToBarOption } from '@/utils/answerBlocks'

const props = defineProps<{
  headers: string[]
  rows: string[][]
}>()

const mode = ref<'table' | 'chart'>('table')
const chartOption = computed(() => tableToBarOption(props.headers, props.rows))
const wide = computed(() => props.headers.length >= 8)
const canChart = computed(() => chartOption.value !== null)

function display(cell: string | undefined): string {
  return cell === undefined || cell === '' ? '—' : cell
}

function isNumericCol(col: number): boolean {
  if (col === 0) return false
  const vals = props.rows.map((r) => r[col] ?? '').filter((v) => v !== '')
  if (!vals.length) return false
  return vals.every((v) => !Number.isNaN(Number(v)))
}
</script>

<template>
  <div class="answer-table" data-test="answer-table">
    <div class="answer-table__toolbar">
      <span v-if="wide" class="answer-table__hint">表格较宽，可左右滑动查看</span>
      <span v-else class="answer-table__hint">{{ rows.length }} 行 · {{ headers.length }} 列</span>
      <button
        v-if="canChart"
        type="button"
        class="answer-table__toggle"
        data-test="table-chart-toggle"
        @click="mode = mode === 'table' ? 'chart' : 'table'"
      >
        {{ mode === 'table' ? '切换为图表' : '切换为表格' }}
      </button>
    </div>
    <div v-show="mode === 'table'" class="answer-table__scroll">
      <table>
        <thead>
          <tr>
            <th
              v-for="(h, i) in headers"
              :key="i"
              :class="{ sticky: i === 0, numeric: isNumericCol(i) }"
            >
              {{ display(h) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in rows" :key="ri">
            <td
              v-for="(_, ci) in headers"
              :key="ci"
              :class="{ sticky: ci === 0, numeric: isNumericCol(ci), empty: !(row[ci] ?? '') }"
            >
              {{ display(row[ci]) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="mode === 'chart' && chartOption" class="answer-table__chart">
      <EChart :option="chartOption as EChartsCoreOption" height="320px" />
    </div>
  </div>
</template>

<style scoped>
.answer-table {
  margin: 12px 0;
  border: 1px solid var(--ekb-code-border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--ekb-bg-card, var(--el-bg-color));
}
.answer-table__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--ekb-bg-fill-2, var(--el-fill-color-light));
  border-bottom: 1px solid var(--ekb-code-border);
}
.answer-table__toggle {
  flex-shrink: 0;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--el-color-primary);
  background: transparent;
  border: 1px solid var(--el-color-primary-light-5);
  border-radius: 999px;
  cursor: pointer;
}
.answer-table__toggle:hover {
  background: var(--el-color-primary-light-9);
}
.answer-table__scroll {
  overflow: auto;
  max-height: min(60vh, 520px);
}
table {
  border-collapse: separate;
  border-spacing: 0;
  width: max-content;
  min-width: 100%;
  font-size: 13px;
}
th,
td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--ekb-code-border);
  border-right: 1px solid var(--ekb-code-border);
  white-space: nowrap;
  text-align: left;
  vertical-align: middle;
  writing-mode: horizontal-tb;
  background: var(--ekb-bg-card, var(--el-bg-color));
}
th {
  position: sticky;
  top: 0;
  z-index: 2;
  font-weight: 600;
  background: var(--ekb-table-header, var(--el-fill-color-light));
}
th.sticky,
td.sticky {
  position: sticky;
  left: 0;
  z-index: 1;
  font-weight: 600;
  background: var(--ekb-table-header, var(--el-fill-color-light));
  box-shadow: 1px 0 0 var(--ekb-code-border);
}
th.sticky {
  z-index: 3;
}
td.numeric,
th.numeric {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
td.empty {
  color: var(--el-text-color-placeholder);
}
.answer-table__chart {
  padding: 8px 4px 4px;
}
</style>
