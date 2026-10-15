<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { listKoVersions } from '@/api/curation'
import type { KoVersion } from '@/api/types'
import { diffLines, hasChanges, type DiffLine } from '@/utils/diff'
import { KO_TYPE_LABEL, KO_VERSION_STATUS_META, metaOf } from '@/utils/curation'
import { formatDateTime } from '@/utils/format'

const props = defineProps<{ koId: string }>()
const visible = defineModel<boolean>({ required: true })

const versions = ref<KoVersion[]>([])
const loading = ref(false)
const base = ref<number | null>(null)
const target = ref<number | null>(null)

async function load(): Promise<void> {
  loading.value = true
  try {
    versions.value = await listKoVersions(props.koId)
    const sorted = [...versions.value].sort((a, b) => b.version - a.version)
    target.value = sorted[0]?.version ?? null
    base.value = sorted[1]?.version ?? null
  } finally {
    loading.value = false
  }
}

watch(visible, (open) => {
  if (open) void load()
})

const baseVersion = computed(() => versions.value.find((v) => v.version === base.value) ?? null)
const targetVersion = computed(() => versions.value.find((v) => v.version === target.value) ?? null)

function text(v: KoVersion | null, field: 'title' | 'question' | 'answer'): string {
  return v ? v[field] : ''
}

function sourcesText(v: KoVersion | null): string {
  return (v?.sources ?? [])
    .map((s) => String(s.title ?? s.document_id ?? ''))
    .filter(Boolean)
    .join('\n')
}

function effectiveWindow(v: KoVersion | null): string {
  if (!v) return ''
  return `${formatDateTime(v.effective_from)} ~ ${formatDateTime(v.effective_to)}`
}

const sections = computed<{ name: string; lines: DiffLine[] }[]>(() => {
  const a = baseVersion.value
  const b = targetVersion.value
  return [
    {
      name: '类型',
      lines: diffLines(a ? KO_TYPE_LABEL[a.ko_type] : '', b ? KO_TYPE_LABEL[b.ko_type] : ''),
    },
    { name: '标题', lines: diffLines(text(a, 'title'), text(b, 'title')) },
    { name: '标准问题', lines: diffLines(text(a, 'question'), text(b, 'question')) },
    {
      name: '相似问法',
      lines: diffLines((a?.variants ?? []).join('\n'), (b?.variants ?? []).join('\n')),
    },
    { name: '答案', lines: diffLines(text(a, 'answer'), text(b, 'answer')) },
    { name: '引用来源', lines: diffLines(sourcesText(a), sourcesText(b)) },
    { name: '生效时间', lines: diffLines(effectiveWindow(a), effectiveWindow(b)) },
  ]
})

const MARK: Record<DiffLine['op'], string> = { equal: ' ', add: '+', remove: '-' }
</script>

<template>
  <el-drawer v-model="visible" title="版本历史" size="70%">
    <div v-loading="loading" class="history">
      <el-table :data="versions" size="small" class="history__table" max-height="260">
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="metaOf(KO_VERSION_STATUS_META, row.status).type">
              {{ metaOf(KO_VERSION_STATUS_META, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" prop="title" min-width="180" show-overflow-tooltip />
        <el-table-column label="提交人" width="100">
          <template #default="{ row }">{{ row.created_by?.name ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="发布" width="200">
          <template #default="{ row }">
            <template v-if="row.published_at">
              {{ row.published_by?.name ?? '-' }} · {{ formatDateTime(row.published_at) }}
            </template>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="说明" prop="note" min-width="140" show-overflow-tooltip />
      </el-table>

      <el-empty v-if="!versions.length" description="尚未提交过审核，暂无版本" />
      <template v-else>
        <div class="history__pick">
          对比
          <el-select v-model="base" clearable placeholder="（空）" style="width: 120px">
            <el-option
              v-for="v in versions"
              :key="v.version"
              :label="`v${v.version}`"
              :value="v.version"
            />
          </el-select>
          →
          <el-select v-model="target" style="width: 120px">
            <el-option
              v-for="v in versions"
              :key="v.version"
              :label="`v${v.version}`"
              :value="v.version"
            />
          </el-select>
        </div>
        <div v-for="s in sections" :key="s.name" class="history__section">
          <div class="history__name">
            {{ s.name }}
            <el-tag v-if="hasChanges(s.lines)" size="small" type="warning">有变更</el-tag>
          </div>
          <pre class="history__diff" data-test="ko-diff"><div
            v-for="(line, i) in s.lines"
            :key="i"
            :class="`diff--${line.op}`"
          >{{ MARK[line.op] }} {{ line.text }}</div></pre>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.history__table {
  margin-bottom: 16px;
}

.history__pick {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.history__section {
  margin-bottom: 12px;
}

.history__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  margin-bottom: 4px;
}

.history__diff {
  margin: 0;
  padding: 8px;
  font-size: 13px;
  line-height: 1.6;
  background: var(--el-fill-color-lighter);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}

.diff--add {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
}

.diff--remove {
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger-dark-2);
  text-decoration: line-through;
}
</style>
