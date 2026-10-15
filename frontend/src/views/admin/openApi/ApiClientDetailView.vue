<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CopyDocument, Key, Search, WarningFilled } from '@element-plus/icons-vue'
import type { EChartsCoreOption } from 'echarts/core'
import {
  createApiKey,
  getApiClient,
  getApiUsage,
  listApiCallLogs,
  listApiKeys,
  previewApiClient,
  revokeApiKey,
  updateApiClient,
} from '@/api/openApi'
import type {
  ApiCallLog,
  ApiClient,
  ApiKey,
  ApiKeyCreated,
  ApiUsage,
  OpenRetrieveResult,
} from '@/api/types'
import EChart from '@/components/charts/EChart.vue'
import { formatDateTime } from '@/utils/format'
import ApiClientEditor from './ApiClientEditor.vue'
import { PRINCIPAL_LABEL, SCOPE_INFO, openApiBase } from './meta'

const props = defineProps<{ clientId: string }>()
const router = useRouter()

const client = ref<ApiClient | null>(null)
const loading = ref(false)
const tab = ref('usage')

async function loadClient(): Promise<void> {
  loading.value = true
  try {
    client.value = await getApiClient(props.clientId)
  } finally {
    loading.value = false
  }
}

const expired = computed(
  () => !!client.value?.expires_at && new Date(client.value.expires_at).getTime() <= Date.now(),
)

async function copy(text: string, label = '已复制'): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(label)
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

// ---- edit / status ----------------------------------------------------------------

const editorVisible = ref(false)

async function toggle(): Promise<void> {
  const c = client.value
  if (!c) return
  const disable = c.status === 'active'
  if (disable) {
    await ElMessageBox.confirm('停用后该应用的所有密钥将立即无法调用，确定停用吗？', '停用应用', {
      type: 'warning',
    }).catch(() => Promise.reject(new Error('cancelled')))
  }
  client.value = await updateApiClient(c.id, { status: disable ? 'disabled' : 'active' })
  ElMessage.success(disable ? '已停用' : '已启用')
}

// ---- usage ------------------------------------------------------------------------

const usage = ref<ApiUsage | null>(null)
const usageDays = ref(14)

async function loadUsage(): Promise<void> {
  usage.value = await getApiUsage(props.clientId, usageDays.value)
}

const usageStats = computed(() => {
  const u = usage.value
  if (!u) return null
  const withCalls = u.days.filter((d) => d.calls)
  const latency = withCalls.length
    ? withCalls.reduce((s, d) => s + d.avg_latency_ms * d.calls, 0) / u.total_calls
    : 0
  return {
    calls: u.total_calls,
    errors: u.total_errors,
    errorRate: u.total_calls ? ((u.total_errors / u.total_calls) * 100).toFixed(1) : '0.0',
    latency: Math.round(latency),
  }
})

const usageOption = computed<EChartsCoreOption>(() => {
  const days = usage.value?.days ?? []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['调用', '失败'], top: 0, right: 0 },
    grid: { left: 40, right: 16, top: 32, bottom: 24 },
    xAxis: { type: 'category', data: days.map((d) => d.day.slice(5)) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: '调用',
        type: 'bar',
        barMaxWidth: 18,
        itemStyle: { color: '#3370ff', borderRadius: [3, 3, 0, 0] },
        data: days.map((d) => d.calls),
      },
      {
        name: '失败',
        type: 'line',
        smooth: true,
        itemStyle: { color: '#f53f3f' },
        data: days.map((d) => d.errors),
      },
    ],
  }
})

const endpointRows = computed(() =>
  Object.entries(usage.value?.by_endpoint ?? {})
    .map(([endpoint, count]) => ({ endpoint, count }))
    .sort((a, b) => b.count - a.count),
)

// ---- keys -------------------------------------------------------------------------

const keys = ref<ApiKey[]>([])
const keysLoading = ref(false)
const keyDialog = reactive({ visible: false, name: '', expires_at: null as string | null })
const issuing = ref(false)
const issued = ref<ApiKeyCreated | null>(null)

async function loadKeys(): Promise<void> {
  keysLoading.value = true
  try {
    keys.value = await listApiKeys(props.clientId)
  } finally {
    keysLoading.value = false
  }
}

function openIssue(): void {
  keyDialog.name = `key-${new Date().toISOString().slice(0, 10)}`
  keyDialog.expires_at = null
  keyDialog.visible = true
}

async function issueKey(): Promise<void> {
  if (!keyDialog.name.trim()) {
    ElMessage.warning('请输入密钥名称')
    return
  }
  issuing.value = true
  try {
    issued.value = await createApiKey(props.clientId, {
      name: keyDialog.name.trim(),
      expires_at: keyDialog.expires_at,
    })
    keyDialog.visible = false
    await Promise.all([loadKeys(), loadClient()])
  } finally {
    issuing.value = false
  }
}

async function revoke(key: ApiKey): Promise<void> {
  await ElMessageBox.confirm(
    `吊销后使用「${key.name}」（${key.prefix}…）的调用将立即被拒绝，且不可恢复。`,
    '吊销密钥',
    { type: 'warning', confirmButtonText: '吊销', confirmButtonClass: 'el-button--danger' },
  )
  await revokeApiKey(props.clientId, key.id)
  ElMessage.success('已吊销')
  await Promise.all([loadKeys(), loadClient()])
}

function keyExpired(key: ApiKey): boolean {
  return !!key.expires_at && new Date(key.expires_at).getTime() <= Date.now()
}

// ---- logs -------------------------------------------------------------------------

const logs = ref<ApiCallLog[]>([])
const logTotal = ref(0)
const logQuery = reactive({ page: 1, size: 20, outcome: '' as '' | 'ok' | 'error' })
const logsLoading = ref(false)

async function loadLogs(): Promise<void> {
  logsLoading.value = true
  try {
    const page = await listApiCallLogs(props.clientId, {
      page: logQuery.page,
      size: logQuery.size,
      outcome: logQuery.outcome || undefined,
    })
    logs.value = page.items
    logTotal.value = page.total
  } finally {
    logsLoading.value = false
  }
}

function filterLogs(): void {
  logQuery.page = 1
  void loadLogs()
}

// ---- preview ----------------------------------------------------------------------

const preview = reactive({ query: '', kb_ids: [] as string[], top_k: 5 })
const previewing = ref(false)
const previewResult = ref<OpenRetrieveResult | null>(null)

async function runPreview(): Promise<void> {
  if (!preview.query.trim()) return
  previewing.value = true
  try {
    previewResult.value = await previewApiClient(props.clientId, {
      query: preview.query.trim(),
      kb_ids: preview.kb_ids,
      top_k: preview.top_k,
    })
  } finally {
    previewing.value = false
  }
}

// ---- guide ------------------------------------------------------------------------

const base = openApiBase()
const guide = computed(() => {
  const kb = client.value?.kbs[0]?.id ?? '<KB_ID>'
  return {
    retrieve: [
      `curl -X POST '${base}/retrieve' \\`,
      `  -H 'X-API-Key: <YOUR_API_KEY>' \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -d '{"query": "差旅住宿标准是多少？", "kb_ids": ["${kb}"], "top_k": 5}'`,
    ].join('\n'),
    chat: [
      `curl -N -X POST '${base}/chat' \\`,
      `  -H 'Authorization: Bearer <YOUR_API_KEY>' \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -d '{"question": "年假怎么申请？", "stream": true}'`,
    ].join('\n'),
    mcp: JSON.stringify(
      {
        mcpServers: {
          'enterprise-kb': {
            type: 'streamable-http',
            url: `${base}/mcp`,
            headers: { 'X-API-Key': '<YOUR_API_KEY>' },
          },
        },
      },
      null,
      2,
    ),
  }
})

// ---- lifecycle --------------------------------------------------------------------

const loaded = new Set<string>()

function loadTab(name: string): void {
  if (loaded.has(name)) return
  loaded.add(name)
  if (name === 'usage') void loadUsage()
  else if (name === 'keys') void loadKeys()
  else if (name === 'logs') void loadLogs()
}

watch(tab, loadTab)
watch(usageDays, () => void loadUsage())

onMounted(async () => {
  await loadClient()
  loadTab(tab.value)
})
</script>

<template>
  <div v-loading="loading" class="detail">
    <template v-if="client">
      <div class="hero">
        <button type="button" class="back" @click="router.push({ name: 'admin-open-api' })">
          <el-icon><ArrowLeft /></el-icon>
        </button>
        <div class="hero__icon">
          <el-icon><Key /></el-icon>
        </div>
        <div class="hero__main">
          <div class="hero__title">
            {{ client.name }}
            <span v-if="expired" class="badge badge--off">已过期</span>
            <span v-else-if="client.status === 'active'" class="badge badge--on">启用中</span>
            <span v-else class="badge badge--off">已停用</span>
          </div>
          <div class="hero__meta">
            <span>{{ client.owner_department_name ?? '未指定部门' }}</span>
            <span v-if="client.contact">联系人：{{ client.contact }}</span>
            <span class="mono">ID：{{ client.id }}</span>
            <span>创建于 {{ formatDateTime(client.created_at) }}</span>
          </div>
        </div>
        <div class="hero__actions">
          <el-button @click="editorVisible = true">编辑授权</el-button>
          <el-button
            :type="client.status === 'active' ? 'danger' : 'primary'"
            plain
            @click="toggle().catch(() => undefined)"
          >
            {{ client.status === 'active' ? '停用' : '启用' }}
          </el-button>
        </div>
      </div>

      <div class="grid">
        <div class="panel">
          <div class="panel__label">授权知识库（上限）</div>
          <div class="panel__value">
            <el-tag v-for="kb in client.kbs" :key="kb.id" effect="plain" class="tag">
              {{ kb.name }}
            </el-tag>
          </div>
        </div>
        <div class="panel">
          <div class="panel__label">代理身份（文档权限按此过滤）</div>
          <div class="panel__value">
            <el-tag
              v-for="p in client.principals"
              :key="p.type + p.id"
              type="info"
              effect="plain"
              class="tag"
            >
              {{ PRINCIPAL_LABEL[p.type] }} · {{ p.name ?? p.id }}
            </el-tag>
          </div>
        </div>
        <div class="panel">
          <div class="panel__label">开通能力</div>
          <div class="panel__value">
            <el-tag v-for="s in client.scopes" :key="s" type="success" class="tag">
              {{ SCOPE_INFO[s].label }}
            </el-tag>
          </div>
        </div>
        <div class="panel">
          <div class="panel__label">安全与配额</div>
          <div class="panel__value small">
            <div>
              限流 {{ client.effective_rate_per_minute }} 次/分钟
              <span v-if="!client.rate_limit_per_minute" class="muted">（默认）</span>
            </div>
            <div>每日配额 {{ client.daily_quota || '不限' }}</div>
            <div>
              IP 白名单
              {{ client.ip_allowlist.length ? client.ip_allowlist.join('，') : '不限' }}
            </div>
            <div>有效期至 {{ client.expires_at ? formatDateTime(client.expires_at) : '长期' }}</div>
          </div>
        </div>
      </div>

      <el-card shadow="never" class="tabs-card">
        <el-tabs v-model="tab">
          <el-tab-pane label="调用概览" name="usage">
            <div class="usage-toolbar">
              <el-radio-group v-model="usageDays" size="small">
                <el-radio-button :value="7">近 7 天</el-radio-button>
                <el-radio-button :value="14">近 14 天</el-radio-button>
                <el-radio-button :value="30">近 30 天</el-radio-button>
              </el-radio-group>
            </div>
            <div v-if="usageStats" class="stats">
              <div class="stat">
                <div class="stat__label">调用次数</div>
                <div class="stat__value">{{ usageStats.calls }}</div>
              </div>
              <div class="stat">
                <div class="stat__label">失败次数</div>
                <div class="stat__value">{{ usageStats.errors }}</div>
              </div>
              <div class="stat">
                <div class="stat__label">失败率</div>
                <div class="stat__value">{{ usageStats.errorRate }}<small>%</small></div>
              </div>
              <div class="stat">
                <div class="stat__label">平均耗时</div>
                <div class="stat__value">{{ usageStats.latency }}<small>ms</small></div>
              </div>
            </div>
            <div class="usage-body">
              <EChart :option="usageOption" height="260px" class="usage-chart" />
              <div class="usage-side">
                <div class="panel__label">接口分布</div>
                <div v-if="!endpointRows.length" class="muted small">暂无调用</div>
                <div v-for="row in endpointRows" :key="row.endpoint" class="endpoint">
                  <span class="mono">{{ row.endpoint }}</span>
                  <span>{{ row.count }}</span>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="密钥管理" name="keys">
            <div class="tab-toolbar">
              <span class="muted small">
                密钥只在签发时显示一次，平台仅保存其哈希；泄露时请立即吊销并重新签发。
              </span>
              <el-button type="primary" :icon="Key" data-test="issue-key" @click="openIssue">
                签发密钥
              </el-button>
            </div>
            <el-table v-loading="keysLoading" :data="keys" empty-text="尚未签发密钥">
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column label="密钥" min-width="150">
                <template #default="{ row }">
                  <span class="mono">{{ row.prefix }}••••••••</span>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag v-if="row.status === 'revoked'" type="info" size="small">已吊销</el-tag>
                  <el-tag v-else-if="keyExpired(row as ApiKey)" type="warning" size="small">
                    已过期
                  </el-tag>
                  <el-tag v-else type="success" size="small">有效</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="过期时间" width="160">
                <template #default="{ row }">
                  {{ row.expires_at ? formatDateTime(row.expires_at) : '长期' }}
                </template>
              </el-table-column>
              <el-table-column label="最近使用" min-width="190">
                <template #default="{ row }">
                  <template v-if="row.last_used_at">
                    {{ formatDateTime(row.last_used_at) }}
                    <span class="muted small">{{ row.last_used_ip }}</span>
                  </template>
                  <span v-else class="muted">从未使用</span>
                </template>
              </el-table-column>
              <el-table-column label="签发时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="row.status === 'active'"
                    link
                    type="danger"
                    @click="revoke(row as ApiKey).catch(() => undefined)"
                  >
                    吊销
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="调用日志" name="logs">
            <div class="tab-toolbar">
              <el-radio-group v-model="logQuery.outcome" size="small" @change="filterLogs">
                <el-radio-button value="">全部</el-radio-button>
                <el-radio-button value="ok">成功</el-radio-button>
                <el-radio-button value="error">失败</el-radio-button>
              </el-radio-group>
              <el-button size="small" @click="loadLogs">刷新</el-button>
            </div>
            <el-table v-loading="logsLoading" :data="logs" empty-text="暂无调用记录">
              <el-table-column label="时间" width="160">
                <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column label="接口" width="150">
                <template #default="{ row }"
                  ><span class="mono">{{ row.endpoint }}</span></template
                >
              </el-table-column>
              <el-table-column label="状态" width="150">
                <template #default="{ row }">
                  <el-tag :type="row.status_code < 400 ? 'success' : 'danger'" size="small">
                    {{ row.status_code }}
                  </el-tag>
                  <span v-if="row.error_code" class="muted small"> {{ row.error_code }}</span>
                </template>
              </el-table-column>
              <el-table-column label="查询内容" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.query ?? '—' }}</template>
              </el-table-column>
              <el-table-column label="结果数" width="80" align="right" prop="result_count" />
              <el-table-column label="耗时" width="90" align="right">
                <template #default="{ row }">{{ row.latency_ms }} ms</template>
              </el-table-column>
              <el-table-column label="来源 IP" width="130" prop="ip" />
              <el-table-column label="Trace" width="110">
                <template #default="{ row }">
                  <el-button
                    v-if="row.trace_id"
                    link
                    type="primary"
                    size="small"
                    @click="copy(row.trace_id as string, '已复制 trace_id')"
                  >
                    复制
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
            <el-pagination
              v-model:current-page="logQuery.page"
              v-model:page-size="logQuery.size"
              class="pager"
              layout="total, sizes, prev, pager, next"
              :total="logTotal"
              @current-change="loadLogs"
              @size-change="filterLogs"
            />
          </el-tab-pane>

          <el-tab-pane label="授权预览" name="preview">
            <el-alert
              type="info"
              show-icon
              :closable="false"
              title="以该应用的身份与授权执行一次检索（不计入调用量），用于确认它能看到什么、看不到什么。"
              class="preview-tip"
            />
            <el-form class="preview-form" @submit.prevent="runPreview">
              <el-input
                v-model="preview.query"
                placeholder="输入一个问题，例如：差旅住宿标准"
                :prefix-icon="Search"
                clearable
                data-test="preview-query"
              />
              <el-select
                v-model="preview.kb_ids"
                multiple
                collapse-tags
                clearable
                placeholder="全部授权知识库"
                class="preview-kb"
              >
                <el-option v-for="kb in client.kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
              </el-select>
              <el-input-number v-model="preview.top_k" :min="1" :max="20" />
              <el-button type="primary" native-type="submit" :loading="previewing">检索</el-button>
            </el-form>
            <template v-if="previewResult">
              <div class="muted small preview-summary">
                命中 {{ previewResult.total }} 条 · 耗时 {{ Math.round(previewResult.took_ms) }} ms
              </div>
              <el-empty
                v-if="!previewResult.items.length"
                :image-size="64"
                description="该应用在授权范围内没有可见的相关内容"
              />
              <div v-for="item in previewResult.items" :key="item.chunk_id" class="hit">
                <div class="hit__head">
                  <span class="hit__rank">{{ item.rank }}</span>
                  <span class="hit__title">{{ item.title }}</span>
                  <el-tag size="small" effect="plain">{{ item.kb_name }}</el-tag>
                  <span v-if="item.score !== null" class="muted small">
                    相关度 {{ item.score.toFixed(3) }}
                  </span>
                </div>
                <div v-if="item.heading_path.length" class="muted small">
                  {{ item.heading_path.join(' › ') }}
                </div>
                <div class="hit__content">{{ item.content }}</div>
              </div>
            </template>
          </el-tab-pane>

          <el-tab-pane label="接入指南" name="guide">
            <div class="guide">
              <div class="guide__row">
                <span class="panel__label">接口地址</span>
                <code class="mono">{{ base }}</code>
                <el-button link :icon="CopyDocument" @click="copy(base)">复制</el-button>
              </div>
              <p class="muted small">
                认证：请求头 <code>X-API-Key: ekb_sk_…</code> 或
                <code>Authorization: Bearer ekb_sk_…</code>。调用
                <code>GET /whoami</code> 可查看当前密钥的授权范围。
              </p>
              <div v-for="(code, name) in guide" :key="name" class="snippet">
                <div class="snippet__head">
                  <span>
                    {{
                      name === 'retrieve'
                        ? '检索'
                        : name === 'chat'
                          ? '问答（流式 SSE）'
                          : 'MCP 客户端配置'
                    }}
                  </span>
                  <el-button link size="small" :icon="CopyDocument" @click="copy(code)">
                    复制
                  </el-button>
                </div>
                <pre class="snippet__code">{{ code }}</pre>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>

      <ApiClientEditor v-model="editorVisible" :client="client" @saved="(c) => (client = c)" />
    </template>

    <el-dialog v-model="keyDialog.visible" title="签发密钥" width="460px">
      <el-form label-position="top">
        <el-form-item label="密钥名称">
          <el-input v-model="keyDialog.name" maxlength="128" placeholder="如：prod / test" />
        </el-form-item>
        <el-form-item label="过期时间">
          <el-date-picker
            v-model="keyDialog.expires_at"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ssZ"
            placeholder="留空表示长期有效"
            clearable
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="keyDialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="issuing" data-test="confirm-issue" @click="issueKey">
          签发
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      :model-value="!!issued"
      title="密钥已签发"
      width="560px"
      :close-on-click-modal="false"
      @update:model-value="issued = null"
    >
      <div class="secret-warn">
        <el-icon><WarningFilled /></el-icon>
        请立即复制并妥善保存。关闭此窗口后将无法再次查看完整密钥。
      </div>
      <div class="secret">
        <code class="mono" data-test="issued-secret">{{ issued?.secret }}</code>
        <el-button type="primary" :icon="CopyDocument" @click="copy(issued?.secret ?? '')">
          复制
        </el-button>
      </div>
      <template #footer>
        <el-button type="primary" @click="issued = null">我已保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.detail {
  min-height: 300px;
}
.hero {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 20px;
  background: var(--ekb-bg-panel);
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius-lg);
}
.back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  color: var(--ekb-text-2);
  background: transparent;
  border: 1px solid var(--ekb-border);
  border-radius: var(--ekb-radius-sm);
  cursor: pointer;
}
.back:hover {
  color: var(--ekb-primary);
  border-color: var(--el-color-primary-light-5);
}
.hero__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  font-size: 22px;
  color: #fff;
  background: var(--ekb-gradient);
  border-radius: 12px;
}
.hero__main {
  flex: 1;
  min-width: 0;
}
.hero__title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 600;
}
.hero__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.badge {
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 10px;
}
.badge--on {
  color: var(--ekb-success-text);
  background: var(--ekb-success-bg);
}
.badge--off {
  color: var(--ekb-text-3);
  background: var(--ekb-bg-hover);
}
.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.panel {
  padding: 14px 16px;
  background: var(--ekb-bg-panel);
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius-lg);
}
.panel__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.panel__value {
  line-height: 1.8;
}
.small {
  font-size: 12px;
}
.tag {
  margin: 0 6px 6px 0;
}
.tabs-card :deep(.el-tabs__header) {
  margin-bottom: 16px;
}
.usage-toolbar,
.tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}
.usage-toolbar {
  justify-content: flex-end;
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat {
  padding: 12px 16px;
  background: var(--ekb-primary-softer);
  border-radius: var(--ekb-radius);
}
.stat__label {
  font-size: 12px;
  color: var(--ekb-text-3);
}
.stat__value {
  margin-top: 4px;
  font-size: 22px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.stat__value small {
  margin-left: 2px;
  font-size: 12px;
  font-weight: 400;
  color: var(--ekb-text-3);
}
.usage-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 240px;
  gap: 16px;
}
.usage-side {
  padding-left: 16px;
  border-left: 1px solid var(--ekb-border-soft);
}
.endpoint {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px dashed var(--ekb-border-soft);
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
.preview-tip {
  margin-bottom: 12px;
}
.preview-form {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.preview-kb {
  width: 260px;
  flex: none;
}
.preview-summary {
  margin-bottom: 8px;
}
.hit {
  padding: 12px 14px;
  margin-bottom: 8px;
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius);
}
.hit__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.hit__rank {
  width: 20px;
  height: 20px;
  font-size: 12px;
  line-height: 20px;
  text-align: center;
  color: var(--ekb-primary);
  background: var(--ekb-primary-soft);
  border-radius: 4px;
}
.hit__title {
  font-weight: 600;
}
.hit__content {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ekb-text-2);
  white-space: pre-wrap;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.guide__row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.guide__row .panel__label {
  margin: 0;
}
.snippet {
  margin-top: 14px;
  overflow: hidden;
  border: 1px solid var(--ekb-border);
  border-radius: var(--ekb-radius);
}
.snippet__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 500;
  background: var(--ekb-bg-fill);
}
.snippet__code {
  margin: 0;
  padding: 12px 14px;
  overflow: auto;
  font-size: 12.5px;
  line-height: 1.6;
  background: var(--ekb-bg-subtle);
}
.secret-warn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ekb-warning-text);
  background: var(--ekb-warning-bg);
  border-radius: var(--ekb-radius);
}
.secret {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--ekb-bg-fill);
  border-radius: var(--ekb-radius);
}
.secret code {
  flex: 1;
  word-break: break-all;
  font-size: 13px;
}
@media (max-width: 1200px) {
  .grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
