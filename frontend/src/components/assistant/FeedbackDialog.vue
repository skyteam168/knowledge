<script setup lang="ts">
import { reactive, watch } from 'vue'
import type { FeedbackReason, MessageFeedback } from '@/api/types'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ initial: MessageFeedback | null; submitting?: boolean }>()
const emit = defineEmits<{ submit: [value: { reasons: FeedbackReason[]; comment: string }] }>()

const REASONS: { value: FeedbackReason; label: string }[] = [
  { value: 'inaccurate', label: '不准确' },
  { value: 'incomplete', label: '不完整' },
  { value: 'outdated', label: '过时' },
  { value: 'not_found', label: '未找到' },
]

const form = reactive({ reasons: [] as FeedbackReason[], comment: '' })

watch(visible, (open) => {
  if (!open) return
  const prev = props.initial?.rating === 'down' ? props.initial : null
  form.reasons = [...(prev?.reasons ?? [])]
  form.comment = prev?.comment ?? ''
})
</script>

<template>
  <el-dialog v-model="visible" title="反馈问题" width="460px">
    <el-form label-position="top">
      <el-form-item label="问题类型">
        <el-checkbox-group v-model="form.reasons">
          <el-checkbox v-for="r in REASONS" :key="r.value" :value="r.value">{{
            r.label
          }}</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="补充说明（可选）">
        <el-input
          v-model="form.comment"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          placeholder="例如：正确的规定是什么、哪里有误"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        @click="emit('submit', { reasons: [...form.reasons], comment: form.comment.trim() })"
      >
        提交
      </el-button>
    </template>
  </el-dialog>
</template>
