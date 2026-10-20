<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { Star, StarFilled } from '@element-plus/icons-vue'
import { addFavorite, getFavoriteState, removeFavorite } from '@/api/collab'
import type { SavedResourceType } from '@/api/types'

const props = defineProps<{ type: SavedResourceType; id: string }>()
const { t } = useI18n()
const favorited = ref(false)
const busy = ref(false)

watch(
  () => [props.type, props.id] as const,
  async ([type, id]) => {
    favorited.value = false
    if (id) favorited.value = (await getFavoriteState(type, id)).favorited
  },
  { immediate: true },
)

async function toggle(): Promise<void> {
  busy.value = true
  try {
    const next = favorited.value
      ? await removeFavorite(props.type, props.id)
      : await addFavorite(props.type, props.id)
    favorited.value = next.favorited
    ElMessage.success(t(next.favorited ? 'collab.favorite.added' : 'collab.favorite.removed'))
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-button
    :icon="favorited ? StarFilled : Star"
    :type="favorited ? 'warning' : 'default'"
    :plain="favorited"
    :loading="busy"
    data-test="favorite-toggle"
    :data-favorited="favorited"
    @click="toggle"
    >{{ favorited ? t('collab.favorite.remove') : t('collab.favorite.add') }}</el-button
  >
</template>
