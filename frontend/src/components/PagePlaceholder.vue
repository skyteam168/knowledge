<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <el-card shadow="never">
    <el-empty :description="description ?? '功能建设中，敬请期待'">
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
