<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listNotifications, markNotificationsRead } from '@/api/curation'
import type { Notification } from '@/api/types'
import { useNotificationStore } from '@/stores/notifications'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const store = useNotificationStore()
const { t } = useI18n()

const unreadOnly = ref(false)
const pager = reactive({ page: 1, size: 20 })
const items = ref<Notification[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listNotifications({ unread_only: unreadOnly.value, ...pager })
    items.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function search(): void {
  pager.page = 1
  void load()
}

async function markAll(): Promise<void> {
  store.unread = (await markNotificationsRead(null)).unread
  await load()
}

async function open(n: Notification): Promise<void> {
  if (!n.read_at) {
    store.unread = (await markNotificationsRead([n.id])).unread
    n.read_at = new Date().toISOString()
  }
  if (n.link) await router.push(n.link)
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <div class="bar">
      <el-checkbox v-model="unreadOnly" @change="search">{{
        t('layout.notificationsPage.unreadOnly')
      }}</el-checkbox>
      <el-button :disabled="!store.unread" @click="markAll">{{
        t('layout.notificationsPage.markAllRead')
      }}</el-button>
    </div>
    <el-empty v-if="!loading && !items.length" :description="t('layout.notificationsPage.empty')" />
    <div v-loading="loading">
      <div
        v-for="n in items"
        :key="n.id"
        class="item"
        :class="{ 'item--unread': !n.read_at, 'item--link': !!n.link }"
        @click="open(n)"
      >
        <div class="item__title">
          <el-badge v-if="!n.read_at" is-dot class="item__dot" />
          {{ n.title }}
        </div>
        <div v-if="n.body" class="item__body">{{ n.body }}</div>
        <div class="item__time">{{ formatDateTime(n.created_at) }}</div>
      </div>
    </div>
    <el-pagination
      v-model:current-page="pager.page"
      v-model:page-size="pager.size"
      :total="total"
      layout="total, prev, pager, next"
      class="pager"
      @current-change="load"
    />
  </el-card>
</template>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.item {
  padding: 10px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.item--link {
  cursor: pointer;
}

.item--unread .item__title {
  font-weight: 600;
}

.item__dot {
  margin-right: 6px;
}

.item__body {
  margin-top: 4px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.item__time {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
