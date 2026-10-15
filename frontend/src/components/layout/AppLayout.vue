<script setup lang="ts">
import {
  computed,
  defineComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type Component,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  Bell,
  ChatDotRound,
  Collection,
  Connection,
  Cpu,
  DataAnalysis,
  Document,
  Expand,
  Files,
  Finished,
  Fold,
  Guide,
  Key,
  Lock,
  Monitor,
  Moon,
  Notebook,
  OfficeBuilding,
  Operation,
  Opportunity,
  QuestionFilled,
  Reading,
  Refresh,
  RefreshLeft,
  Search,
  Setting,
  Sunny,
  SwitchButton,
  TrendCharts,
  User,
  UserFilled,
  Warning,
} from '@element-plus/icons-vue'
import { menuRoutes, type MenuRoute } from '@/router/routes'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { useGuideStore } from '@/stores/guide'
import { LAYOUT_TOUR, tourForRoute } from '@/guide/tours'
import GuideTour from '@/components/guide/GuideTour.vue'
import { useTagsStore } from '@/stores/tags'
import { fetchReadiness } from '@/api/system'
import { useTheme, type ThemeMode } from '@/composables/useTheme'
import type { ReadinessResponse } from '@/api/types'
import AppLogo from './AppLogo.vue'
import TagsView from './TagsView.vue'

const iconMap: Record<string, Component> = {
  ChatDotRound,
  Collection,
  Connection,
  Cpu,
  Search,
  Setting,
  DataAnalysis,
  OfficeBuilding,
  User,
  UserFilled,
  Lock,
  Document,
  Refresh,
  Operation,
  Opportunity,
  Warning,
  Notebook,
  Finished,
  Files,
  Key,
  TrendCharts,
}

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const auth = useAuthStore()
const notifications = useNotificationStore()
const tags = useTagsStore()

function visible(routes: MenuRoute[]): MenuRoute[] {
  return routes
    .filter((r) => auth.can(r.meta.permission))
    .map((r) => (r.children ? { ...r, children: visible(r.children) } : r))
    .filter((r) => !r.children || r.children.length > 0)
}

const menus = computed(() => visible(menuRoutes))
const activeMenu = computed(() => route.meta.activeMenu ?? route.path)

const breadcrumbs = computed(() => {
  const crumbs: string[] = []
  const target = activeMenu.value
  for (const item of menuRoutes as MenuRoute[]) {
    if (item.path === target) {
      crumbs.push(item.meta.title)
      break
    }
    const child = item.children?.find((c) => c.path === target)
    if (child) {
      crumbs.push(item.meta.title, child.meta.title)
      break
    }
  }
  const title = route.meta.title
  if (title && crumbs[crumbs.length - 1] !== title) crumbs.push(title)
  return crumbs
})

const readiness = ref<ReadinessResponse['status'] | 'unknown'>('unknown')
const readinessTag = computed(() => {
  switch (readiness.value) {
    case 'ready':
      return { level: 'success', text: '服务正常' }
    case 'degraded':
      return { level: 'warning', text: '部分降级' }
    case 'not_ready':
      return { level: 'danger', text: '服务异常' }
    default:
      return { level: 'info', text: '状态未知' }
  }
})

const theme = useTheme()
const THEME_OPTIONS: { value: ThemeMode; label: string; icon: Component }[] = [
  { value: 'light', label: '浅色', icon: Sunny },
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'system', label: '跟随系统', icon: Monitor },
]
const themeIcon = computed(() => (theme.isDark.value ? Moon : Sunny))

const avatarText = computed(() => (auth.displayName || '?').trim().slice(0, 1).toUpperCase())

const keyword = ref('')
const searchInput = ref<{ focus: () => void }>()
const canSearch = computed(() => auth.can('search:use'))

function submitSearch(): void {
  const q = keyword.value.trim()
  if (!q) return
  void router.push({ name: 'search', query: { q } })
  keyword.value = ''
}

function onHotkey(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k' && canSearch.value) {
    event.preventDefault()
    searchInput.value?.focus()
  }
}

async function onCommand(command: string): Promise<void> {
  if (command === 'logout') {
    tags.reset()
    await auth.logout()
  } else if (command === 'notifications') {
    void router.push('/notifications')
  }
}

const guide = useGuideStore()

async function onHelpCommand(command: string): Promise<void> {
  if (command === 'manual') {
    void router.push('/guide')
  } else if (command === 'replay') {
    const tour = tourForRoute(route.name)
    if (!guide.start(tour?.key ?? LAYOUT_TOUR)) ElMessage.info('当前页面暂无可播放的引导')
  } else if (command === 'restart') {
    try {
      await ElMessageBox.confirm('将清除你的引导记录，并从系统导览重新开始。', '重新开始全部引导', {
        type: 'info',
        confirmButtonText: '重新开始',
        cancelButtonText: '取消',
      })
    } catch {
      return
    }
    try {
      await guide.reset()
    } catch {
      return
    }
    guide.start(LAYOUT_TOUR)
  }
}

/**
 * One named wrapper per path so keep-alive can cache (and evict) each tab independently,
 * including several instances of the same view component with different params.
 */
const wrappers = new Map<string, Component>()
function pageFor(key: string): Component {
  let wrapper = wrappers.get(key)
  if (!wrapper) {
    wrapper = defineComponent({
      name: key,
      setup(_, { slots }) {
        return () => slots.default?.()
      },
    })
    wrappers.set(key, wrapper)
  }
  return wrapper
}

const refreshing = ref<string[]>([])
const cacheInclude = computed(() =>
  tags.cachedKeys.filter((key) => !refreshing.value.includes(key)),
)
const renderKey = computed(() => `${route.path}#${tags.refreshSeq[route.path] ?? 0}`)

watch(
  () => ({ ...tags.refreshSeq }),
  async (next, prev) => {
    const changed = Object.keys(next).filter((k) => next[k] !== prev?.[k])
    if (!changed.length) return
    refreshing.value = [...refreshing.value, ...changed]
    await nextTick()
    refreshing.value = refreshing.value.filter((k) => !changed.includes(k))
  },
)

watch(
  () => route.fullPath,
  () => tags.track(route),
  { immediate: true },
)

onMounted(async () => {
  notifications.startPolling()
  window.addEventListener('keydown', onHotkey)
  try {
    readiness.value = (await fetchReadiness()).status
  } catch {
    readiness.value = 'unknown'
  }
})

onBeforeUnmount(() => {
  notifications.stopPolling()
  window.removeEventListener('keydown', onHotkey)
})
</script>

<template>
  <div class="layout" :class="{ 'layout--collapsed': appStore.sidebarCollapsed }">
    <aside class="layout__aside">
      <div class="layout__logo" @click="router.push('/')">
        <AppLogo :collapsed="appStore.sidebarCollapsed" />
      </div>
      <el-scrollbar class="layout__menu-scroll">
        <el-menu
          :default-active="activeMenu"
          :collapse="appStore.sidebarCollapsed"
          :collapse-transition="false"
          :default-openeds="menus.filter((m) => m.children).map((m) => m.path)"
          router
          class="layout__menu"
          data-test="side-menu"
        >
          <template v-for="item in menus" :key="item.path">
            <el-sub-menu v-if="item.children" :index="item.path" :data-guide="`menu-${item.name}`">
              <template #title>
                <el-icon><component :is="iconMap[item.meta.icon]" /></el-icon>
                <span>{{ item.meta.title }}</span>
              </template>
              <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
                <el-icon><component :is="iconMap[child.meta.icon]" /></el-icon>
                <template #title>{{ child.meta.title }}</template>
              </el-menu-item>
            </el-sub-menu>
            <el-menu-item v-else :index="item.path" :data-guide="`menu-${item.name}`">
              <el-icon><component :is="iconMap[item.meta.icon]" /></el-icon>
              <template #title>{{ item.meta.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
      <button class="layout__collapse" type="button" @click="appStore.toggleSidebar">
        <el-icon :size="16">
          <Expand v-if="appStore.sidebarCollapsed" />
          <Fold v-else />
        </el-icon>
        <span v-if="!appStore.sidebarCollapsed">收起菜单</span>
      </button>
    </aside>

    <div class="layout__body">
      <header class="layout__header">
        <div class="layout__header-left">
          <el-breadcrumb separator="/" class="layout__crumbs" data-test="breadcrumb">
            <el-breadcrumb-item v-for="(crumb, i) in breadcrumbs" :key="i">
              {{ crumb }}
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="layout__header-right">
          <el-input
            v-if="canSearch"
            ref="searchInput"
            v-model="keyword"
            class="layout__search"
            placeholder="搜索知识…"
            :prefix-icon="Search"
            data-test="global-search"
            data-guide="global-search"
            @keyup.enter="submitSearch"
          >
            <template #suffix><kbd class="layout__kbd">Ctrl K</kbd></template>
          </el-input>
          <span
            class="layout__status"
            :class="`layout__status--${readinessTag.level}`"
            data-test="readiness-tag"
            >{{ readinessTag.text }}</span
          >
          <el-dropdown trigger="click" @command="onHelpCommand">
            <button
              class="layout__icon-btn"
              type="button"
              title="帮助"
              data-test="help-menu"
              data-guide="help"
            >
              <el-icon :size="18"><QuestionFilled /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="manual" :icon="Reading">使用说明</el-dropdown-item>
                <el-dropdown-item command="replay" :icon="Guide">重新播放本页引导</el-dropdown-item>
                <el-dropdown-item command="restart" :icon="RefreshLeft">
                  重新开始全部引导
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-dropdown trigger="click" @command="theme.setThemeMode">
            <button
              class="layout__icon-btn"
              type="button"
              title="切换主题"
              data-test="theme-toggle"
              data-guide="theme"
            >
              <el-icon :size="18"><component :is="themeIcon" /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="opt in THEME_OPTIONS"
                  :key="opt.value"
                  :command="opt.value"
                  :icon="opt.icon"
                  :class="{ 'is-current': theme.mode.value === opt.value }"
                >
                  {{ opt.label }}
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-badge
            :value="notifications.unread"
            :hidden="!notifications.unread"
            :max="99"
            class="layout__bell"
          >
            <button
              class="layout__icon-btn"
              type="button"
              title="消息通知"
              data-test="notification-bell"
              data-guide="notifications"
              @click="router.push('/notifications')"
            >
              <el-icon :size="18"><Bell /></el-icon>
            </button>
          </el-badge>
          <el-dropdown trigger="click" @command="onCommand">
            <span class="layout__user" data-test="user-menu">
              <span class="layout__avatar">{{ avatarText }}</span>
              <span class="layout__user-name">{{ auth.displayName }}</span>
              <el-icon class="layout__user-arrow"><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <div class="layout__user-card">
                <div class="layout__user-card-name">{{ auth.displayName }}</div>
                <div class="layout__user-card-meta">
                  {{ auth.profile?.org.name }}
                  <template v-if="auth.profile?.roles.length">
                    · {{ auth.profile.roles.map((r) => r.name).join('、') }}
                  </template>
                </div>
              </div>
              <el-dropdown-menu>
                <el-dropdown-item command="notifications" :icon="Bell">消息通知</el-dropdown-item>
                <el-dropdown-item command="logout" :icon="SwitchButton" divided>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <TagsView />
      <main class="layout__main" data-test="layout-main">
        <RouterView v-slot="{ Component: view, route: r }">
          <KeepAlive :include="cacheInclude" :max="20">
            <component :is="pageFor(r.path)" :key="renderKey">
              <component :is="view" />
            </component>
          </KeepAlive>
        </RouterView>
      </main>
    </div>
    <GuideTour />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--ekb-bg-page);
}

.layout__aside {
  flex: none;
  width: var(--ekb-sider-w);
  display: flex;
  flex-direction: column;
  background: var(--ekb-bg-sider);
  border-right: 1px solid var(--ekb-border-soft);
  transition: width 0.2s ease;
  overflow: hidden;
}
.layout--collapsed .layout__aside {
  width: var(--ekb-sider-collapsed-w);
}

.layout__logo {
  height: var(--ekb-header-h);
  flex: none;
  display: flex;
  align-items: center;
  padding: 0 16px;
  cursor: pointer;
}
.layout--collapsed .layout__logo {
  justify-content: center;
  padding: 0;
}

.layout__menu-scroll {
  flex: 1;
  min-height: 0;
}

.layout__menu {
  --el-menu-bg-color: transparent;
  --el-menu-hover-bg-color: var(--ekb-bg-hover);
  --el-menu-item-height: 40px;
  --el-menu-sub-item-height: 38px;
  --el-menu-text-color: var(--ekb-text-2);
  --el-menu-active-color: var(--ekb-primary);
  --el-menu-base-level-padding: 14px;
  --el-menu-level-padding: 14px;
  border-right: none;
  padding: 4px 0 12px;
}
.layout__menu :deep(.el-menu-item),
.layout__menu :deep(.el-sub-menu__title) {
  margin: 2px 10px;
  border-radius: var(--ekb-radius);
  font-size: 14px;
}
.layout__menu :deep(.el-sub-menu .el-menu-item) {
  padding-left: 42px !important;
  min-width: 0;
}
.layout__menu :deep(.el-menu-item.is-active) {
  background: var(--ekb-primary-soft);
  font-weight: 600;
}
.layout__menu :deep(.el-sub-menu.is-active > .el-sub-menu__title) {
  color: var(--ekb-text-1);
  font-weight: 600;
}
.layout__menu.el-menu--collapse {
  width: var(--ekb-sider-collapsed-w);
}
.layout__menu.el-menu--collapse :deep(.el-menu-item),
.layout__menu.el-menu--collapse :deep(.el-sub-menu__title) {
  margin: 2px 8px;
  padding: 0 !important;
  justify-content: center;
}

.layout__collapse {
  flex: none;
  height: 44px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 24px;
  border: none;
  border-top: 1px solid var(--ekb-border-soft);
  background: transparent;
  color: var(--ekb-text-3);
  font-size: 13px;
  cursor: pointer;
}
.layout--collapsed .layout__collapse {
  justify-content: center;
  padding: 0;
}
.layout__collapse:hover {
  color: var(--ekb-primary);
}

.layout__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.layout__header {
  height: var(--ekb-header-h);
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 20px;
  background: var(--ekb-bg-panel);
  border-bottom: 1px solid var(--ekb-border-soft);
}
.layout__header-left,
.layout__header-right {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.layout__crumbs :deep(.el-breadcrumb__inner) {
  color: var(--ekb-text-3);
  font-weight: 400;
}
.layout__crumbs :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--ekb-text-1);
  font-weight: 600;
}

.layout__search {
  width: 240px;
  --el-input-bg-color: var(--ekb-bg-input);
  --el-input-border-color: transparent;
  --el-input-border-radius: 16px;
}
.layout__search :deep(.el-input__wrapper) {
  border-radius: 16px;
}
.layout__kbd {
  padding: 0 6px;
  border: 1px solid var(--ekb-border);
  border-radius: 4px;
  font-size: 11px;
  font-family: inherit;
  line-height: 18px;
  color: var(--ekb-text-3);
  background: var(--ekb-bg-panel);
}

.layout__status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  white-space: nowrap;
  background: var(--ekb-bg-hover);
  color: var(--ekb-text-2);
}
.layout__status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.layout__status--success {
  background: var(--ekb-success-bg);
  color: var(--ekb-success-text);
}
.layout__status--warning {
  background: var(--ekb-warning-bg);
  color: var(--ekb-warning-strong);
}
.layout__status--danger {
  background: var(--ekb-danger-bg);
  color: var(--ekb-danger-strong);
}

.layout__icon-btn {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--ekb-radius);
  background: transparent;
  color: var(--ekb-text-2);
  cursor: pointer;
}
.layout__icon-btn:hover {
  background: var(--ekb-bg-hover);
  color: var(--ekb-text-1);
}
.layout__bell :deep(.el-badge__content) {
  top: 6px;
  right: 8px;
}

.layout__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px 4px 4px;
  border-radius: 18px;
  cursor: pointer;
}
.layout__user:hover {
  background: var(--ekb-bg-hover);
}
.layout__avatar {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--ekb-gradient);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
}
.layout__user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--ekb-text-1);
}
.layout__user-arrow {
  color: var(--ekb-text-3);
}
.layout__user-card {
  padding: 12px 16px 8px;
  min-width: 200px;
  border-bottom: 1px solid var(--ekb-border-soft);
}
.layout__user-card-name {
  font-weight: 600;
  color: var(--ekb-text-1);
}
.layout__user-card-meta {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ekb-text-3);
}

.layout__main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--ekb-content-pad);
}
</style>
