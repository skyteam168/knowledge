<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <el-result icon="warning" title="404" :sub-title="t('layout.notFound')">
    <template #extra>
      <RouterLink to="/">
        <el-button type="primary">{{ t('layout.backHome') }}</el-button>
      </RouterLink>
    </template>
  </el-result>
</template>
