<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <el-result icon="error" title="403" :sub-title="t('layout.forbidden')">
    <template #extra>
      <RouterLink to="/">
        <el-button type="primary">{{ t('layout.backHome') }}</el-button>
      </RouterLink>
    </template>
  </el-result>
</template>
