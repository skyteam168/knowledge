<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{
  title: string
  description?: string
}>()

const { t } = useI18n()
</script>

<template>
  <el-card shadow="never">
    <el-empty :description="description ?? t('layout.placeholder')">
      <template #image>
        <span />
      </template>
      <h2 class="placeholder__title">{{ title }}</h2>
    </el-empty>
  </el-card>
</template>

<style scoped>
.placeholder__title {
  margin: 0;
  font-weight: 500;
}
</style>
