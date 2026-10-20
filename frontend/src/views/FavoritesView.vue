<script setup lang="ts">
import { onActivated, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { listFavorites, listRecent, removeFavorite } from '@/api/collab'
import type { SavedItem } from '@/api/types'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const { t } = useI18n()
const tab = ref<'favorites' | 'recent'>('favorites')
const items = ref<SavedItem[]>([])
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = tab.value === 'favorites' ? await listFavorites() : await listRecent(50)
  } finally {
    loading.value = false
  }
}

async function unfavorite(item: SavedItem): Promise<void> {
  await removeFavorite(item.resource_type, item.resource_id)
  items.value = items.value.filter(
    (i) => !(i.resource_type === item.resource_type && i.resource_id === item.resource_id),
  )
}

watch(tab, load)
onMounted(load)
onActivated(load)
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab">
      <el-tab-pane :label="t('collab.favorite.tabFavorites')" name="favorites" />
      <el-tab-pane :label="t('collab.favorite.tabRecent')" name="recent" />
    </el-tabs>
    <p class="hint">{{ t('collab.favorite.hint') }}</p>
    <el-table
      v-loading="loading"
      :data="items"
      data-test="saved-items"
      :empty-text="
        tab === 'favorites' ? t('collab.favorite.emptyFavorites') : t('collab.favorite.emptyRecent')
      "
    >
      <el-table-column :label="t('knowledge.doc.title')" min-width="260">
        <template #default="{ row }">
          <el-tag size="small" effect="plain" class="type">{{
            t(`collab.favorite.type.${(row as SavedItem).resource_type}`)
          }}</el-tag>
          <el-link
            type="primary"
            :underline="false"
            @click="router.push((row as SavedItem).link)"
            >{{ (row as SavedItem).title }}</el-link
          >
          <div v-if="(row as SavedItem).filename" class="sub">
            {{ (row as SavedItem).filename }}
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="t('collab.favorite.kb')" min-width="160">
        <template #default="{ row }">{{ (row as SavedItem).kb_name }}</template>
      </el-table-column>
      <el-table-column
        :label="
          tab === 'favorites' ? t('collab.favorite.favoritedAt') : t('collab.favorite.viewedAt')
        "
        width="170"
      >
        <template #default="{ row }">{{ formatDateTime((row as SavedItem).at) }}</template>
      </el-table-column>
      <el-table-column v-if="tab === 'favorites'" :label="t('common.actions')" width="110">
        <template #default="{ row }">
          <el-button link type="danger" @click="unfavorite(row as SavedItem)">{{
            t('collab.favorite.unfavorite')
          }}</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.hint {
  margin: -6px 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.type {
  margin-right: 8px;
}
.sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
