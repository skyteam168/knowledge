<script setup lang="ts">
withDefaults(
  defineProps<{
    description: string
    actionLabel?: string
  }>(),
  { actionLabel: undefined },
)

const emit = defineEmits<{ action: [] }>()
</script>

<template>
  <el-empty class="ekb-empty" :description="description" :image-size="72">
    <el-button v-if="actionLabel" type="primary" @click="emit('action')">
      {{ actionLabel }}
    </el-button>
    <slot />
  </el-empty>
</template>

<style scoped>
.ekb-empty {
  padding: 28px 12px;
}
</style>
