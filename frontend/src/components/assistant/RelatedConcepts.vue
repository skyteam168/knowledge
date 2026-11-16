<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowDown } from '@element-plus/icons-vue'
import type { RelatedConcept } from '@/api/types'

const props = defineProps<{ items: RelatedConcept[] }>()
const { t } = useI18n()
const open = ref(false)

const title = computed(() =>
  t('assistant.concepts.title', { count: props.items.length }),
)
</script>

<template>
  <div v-if="items.length" class="concepts" :class="{ open }" data-test="related-concepts">
    <button type="button" class="concepts__head" @click="open = !open">
      <span class="concepts__title">{{ title }}</span>
      <el-icon class="concepts__arrow"><ArrowDown /></el-icon>
    </button>
    <ul v-show="open" class="concepts__list">
      <li v-for="c in items" :key="c.entity_id" class="card">
        <div class="card__name">
          {{ c.canonical_name }}
          <span class="card__type">{{ c.entity_type }}</span>
        </div>
        <div v-if="c.aliases.length" class="card__row">
          <span class="label">{{ t('assistant.concepts.aliases') }}</span>
          <span v-for="a in c.aliases" :key="a" class="chip">{{ a }}</span>
        </div>
        <div v-if="c.mirrors.length" class="card__row">
          <span class="label">{{ t('assistant.concepts.mirrors') }}</span>
          <span v-for="m in c.mirrors" :key="m.external_id" class="chip">
            {{ m.label }}
            <code v-if="m.external_id">{{ m.external_id }}</code>
          </span>
        </div>
        <div v-if="c.knowledge_objects.length" class="card__row">
          <span class="label">{{ t('assistant.concepts.kos') }}</span>
          <span v-for="k in c.knowledge_objects" :key="k.id" class="chip ko">{{ k.title }}</span>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.concepts {
  margin: 0.4rem 0 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}
.concepts__head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  padding: 0.45rem 0.7rem;
  border: 0;
  background: transparent;
  color: var(--el-text-color-secondary);
  cursor: pointer;
  font-size: 0.85rem;
}
.concepts__head:hover {
  color: var(--el-text-color-primary);
}
.concepts__arrow {
  margin-left: auto;
  transition: transform 0.15s ease;
}
.concepts.open .concepts__arrow {
  transform: rotate(180deg);
}
.concepts__list {
  margin: 0;
  padding: 0 0.7rem 0.7rem;
  list-style: none;
  display: grid;
  gap: 0.55rem;
}
.card {
  padding: 0.55rem 0.65rem;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.card__name {
  font-weight: 600;
  font-size: 0.92rem;
  margin-bottom: 0.35rem;
}
.card__type {
  margin-left: 0.4rem;
  font-weight: 400;
  font-size: 0.75rem;
  color: var(--el-text-color-secondary);
}
.card__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.25rem;
  font-size: 0.8rem;
}
.label {
  color: var(--el-text-color-secondary);
  margin-right: 0.15rem;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
}
.chip code {
  font-size: 0.72rem;
  color: var(--el-color-primary);
}
.chip.ko {
  max-width: 100%;
}
</style>
