<script setup lang="ts"></script>

<template>
  <el-result icon="error" title="403" sub-title="您没有访问该页面的权限，如需开通请联系管理员">
    <template #extra>
      <RouterLink to="/">
        <el-button type="primary">返回首页</el-button>
      </RouterLink>
    </template>
  </el-result>
</template>
