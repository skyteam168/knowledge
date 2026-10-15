<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Close, RefreshRight } from '@element-plus/icons-vue'
import { useTagsStore, type TagView } from '@/stores/tags'

const route = useRoute()
const router = useRouter()
const store = useTagsStore()

const scroller = ref<HTMLElement>()
const menu = reactive({ visible: false, x: 0, y: 0, key: '' })
const dragFrom = ref(-1)
const dragOver = ref(-1)

const activeKey = computed(() => route.path)
const menuIndex = computed(() => store.tags.findIndex((t) => t.key === menu.key))

function go(tag: TagView): void {
  if (tag.key !== activeKey.value) void router.push(tag.fullPath)
}

function close(tag: TagView): void {
  const wasActive = tag.key === activeKey.value
  const next = store.close(tag.key)
  if (!wasActive) return
  void router.push(next ? next.fullPath : '/')
}

function openMenu(event: MouseEvent, tag: TagView): void {
  menu.visible = true
  menu.key = tag.key
  menu.x = event.clientX
  menu.y = event.clientY
}

function hideMenu(): void {
  menu.visible = false
}

function command(action: 'refresh' | 'close' | 'others' | 'left' | 'right' | 'all'): void {
  const tag = store.tags.find((t) => t.key === menu.key)
  hideMenu()
  if (!tag) return
  switch (action) {
    case 'refresh':
      store.refresh(tag.key)
      if (tag.key !== activeKey.value) void router.push(tag.fullPath)
      break
    case 'close':
      close(tag)
      break
    case 'others':
      store.closeOthers(tag.key)
      go(tag)
      break
    case 'left':
      store.closeLeft(tag.key)
      if (!store.tags.some((t) => t.key === activeKey.value)) go(tag)
      break
    case 'right':
      store.closeRight(tag.key)
      if (!store.tags.some((t) => t.key === activeKey.value)) go(tag)
      break
    case 'all':
      store.closeAll()
      void router.push('/')
      break
  }
}

function scrollBy(delta: number): void {
  scroller.value?.scrollBy({ left: delta, behavior: 'smooth' })
}

function onWheel(event: WheelEvent): void {
  if (!scroller.value || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  scroller.value.scrollLeft += event.deltaY
}

function onDrop(index: number): void {
  store.move(dragFrom.value, index)
  dragFrom.value = -1
  dragOver.value = -1
}

watch(
  activeKey,
  () => {
    void nextTick(() => {
      const active = scroller.value?.querySelector<HTMLElement>('.tags__item--active')
      active?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'smooth' })
    })
  },
  { immediate: true },
)

onMounted(() => document.addEventListener('click', hideMenu))
onBeforeUnmount(() => document.removeEventListener('click', hideMenu))
</script>

<template>
  <div class="tags" data-test="tags-view">
    <button class="tags__nav" type="button" aria-label="向左滚动" @click="scrollBy(-240)">
      <el-icon><ArrowLeft /></el-icon>
    </button>
    <div ref="scroller" class="tags__scroller" @wheel.prevent="onWheel">
      <div
        v-for="(tag, index) in store.tags"
        :key="tag.key"
        class="tags__item"
        :class="{
          'tags__item--active': tag.key === activeKey,
          'tags__item--over': dragOver === index && dragFrom !== index,
        }"
        :title="tag.title"
        draggable="true"
        data-test="tag-item"
        @click="go(tag)"
        @click.middle.prevent="close(tag)"
        @contextmenu.prevent="openMenu($event, tag)"
        @dragstart="dragFrom = index"
        @dragover.prevent="dragOver = index"
        @dragleave="dragOver = -1"
        @drop.prevent="onDrop(index)"
        @dragend="dragFrom = -1"
      >
        <span class="tags__dot" />
        <span class="tags__title">{{ tag.title }}</span>
        <el-icon
          v-if="!tag.affix && store.tags.length > 1"
          class="tags__close"
          @click.stop="close(tag)"
        >
          <Close />
        </el-icon>
      </div>
    </div>
    <button class="tags__nav" type="button" aria-label="向右滚动" @click="scrollBy(240)">
      <el-icon><ArrowRight /></el-icon>
    </button>
    <button
      class="tags__nav tags__nav--refresh"
      type="button"
      title="刷新当前页"
      @click="store.refresh(activeKey)"
    >
      <el-icon><RefreshRight /></el-icon>
    </button>

    <Teleport to="body">
      <ul
        v-show="menu.visible"
        class="tags-menu"
        :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
        data-test="tags-menu"
      >
        <li @click="command('refresh')">刷新页面</li>
        <li v-if="store.tags.length > 1" @click="command('close')">关闭当前</li>
        <li v-if="store.tags.length > 1" @click="command('others')">关闭其他</li>
        <li v-if="menuIndex > 0" @click="command('left')">关闭左侧</li>
        <li v-if="menuIndex < store.tags.length - 1" @click="command('right')">关闭右侧</li>
        <li class="tags-menu__divider" />
        <li @click="command('all')">全部关闭</li>
      </ul>
    </Teleport>
  </div>
</template>

<style scoped>
.tags {
  height: var(--ekb-tags-h);
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  background: var(--ekb-bg-panel);
  border-bottom: 1px solid var(--ekb-border-soft);
  box-shadow: var(--ekb-shadow-sm);
}
.tags__scroller {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
}
.tags__scroller::-webkit-scrollbar {
  display: none;
}
.tags__nav {
  flex: none;
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--ekb-radius-sm);
  background: transparent;
  color: var(--ekb-text-3);
  cursor: pointer;
}
.tags__nav:hover {
  background: var(--ekb-bg-hover);
  color: var(--ekb-text-1);
}
.tags__nav--refresh {
  margin-left: 2px;
  border-left: 1px solid var(--ekb-border-soft);
  border-radius: 0 var(--ekb-radius-sm) var(--ekb-radius-sm) 0;
}
.tags__item {
  flex: none;
  height: 28px;
  max-width: 180px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius-sm);
  background: var(--ekb-bg-subtle);
  color: var(--ekb-text-2);
  font-size: 13px;
  cursor: pointer;
  user-select: none;
  transition:
    background 0.15s,
    color 0.15s,
    border-color 0.15s;
}
.tags__item:hover {
  color: var(--ekb-primary);
  background: var(--ekb-primary-softer);
}
.tags__item--active {
  color: var(--ekb-primary);
  background: var(--ekb-primary-soft);
  border-color: var(--el-color-primary-light-7);
  font-weight: 500;
}
.tags__item--over {
  border-style: dashed;
  border-color: var(--ekb-primary);
}
.tags__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ekb-scrollbar);
  flex: none;
}
.tags__item--active .tags__dot {
  background: var(--ekb-primary);
  box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.15);
}
.tags__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tags__close {
  flex: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  font-size: 11px;
  color: var(--ekb-text-3);
}
.tags__close:hover {
  background: var(--el-color-primary-light-7);
  color: #fff;
}
.tags-menu {
  position: fixed;
  z-index: 3000;
  margin: 0;
  padding: 4px;
  min-width: 120px;
  list-style: none;
  background: var(--ekb-bg-overlay);
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius);
  box-shadow: var(--ekb-shadow-lg);
  font-size: 13px;
  color: var(--ekb-text-1);
}
.tags-menu li {
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.tags-menu li:hover {
  background: var(--ekb-bg-hover);
}
.tags-menu .tags-menu__divider {
  height: 1px;
  margin: 4px 0;
  padding: 0;
  background: var(--ekb-border-soft);
  pointer-events: none;
}
</style>
