<script setup lang="ts">
import { computed, ref, type Component } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Collection,
  DataAnalysis,
  Opportunity,
  Promotion,
  Search,
  Setting,
  VideoPlay,
} from '@element-plus/icons-vue'
import { visibleManual, type ManualSection } from '@/guide/manual'
import { useAuthStore } from '@/stores/auth'
import { useGuideStore } from '@/stores/guide'

const ICONS: Record<string, Component> = {
  ChatDotRound,
  Collection,
  DataAnalysis,
  Opportunity,
  Promotion,
  Search,
  Setting,
}

/** Lazy pages need a moment to render their tour targets after navigation. */
const START_RETRY_MS = 200
const START_ATTEMPTS = 15

const router = useRouter()
const auth = useAuthStore()
const guide = useGuideStore()

const manual = computed(() => visibleManual(auth.can))
const activeId = ref<string>('')

function sectionDomId(id: string): string {
  return `guide-section-${id}`
}

function jump(id: string): void {
  activeId.value = id
  document.getElementById(sectionDomId(id))?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function tryIt(section: ManualSection): Promise<void> {
  if (section.route) await router.push(section.route)
}

async function playTour(section: ManualSection): Promise<void> {
  const key = section.tourKey
  if (!key) return
  if (section.route) await router.push(section.route)
  for (let i = 0; i < START_ATTEMPTS; i++) {
    if (guide.running || guide.start(key)) return
    await new Promise((resolve) => window.setTimeout(resolve, START_RETRY_MS))
  }
  ElMessage.info('该页面暂无可播放的引导')
}
</script>

<template>
  <div class="guide-page">
    <aside class="guide-nav">
      <div class="guide-nav__title">使用说明</div>
      <button
        v-for="s in manual.sections"
        :key="s.id"
        type="button"
        class="guide-nav__item"
        :class="{ 'guide-nav__item--active': activeId === s.id }"
        :data-test="`guide-nav-${s.id}`"
        @click="jump(s.id)"
      >
        <el-icon><component :is="ICONS[s.icon] ?? Promotion" /></el-icon>
        <span>{{ s.title }}</span>
      </button>
      <button
        v-if="manual.faq.length"
        type="button"
        class="guide-nav__item"
        :class="{ 'guide-nav__item--active': activeId === 'faq' }"
        @click="jump('faq')"
      >
        <el-icon><Promotion /></el-icon>
        <span>常见问题</span>
      </button>
    </aside>

    <main class="guide-body">
      <section
        v-for="s in manual.sections"
        :id="sectionDomId(s.id)"
        :key="s.id"
        class="guide-section"
        :data-test="`guide-section-${s.id}`"
      >
        <header class="guide-section__head">
          <el-icon class="guide-section__icon"
            ><component :is="ICONS[s.icon] ?? Promotion"
          /></el-icon>
          <div>
            <h2 class="guide-section__title">{{ s.title }}</h2>
            <p class="guide-section__summary">{{ s.summary }}</p>
          </div>
        </header>

        <div v-for="t in s.topics" :key="t.title" class="guide-topic">
          <h3 class="guide-topic__title">{{ t.title }}</h3>
          <ol class="guide-steps">
            <li v-for="(st, i) in t.steps" :key="st.title" class="guide-step">
              <span class="guide-step__no">{{ i + 1 }}</span>
              <div>
                <div class="guide-step__title">{{ st.title }}</div>
                <div class="guide-step__detail">{{ st.detail }}</div>
              </div>
            </li>
          </ol>
        </div>

        <div v-if="s.route || s.tourKey" class="guide-section__actions">
          <el-button v-if="s.route" type="primary" plain @click="tryIt(s)">去试试</el-button>
          <el-button
            v-if="s.tourKey"
            :icon="VideoPlay"
            :data-test="`guide-play-${s.id}`"
            @click="playTour(s)"
          >
            播放该页引导
          </el-button>
        </div>
      </section>

      <section
        v-if="manual.faq.length"
        :id="sectionDomId('faq')"
        class="guide-section"
        data-test="guide-faq"
      >
        <header class="guide-section__head">
          <div>
            <h2 class="guide-section__title">常见问题</h2>
          </div>
        </header>
        <el-collapse>
          <el-collapse-item
            v-for="(f, i) in manual.faq"
            :key="f.question"
            :title="f.question"
            :name="i"
          >
            <div class="guide-step__detail">{{ f.answer }}</div>
          </el-collapse-item>
        </el-collapse>
      </section>
    </main>
  </div>
</template>

<style scoped>
.guide-page {
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.guide-nav {
  position: sticky;
  top: 0;
  flex: 0 0 180px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 8px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}

.guide-nav__title {
  padding: 4px 10px 10px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.guide-nav__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  color: var(--el-text-color-regular);
  font-size: 14px;
  text-align: left;
  background: none;
  border: 0;
  border-radius: 6px;
  cursor: pointer;
}

.guide-nav__item:hover {
  background: var(--el-fill-color-light);
}

.guide-nav__item--active {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}

.guide-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.guide-section {
  padding: 20px 24px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  scroll-margin-top: 12px;
}

.guide-section__head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 8px;
}

.guide-section__icon {
  margin-top: 2px;
  font-size: 22px;
  color: var(--el-color-primary);
}

.guide-section__title {
  margin: 0;
  font-size: 18px;
  color: var(--el-text-color-primary);
}

.guide-section__summary {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.guide-topic {
  margin-top: 16px;
}

.guide-topic__title {
  margin: 0 0 10px;
  font-size: 15px;
  color: var(--el-text-color-primary);
}

.guide-steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.guide-step {
  display: flex;
  gap: 12px;
}

.guide-step__no {
  flex: 0 0 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  font-size: 12px;
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  border-radius: 50%;
}

.guide-step__title {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.guide-step__detail {
  margin-top: 2px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.guide-section__actions {
  display: flex;
  gap: 8px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

@media (max-width: 768px) {
  .guide-page {
    flex-direction: column;
  }

  .guide-nav {
    position: static;
    flex-basis: auto;
    width: 100%;
    flex-direction: row;
    flex-wrap: wrap;
  }
}
</style>
