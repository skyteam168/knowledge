<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { compareVersions } from '@/api/knowledge'
import type { DocumentVersion, Protection, VersionCompare } from '@/api/types'
import ProtectedArea from '@/components/knowledge/ProtectedArea.vue'

/** Line diff of the parsed text of two versions (base = older side, target = newer side). */
const props = defineProps<{
  docId: string
  versions: DocumentVersion[]
  /** `[base, target]` to open with; null = closed. */
  pair: [number, number] | null
  protection: Protection | null
}>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const base = ref(0)
const target = ref(0)
const result = ref<VersionCompare | null>(null)
const loading = ref(false)

const visible = computed({
  get: () => props.pair !== null,
  set: (open) => {
    if (!open) emit('close')
  },
})
const SIGN = { equal: ' ', add: '+', del: '-' } as const

watch(
  () => props.pair,
  (pair) => {
    result.value = null
    if (pair) [base.value, target.value] = pair
  },
  { immediate: true },
)

watch(
  [base, target, visible],
  async () => {
    if (!visible.value || !base.value || !target.value) return
    if (base.value === target.value) {
      result.value = null
      return
    }
    loading.value = true
    try {
      result.value = await compareVersions(props.docId, base.value, target.value)
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

function swap(): void {
  ;[base.value, target.value] = [target.value, base.value]
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="t('knowledge.version.compareTitle')"
    width="80%"
    top="5vh"
    destroy-on-close
  >
    <div class="compare-bar">
      <span>{{ t('knowledge.version.base') }}</span>
      <el-select v-model="base" style="width: 110px" data-test="compare-base">
        <el-option
          v-for="v in versions"
          :key="v.version"
          :label="`v${v.version}`"
          :value="v.version"
        />
      </el-select>
      <el-button link @click="swap">⇄ {{ t('knowledge.version.swap') }}</el-button>
      <span>{{ t('knowledge.version.target') }}</span>
      <el-select v-model="target" style="width: 110px" data-test="compare-target">
        <el-option
          v-for="v in versions"
          :key="v.version"
          :label="`v${v.version}`"
          :value="v.version"
        />
      </el-select>
      <el-tag v-if="result?.available" effect="plain" class="stat" data-test="compare-stats">{{
        t('knowledge.version.stats', { added: result.added, removed: result.removed })
      }}</el-tag>
    </div>

    <div v-loading="loading" class="compare-body">
      <template v-if="result">
        <el-alert
          v-if="result.same_file"
          type="success"
          :closable="false"
          :title="t('knowledge.version.sameFile')"
        />
        <el-alert
          v-else-if="!result.available"
          type="warning"
          :closable="false"
          :title="t('knowledge.version.compareUnavailable')"
        />
        <el-alert
          v-else-if="!result.hunks.length"
          type="info"
          :closable="false"
          :title="t('knowledge.version.noTextChange')"
        />
        <el-alert
          v-if="result.truncated"
          type="info"
          :closable="false"
          :title="t('knowledge.version.diffTruncated')"
          class="truncated"
        />
        <ProtectedArea
          v-if="result.hunks.length"
          :watermark="protection?.watermark"
          :copy-protect="protection?.copy_protect"
          class="diff-frame"
        >
          <div class="diff" data-test="version-diff">
            <section v-for="(hunk, i) in result.hunks" :key="i" class="hunk">
              <div class="hunk__head">
                {{
                  t('knowledge.version.hunk', {
                    oldStart: hunk.find((l) => l.old_no)?.old_no ?? '-',
                    newStart: hunk.find((l) => l.new_no)?.new_no ?? '-',
                  })
                }}
              </div>
              <div
                v-for="(line, j) in hunk"
                :key="j"
                class="line"
                :class="`line--${line.op}`"
                :data-op="line.op"
              >
                <span class="no">{{ line.old_no ?? '' }}</span>
                <span class="no">{{ line.new_no ?? '' }}</span>
                <span class="sign">{{ SIGN[line.op] }}</span>
                <span class="text">{{ line.text }}</span>
              </div>
            </section>
          </div>
        </ProtectedArea>
      </template>
    </div>
  </el-dialog>
</template>

<style scoped>
.compare-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.stat {
  margin-left: 12px;
}
.compare-body {
  min-height: 200px;
}
.truncated {
  margin-top: 8px;
}
.diff-frame {
  margin-top: 8px;
}
.diff {
  height: 65vh;
  overflow: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.7;
}
.hunk + .hunk {
  border-top: 1px dashed var(--el-border-color);
}
.hunk__head {
  padding: 2px 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}
.line {
  display: grid;
  grid-template-columns: 48px 48px 20px minmax(0, 1fr);
}
.line--add {
  background: var(--el-color-success-light-9);
}
.line--del {
  background: var(--el-color-danger-light-9);
}
.no {
  padding-right: 8px;
  text-align: right;
  color: var(--el-text-color-placeholder);
  user-select: none;
}
.sign {
  text-align: center;
  color: var(--el-text-color-secondary);
}
.line--add .sign {
  color: var(--el-color-success);
}
.line--del .sign {
  color: var(--el-color-danger);
}
.text {
  white-space: pre-wrap;
  word-break: break-word;
  padding-right: 12px;
}
</style>
