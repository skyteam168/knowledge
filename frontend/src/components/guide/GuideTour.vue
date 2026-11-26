<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useGuideStore } from '@/stores/guide'
import { LAYOUT_TOUR, guideSelector, tourForRoute } from '@/guide/tours'

/** Lazy pages render after navigation; wait before looking for their targets. */
const props = withDefaults(defineProps<{ settleMs?: number }>(), { settleMs: 600 })

const { t } = useI18n()
const guide = useGuideStore()
const route = useRoute()
const current = ref(0)
let timer: number | undefined
let targetWatchTimer: number | undefined
let unmounted = false

function targetOf(target: string | undefined): (() => HTMLElement | null) | undefined {
  if (!target) return undefined
  return () => document.querySelector<HTMLElement>(guideSelector(target))
}

function stepTargetMissing(): boolean {
  const step = guide.steps[current.value]
  if (!step?.target) return false
  return document.querySelector(guideSelector(step.target)) === null
}

/**
 * Element Plus Tour mask uses pointer-events:auto when the highlight target is gone,
 * covering the whole page (including the sidebar). Abort before the UI freezes.
 */
function abortIfTargetGone(): void {
  if (!guide.running || unmounted) return
  if (stepTargetMissing()) void guide.end('skipped')
}

function autoplay(): void {
  window.clearTimeout(timer)
  if (!guide.loaded || guide.running) return
  timer = window.setTimeout(async () => {
    await nextTick()
    if (unmounted || guide.running) return
    if (guide.needs(LAYOUT_TOUR)) {
      if (guide.start(LAYOUT_TOUR)) return
    }
    // Skipping the welcome tour means "don't guide me": page tours then stay manual.
    if (guide.progress[LAYOUT_TOUR]?.status === 'skipped') return
    const tour = tourForRoute(route.name)
    if (tour && guide.needs(tour.key)) guide.start(tour.key)
  }, props.settleMs)
}

function finish(): void {
  void guide.end('completed')
}

function skip(): void {
  void guide.end('skipped')
}

function onModelUpdate(open: boolean): void {
  if (!open && guide.running) skip()
}

function startTargetWatch(): void {
  window.clearInterval(targetWatchTimer)
  if (!guide.running) return
  // Resize/scroll can leave a stale hole; also catch keep-alive DOM swaps without route change.
  targetWatchTimer = window.setInterval(abortIfTargetGone, 800)
  abortIfTargetGone()
}

function stopTargetWatch(): void {
  window.clearInterval(targetWatchTimer)
  targetWatchTimer = undefined
}

watch(
  () => guide.running,
  (running) => {
    current.value = 0
    if (running) startTargetWatch()
    else {
      stopTargetWatch()
      autoplay()
    }
  },
)

watch(
  () => route.fullPath,
  () => {
    // Leaving a page mid-tour removes targets → full-screen blocking mask.
    if (guide.running) {
      void guide.end('skipped')
      return
    }
    autoplay()
  },
)

watch(current, () => {
  void nextTick(abortIfTargetGone)
})

onMounted(async () => {
  await guide.load()
  autoplay()
})

onBeforeUnmount(() => {
  unmounted = true
  window.clearTimeout(timer)
  stopTargetWatch()
  if (guide.running) void guide.end('skipped')
})
</script>

<template>
  <el-tour
    v-model:current="current"
    :model-value="guide.running"
    :z-index="3000"
    :scroll-into-view-options="{ block: 'center' }"
    class="guide-tour"
    @update:model-value="onModelUpdate"
    @finish="finish"
    @close="skip"
  >
    <el-tour-step
      v-for="(step, i) in guide.steps"
      :key="`${guide.active?.key}-${i}`"
      :target="targetOf(step.target)"
      :title="step.title"
      :placement="step.placement ?? 'bottom'"
    >
      <div class="guide-step" data-test="guide-step">
        <p class="guide-step__desc">{{ step.description }}</p>
        <div class="guide-step__foot">
          <span class="guide-step__count">{{ i + 1 }} / {{ guide.steps.length }}</span>
          <button
            v-if="i < guide.steps.length - 1"
            type="button"
            class="guide-step__skip"
            data-test="guide-skip"
            @click="skip"
          >
            {{ t('guide.tour.skip') }}
          </button>
        </div>
      </div>
    </el-tour-step>
  </el-tour>
</template>

<style scoped>
.guide-step__desc {
  margin: 0;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.guide-step__foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
}
.guide-step__count {
  color: var(--el-text-color-secondary);
}
.guide-step__skip {
  padding: 0;
  color: var(--el-text-color-secondary);
  background: none;
  border: 0;
  cursor: pointer;
}
.guide-step__skip:hover {
  color: var(--el-color-primary);
}
</style>
