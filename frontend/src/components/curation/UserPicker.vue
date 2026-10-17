<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { searchPrincipals } from '@/api/knowledge'
import type { PrincipalOption, UserRef } from '@/api/types'

const props = withDefaults(defineProps<{ initial?: UserRef | null; placeholder?: string }>(), {
  initial: null,
  placeholder: '',
})
const { t } = useI18n()
const model = defineModel<string | null>({ required: true })

const options = ref<PrincipalOption[]>([])
const loading = ref(false)

async function search(keyword = ''): Promise<void> {
  loading.value = true
  try {
    options.value = await searchPrincipals('user', keyword || undefined)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.initial,
  (user) => {
    if (user && !options.value.some((o) => o.id === user.id)) {
      options.value = [
        { type: 'user', id: user.id, name: user.name, description: null },
        ...options.value,
      ]
    }
  },
  { immediate: true },
)
</script>

<template>
  <el-select
    v-model="model"
    filterable
    remote
    clearable
    :remote-method="search"
    :loading="loading"
    :placeholder="placeholder || t('curation.userPicker.placeholder')"
    style="width: 100%"
    @focus="options.length <= 1 && search()"
  >
    <el-option v-for="u in options" :key="u.id" :label="u.name" :value="u.id">
      <span>{{ u.name }}</span>
      <span v-if="u.description" class="user-picker__meta">{{ u.description }}</span>
    </el-option>
  </el-select>
</template>

<style scoped>
.user-picker__meta {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
