<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listDocuments } from '@/api/knowledge'
import type { KbDocument } from '@/api/types'

const props = withDefaults(
  defineProps<{ kbId: string | null; multiple?: boolean; placeholder?: string }>(),
  { multiple: true, placeholder: '搜索文档标题' },
)
const model = defineModel<string[]>({ required: true })

const options = ref<KbDocument[]>([])
const loading = ref(false)

const selected = computed<string | string[]>({
  get: () => (props.multiple ? model.value : (model.value[0] ?? '')),
  set: (value) => {
    model.value = Array.isArray(value) ? value : value ? [value] : []
  },
})

async function search(keyword = ''): Promise<void> {
  if (!props.kbId) {
    options.value = []
    return
  }
  loading.value = true
  try {
    const page = await listDocuments(props.kbId, {
      keyword: keyword || undefined,
      page: 1,
      size: 30,
    })
    // Keep already selected documents visible as options.
    const selected = options.value.filter((d) => model.value.includes(d.id))
    const ids = new Set(page.items.map((d) => d.id))
    options.value = [...selected.filter((d) => !ids.has(d.id)), ...page.items]
  } finally {
    loading.value = false
  }
}

watch(
  () => props.kbId,
  () => {
    model.value = []
    options.value = []
    void search()
  },
  { immediate: true },
)
</script>

<template>
  <el-select
    v-model="selected"
    :multiple="multiple"
    filterable
    remote
    clearable
    :remote-method="search"
    :loading="loading"
    :disabled="!kbId"
    :placeholder="kbId ? placeholder : '请先选择知识库'"
    style="width: 100%"
  >
    <el-option v-for="doc in options" :key="doc.id" :label="doc.title" :value="doc.id">
      <span>{{ doc.title }}</span>
      <span class="doc-picker__meta">v{{ doc.version }} · {{ doc.filename }}</span>
    </el-option>
  </el-select>
</template>

<style scoped>
.doc-picker__meta {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
