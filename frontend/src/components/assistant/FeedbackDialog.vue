<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FeedbackReason, MessageFeedback } from '@/api/types'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{ initial: MessageFeedback | null; submitting?: boolean }>()
const emit = defineEmits<{ submit: [value: { reasons: FeedbackReason[]; comment: string }] }>()
const { t } = useI18n()

const REASON_VALUES: FeedbackReason[] = ['inaccurate', 'incomplete', 'outdated', 'not_found']
const REASONS = computed(() =>
  REASON_VALUES.map((value) => ({ value, label: t(`assistant.feedback.${value}`) })),
)

const form = reactive({ reasons: [] as FeedbackReason[], comment: '' })

watch(visible, (open) => {
  if (!open) return
  const prev = props.initial?.rating === 'down' ? props.initial : null
  form.reasons = [...(prev?.reasons ?? [])]
  form.comment = prev?.comment ?? ''
})
</script>

<template>
  <el-dialog v-model="visible" :title="t('assistant.feedback.title')" width="460px">
    <el-form label-position="top">
      <el-form-item :label="t('assistant.feedback.reasons')">
        <el-checkbox-group v-model="form.reasons">
          <el-checkbox v-for="r in REASONS" :key="r.value" :value="r.value">{{
            r.label
          }}</el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item :label="t('assistant.feedback.comment')">
        <el-input
          v-model="form.comment"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          :placeholder="t('assistant.feedback.commentPlaceholder')"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">{{ t('common.cancel') }}</el-button>
      <el-button
        type="primary"
        :loading="submitting"
        @click="emit('submit', { reasons: [...form.reasons], comment: form.comment.trim() })"
      >
        {{ t('common.submit') }}
      </el-button>
    </template>
  </el-dialog>
</template>
