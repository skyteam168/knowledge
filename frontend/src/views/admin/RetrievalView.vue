<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { HttpError } from '@/api/http'
import {
  activateRetrievalProfile,
  createRetrievalProfile,
  deleteRetrievalProfile,
  getDefaultRetrievalConfig,
  getRetrievalTrace,
  listRetrievalProfiles,
  listRetrievalTraces,
  updateRetrievalProfile,
} from '@/api/search'
import type {
  RetrievalConfig,
  RetrievalProfile,
  RetrievalTrace,
  RetrievalTraceSummary,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

const tab = ref('profiles')

// ---- profiles ---------------------------------------------------------------------

const profiles = ref<RetrievalProfile[]>([])
const loadingProfiles = ref(false)

async function loadProfiles(): Promise<void> {
  loadingProfiles.value = true
  try {
    profiles.value = await listRetrievalProfiles()
  } finally {
    loadingProfiles.value = false
  }
}

function summary(c: RetrievalConfig): string {
  const routes = [
    c.dense.enabled ? `Dense top${c.dense.top_k}` : null,
    c.sparse.enabled ? `BM25 top${c.sparse.top_k}` : null,
  ].filter(Boolean)
  const weights = Object.entries(c.fusion.weights)
    .map(([r, w]) => `${r}×${w}`)
    .join(' ')
  const rerank = c.rerank.enabled ? `Rerank top${c.rerank.top_n}` : '无 Rerank'
  return `${routes.join(' + ')} · RRF k=${c.fusion.k} ${weights} · ${rerank} · 输出 ${c.top_k}`
}

const editor = reactive({
  visible: false,
  saving: false,
  id: null as string | null,
  name: '',
  description: '',
  json: '',
  error: '',
})

async function openEditor(profile?: RetrievalProfile, copy = false): Promise<void> {
  const config = profile ? profile.config : await getDefaultRetrievalConfig()
  editor.id = profile && !copy ? profile.id : null
  editor.name = profile && !copy ? profile.name : profile ? `${profile.name}-copy` : ''
  editor.description = (profile?.description ?? '') || ''
  editor.json = JSON.stringify(config, null, 2)
  editor.error = ''
  editor.visible = true
}

async function resetJson(): Promise<void> {
  editor.json = JSON.stringify(await getDefaultRetrievalConfig(), null, 2)
}

async function saveEditor(): Promise<void> {
  let config: RetrievalConfig
  try {
    config = JSON.parse(editor.json) as RetrievalConfig
  } catch (e) {
    editor.error = `JSON 格式错误：${(e as Error).message}`
    return
  }
  editor.saving = true
  editor.error = ''
  try {
    const body = { name: editor.name.trim(), description: editor.description || null, config }
    if (editor.id) await updateRetrievalProfile(editor.id, body)
    else await createRetrievalProfile(body)
    ElMessage.success('已保存')
    editor.visible = false
    await loadProfiles()
  } catch (e) {
    if (e instanceof HttpError && e.status === 422) {
      editor.error = JSON.stringify(e.detail, null, 2)
    }
  } finally {
    editor.saving = false
  }
}

async function activate(profile: RetrievalProfile): Promise<void> {
  await activateRetrievalProfile(profile.id ?? 'builtin')
  ElMessage.success(`已切换为「${profile.name}」`)
  await loadProfiles()
}

async function remove(profile: RetrievalProfile): Promise<void> {
  if (!profile.id) return
  await ElMessageBox.confirm(`确定删除检索策略「${profile.name}」？`, '删除', { type: 'warning' })
  await deleteRetrievalProfile(profile.id)
  ElMessage.success('已删除')
  await loadProfiles()
}

// ---- traces -----------------------------------------------------------------------

const traceFilters = reactive({ keyword: '', degraded_only: false })
const pager = reactive({ page: 1, size: 20 })
const traces = ref<RetrievalTraceSummary[]>([])
const total = ref(0)
const loadingTraces = ref(false)
const detail = ref<RetrievalTrace | null>(null)
const detailVisible = ref(false)

async function loadTraces(): Promise<void> {
  loadingTraces.value = true
  try {
    const page = await listRetrievalTraces({
      keyword: traceFilters.keyword || undefined,
      degraded_only: traceFilters.degraded_only || undefined,
      ...pager,
    })
    traces.value = page.items
    total.value = page.total
  } finally {
    loadingTraces.value = false
  }
}

function searchTraces(): void {
  pager.page = 1
  void loadTraces()
}

async function openTrace(row: RetrievalTraceSummary): Promise<void> {
  detail.value = await getRetrievalTrace(row.id)
  detailVisible.value = true
}

function onTab(name: string | number): void {
  if (name === 'traces' && !traces.value.length) void loadTraces()
}

onMounted(loadProfiles)
</script>

<template>
  <el-card shadow="never">
    <el-tabs v-model="tab" @tab-change="onTab">
      <el-tab-pane label="检索策略" name="profiles">
        <div class="toolbar">
          <span class="hint"
            >每个组织同一时间只有一个生效策略；搜索页调试模式可临时指定任意策略对比效果。</span
          >
          <el-button type="primary" @click="openEditor()">新建策略</el-button>
        </div>
        <el-table v-loading="loadingProfiles" :data="profiles" row-key="name">
          <el-table-column label="名称" min-width="160">
            <template #default="{ row }">
              <span class="name">{{ row.name }}</span>
              <el-tag v-if="row.builtin" size="small" type="info">内置</el-tag>
              <el-tag v-if="row.is_active" size="small" type="success">生效中</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
          <el-table-column label="参数" min-width="320">
            <template #default="{ row }">
              <span class="summary">{{ summary(row.config) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="更新时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="220" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="!row.is_active"
                link
                type="primary"
                @click="activate(row as RetrievalProfile)"
              >
                启用
              </el-button>
              <el-button
                v-if="!row.builtin"
                link
                type="primary"
                @click="openEditor(row as RetrievalProfile)"
              >
                编辑
              </el-button>
              <el-button link type="primary" @click="openEditor(row as RetrievalProfile, true)">
                复制
              </el-button>
              <el-button
                v-if="!row.builtin"
                link
                type="danger"
                :disabled="row.is_active"
                @click="remove(row as RetrievalProfile)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="检索日志" name="traces">
        <div class="toolbar">
          <el-input
            v-model="traceFilters.keyword"
            placeholder="查询内容"
            clearable
            class="keyword"
            @keyup.enter="searchTraces"
            @clear="searchTraces"
          />
          <el-checkbox v-model="traceFilters.degraded_only" @change="searchTraces">
            仅看降级
          </el-checkbox>
          <el-button @click="searchTraces">查询</el-button>
        </div>
        <el-table v-loading="loadingTraces" :data="traces" @row-click="openTrace">
          <el-table-column label="时间" width="170">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="query" label="查询" min-width="200" show-overflow-tooltip />
          <el-table-column prop="profile_name" label="策略" width="130" />
          <el-table-column prop="result_count" label="结果" width="70" />
          <el-table-column label="耗时" width="90">
            <template #default="{ row }">{{ row.total_ms }} ms</template>
          </el-table-column>
          <el-table-column label="状态" min-width="180">
            <template #default="{ row }">
              <el-tag v-if="row.cache_hit" size="small" type="info">缓存</el-tag>
              <el-tag v-for="d in row.degraded" :key="d" size="small" type="warning">{{
                d
              }}</el-tag>
              <el-tag v-if="row.truncated" size="small">已截断</el-tag>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="pager.page"
          v-model:page-size="pager.size"
          :total="total"
          layout="total, sizes, prev, pager, next"
          class="pager"
          @current-change="loadTraces"
          @size-change="searchTraces"
        />
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="editor.visible"
      :title="editor.id ? '编辑检索策略' : '新建检索策略'"
      width="720px"
    >
      <el-form label-width="70px">
        <el-form-item label="名称" required>
          <el-input v-model="editor.name" maxlength="64" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="editor.description" maxlength="2000" />
        </el-form-item>
        <el-form-item label="配置">
          <el-input v-model="editor.json" type="textarea" :rows="18" class="json-input" />
          <el-button link type="primary" @click="resetJson">恢复为默认值</el-button>
        </el-form-item>
      </el-form>
      <pre v-if="editor.error" class="error">{{ editor.error }}</pre>
      <template #footer>
        <el-button @click="editor.visible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="editor.saving"
          :disabled="!editor.name.trim()"
          @click="saveEditor"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="检索日志详情" size="50%">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="查询" :span="2">{{ detail.query }}</el-descriptions-item>
          <el-descriptions-item label="规范化" :span="2">
            {{ detail.normalized_query }}
          </el-descriptions-item>
          <el-descriptions-item label="策略">{{ detail.profile_name }}</el-descriptions-item>
          <el-descriptions-item label="索引代">{{ detail.generation ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detail.user_id ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.total_ms }} ms</el-descriptions-item>
        </el-descriptions>
        <el-collapse :model-value="['stages']" class="raw">
          <el-collapse-item title="过滤条件" name="filters">
            <pre class="json">{{ JSON.stringify(detail.filters, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item title="耗时" name="timings">
            <pre class="json">{{ JSON.stringify(detail.timings, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item title="各阶段候选与分数" name="stages">
            <pre class="json">{{ JSON.stringify(detail.stages, null, 2) }}</pre>
          </el-collapse-item>
          <el-collapse-item title="策略配置" name="config">
            <pre class="json">{{ JSON.stringify(detail.config, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.hint {
  flex: 1;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.keyword {
  width: 260px;
}
.name {
  margin-right: 6px;
  font-weight: 500;
}
.name + .el-tag {
  margin-right: 4px;
}
.summary {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.pager {
  margin-top: 12px;
  justify-content: flex-end;
}
.json-input :deep(textarea),
.json,
.error {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.json,
.error {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 480px;
  overflow: auto;
}
.error {
  color: var(--el-color-danger);
  max-height: 200px;
}
.raw {
  margin-top: 16px;
}
</style>
