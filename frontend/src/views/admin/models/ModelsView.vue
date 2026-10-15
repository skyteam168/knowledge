<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { HttpError } from '@/api/http'
import {
  checkModel,
  createModel,
  createModelProvider,
  deleteModel,
  deleteModelProvider,
  getModelOverview,
  listModelProviders,
  listModels,
  saveModelRoutes,
  syncProviderModels,
  updateModel,
  updateModelProvider,
} from '@/api/models'
import type {
  ModelCheckFailure,
  ModelItem,
  ModelKind,
  ModelOverview,
  ModelProvider,
  ModelScene,
  ModelSceneInfo,
} from '@/api/types'
import { formatDateTime } from '@/utils/format'

type Tab = 'routes' | 'models' | 'providers'
type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const SCENE_LABELS: Record<ModelScene, string> = {
  chat: '对话',
  chat_fallback: '备用对话',
  embedding: '向量（Embedding）',
  rerank: '重排（Rerank）',
}
const KIND_LABELS: Record<ModelKind, string> = {
  chat: '对话',
  embedding: '向量',
  rerank: '重排',
}
const SOURCE_LABELS: Record<ModelSceneInfo['source'], { label: string; type: TagType }> = {
  page: { label: '页面配置', type: 'success' },
  config: { label: '部署配置', type: 'info' },
  index: { label: '随索引固定', type: 'warning' },
}

const tab = ref<Tab>('routes')
const providers = ref<ModelProvider[]>([])
const modelTotal = ref(0)

// ---- checks -----------------------------------------------------------------------

const checking = ref<Record<string, boolean>>({})

async function runCheck(modelId: string, name: string): Promise<void> {
  checking.value[modelId] = true
  try {
    const r = await checkModel(modelId)
    if (r.ok) {
      const parts = [`${name} 可用，耗时 ${r.latency_ms} ms`]
      if (r.first_token_ms !== null) parts.push(`首字 ${r.first_token_ms} ms`)
      if (r.sample) parts.push(`返回：${r.sample}`)
      ElMessage.success({ message: parts.join('，'), duration: 5000 })
      if (r.warning) ElMessage.warning({ message: r.warning, duration: 8000 })
    } else {
      ElMessage.error({ message: `${name} 不可用：${r.message}`, duration: 8000 })
    }
    await Promise.all([loadOverview(), loadModels()])
  } finally {
    checking.value[modelId] = false
  }
}

function checkTag(status: string | null): { label: string; type: TagType } {
  if (status === 'ok') return { label: '正常', type: 'success' }
  if (status === 'error') return { label: '异常', type: 'danger' }
  return { label: '未检测', type: 'info' }
}

// ---- scene routing ----------------------------------------------------------------

const overview = ref<ModelOverview | null>(null)
const chatOptions = ref<ModelItem[]>([])
const routeForm = reactive({ chat: '' as string, fallback: '' as string })
const savingRoutes = ref(false)

async function loadOverview(): Promise<void> {
  overview.value = await getModelOverview()
}

async function loadChatOptions(): Promise<void> {
  const page = await listModels({ kind: 'chat', size: 200 })
  chatOptions.value = page.items.filter((m) => m.provider_enabled)
}

function resetRouteForm(): void {
  const scenes = overview.value?.scenes ?? []
  const page = scenes.find((s) => s.scene === 'chat')?.source === 'page'
  routeForm.chat = page ? (scenes.find((s) => s.scene === 'chat')?.model_id ?? '') : ''
  routeForm.fallback = page ? (scenes.find((s) => s.scene === 'chat_fallback')?.model_id ?? '') : ''
}

function optionLabel(m: ModelItem): string {
  return `${m.name}（${m.provider_name}）`
}

async function submitRoutes(chatId: string | null, fallbackId: string | null, force = false) {
  savingRoutes.value = true
  try {
    overview.value = await saveModelRoutes({
      chat_model_id: chatId,
      chat_fallback_model_id: fallbackId,
      force,
    })
    resetRouteForm()
    ElMessage.success(
      chatId
        ? `已切换，当前服务立即生效，其他服务 ${overview.value.refresh_seconds} 秒内生效`
        : '已恢复为部署配置',
    )
    await loadModels()
  } catch (e) {
    if (e instanceof HttpError && e.code === 'MODEL_CHECK_FAILED') {
      const failures = (e.detail as ModelCheckFailure[]) ?? []
      const text = failures
        .map((f) => `${SCENE_LABELS[f.scene]}「${f.model}」：${f.message}`)
        .join('\n')
      await loadModels()
      try {
        await ElMessageBox.confirm(
          `${text}\n\n模型检测未通过，强制切换可能导致 AI 助手无法回答。仍要切换吗？`,
          '模型检测未通过',
          { type: 'warning', confirmButtonText: '仍然切换', cancelButtonText: '取消' },
        )
      } catch {
        return
      }
      await submitRoutes(chatId, fallbackId, true)
    } else if (e instanceof HttpError) {
      ElMessage.error(e.message)
    } else {
      throw e
    }
  } finally {
    savingRoutes.value = false
  }
}

async function saveRoutes(): Promise<void> {
  if (!routeForm.chat) {
    ElMessage.warning('请选择对话模型')
    return
  }
  await submitRoutes(routeForm.chat, routeForm.fallback || null)
}

async function resetRoutes(): Promise<void> {
  await ElMessageBox.confirm(
    '恢复后对话将使用部署配置（deploy/.env）中的模型，确定吗？',
    '恢复为部署配置',
    { type: 'warning' },
  )
  await submitRoutes(null, null)
}

const pageRouting = computed(
  () => overview.value?.scenes.find((s) => s.scene === 'chat')?.source === 'page',
)

// ---- models -----------------------------------------------------------------------

const models = ref<ModelItem[]>([])
const modelFilters = reactive({ provider_id: '', kind: '' as ModelKind | '', keyword: '' })
const modelPager = reactive({ page: 1, size: 20 })
const loadingModels = ref(false)

async function loadModels(): Promise<void> {
  loadingModels.value = true
  try {
    const page = await listModels({
      provider_id: modelFilters.provider_id || undefined,
      kind: modelFilters.kind || undefined,
      keyword: modelFilters.keyword || undefined,
      ...modelPager,
    })
    models.value = page.items
    if (!modelFilters.provider_id && !modelFilters.kind && !modelFilters.keyword) {
      modelTotal.value = page.total
    }
    modelPagerTotal.value = page.total
  } finally {
    loadingModels.value = false
  }
  await loadChatOptions()
}

const modelPagerTotal = ref(0)

function searchModels(): void {
  modelPager.page = 1
  void loadModels()
}

const modelEditor = reactive({
  visible: false,
  saving: false,
  id: null as string | null,
  provider_id: '',
  name: '',
  kind: 'chat' as ModelKind,
  base_url: '',
  path: '',
  inUse: false,
})

function openModelEditor(model?: ModelItem): void {
  modelEditor.id = model?.id ?? null
  modelEditor.provider_id = model?.provider_id ?? providers.value[0]?.id ?? ''
  modelEditor.name = model?.name ?? ''
  modelEditor.kind = model?.kind ?? 'chat'
  modelEditor.base_url = model?.base_url ?? ''
  modelEditor.path = model?.path ?? ''
  modelEditor.inUse = (model?.scenes.length ?? 0) > 0
  modelEditor.visible = true
}

async function saveModel(): Promise<void> {
  modelEditor.saving = true
  try {
    const common = {
      kind: modelEditor.kind,
      base_url: modelEditor.base_url.trim() || null,
      path: modelEditor.path.trim() || null,
    }
    if (modelEditor.id) {
      await updateModel(modelEditor.id, common)
    } else {
      await createModel({
        ...common,
        provider_id: modelEditor.provider_id,
        name: modelEditor.name.trim(),
      })
    }
    ElMessage.success('已保存')
    modelEditor.visible = false
    await Promise.all([loadModels(), loadProviders(), loadOverview()])
  } finally {
    modelEditor.saving = false
  }
}

async function removeModel(model: ModelItem): Promise<void> {
  await ElMessageBox.confirm(`确定删除模型「${model.name}」？`, '删除', { type: 'warning' })
  await deleteModel(model.id)
  ElMessage.success('已删除')
  await Promise.all([loadModels(), loadProviders()])
}

// ---- providers --------------------------------------------------------------------

const loadingProviders = ref(false)
const syncing = ref<Record<string, boolean>>({})

async function loadProviders(): Promise<void> {
  loadingProviders.value = true
  try {
    providers.value = await listModelProviders()
  } finally {
    loadingProviders.value = false
  }
}

const providerEditor = reactive({
  visible: false,
  saving: false,
  id: null as string | null,
  name: '',
  base_url: '',
  api_key: '',
  clear_api_key: false,
  hint: null as string | null,
})

function openProviderEditor(provider?: ModelProvider): void {
  providerEditor.id = provider?.id ?? null
  providerEditor.name = provider?.name ?? ''
  providerEditor.base_url = provider?.base_url ?? ''
  providerEditor.api_key = ''
  providerEditor.clear_api_key = false
  providerEditor.hint = provider?.api_key_hint ?? null
  providerEditor.visible = true
}

async function saveProvider(): Promise<void> {
  providerEditor.saving = true
  try {
    const body = {
      name: providerEditor.name.trim(),
      base_url: providerEditor.base_url.trim(),
      api_key: providerEditor.api_key.trim() || null,
    }
    if (providerEditor.id) {
      await updateModelProvider(providerEditor.id, {
        ...body,
        clear_api_key: providerEditor.clear_api_key,
      })
    } else {
      await createModelProvider(body)
    }
    ElMessage.success('已保存')
    providerEditor.visible = false
    await Promise.all([loadProviders(), loadModels(), loadOverview()])
  } finally {
    providerEditor.saving = false
  }
}

async function toggleProvider(provider: ModelProvider, enabled: boolean): Promise<void> {
  try {
    await updateModelProvider(provider.id, { enabled })
    ElMessage.success(enabled ? '已启用' : '已停用')
  } finally {
    await Promise.all([loadProviders(), loadModels()])
  }
}

async function syncProvider(provider: ModelProvider): Promise<void> {
  syncing.value[provider.id] = true
  try {
    const r = await syncProviderModels(provider.id)
    const extra = r.missing.length ? `，${r.missing.length} 个已不在列表中` : ''
    ElMessage.success(`共列出 ${r.listed} 个模型，新增 ${r.added} 个${extra}`)
    await Promise.all([loadProviders(), loadModels()])
  } finally {
    syncing.value[provider.id] = false
  }
}

async function removeProvider(provider: ModelProvider): Promise<void> {
  await ElMessageBox.confirm(
    `确定删除提供方「${provider.name}」及其 ${provider.model_count} 个模型？`,
    '删除',
    { type: 'warning' },
  )
  await deleteModelProvider(provider.id)
  ElMessage.success('已删除')
  await Promise.all([loadProviders(), loadModels()])
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadProviders(), loadModels()])
  resetRouteForm()
})
</script>

<template>
  <el-card shadow="never" class="models">
    <el-tabs v-model="tab">
      <el-tab-pane label="场景路由" name="routes">
        <el-table :data="overview?.scenes ?? []" size="small" class="scenes">
          <el-table-column label="场景" width="150">
            <template #default="{ row }">{{ SCENE_LABELS[row.scene as ModelScene] }}</template>
          </el-table-column>
          <el-table-column label="当前模型" min-width="180">
            <template #default="{ row }">
              <span v-if="row.model" class="mono">{{ row.model }}</span>
              <el-text v-else type="info">未设置</el-text>
              <div v-if="row.dim" class="sub">{{ row.dim }} 维</div>
            </template>
          </el-table-column>
          <el-table-column label="接口地址" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.base_url ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="110">
            <template #default="{ row }">
              <el-tag
                :type="SOURCE_LABELS[row.source as ModelSceneInfo['source']].type"
                size="small"
              >
                {{ SOURCE_LABELS[row.source as ModelSceneInfo['source']].label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="checkTag(row.last_check_status).type" size="small">
                {{ checkTag(row.last_check_status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="说明" min-width="220">
            <template #default="{ row }">
              <span class="sub">{{ row.note ?? (row.editable ? '可在下方切换' : '') }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.model_id"
                link
                type="primary"
                :loading="checking[row.model_id]"
                @click="runCheck(row.model_id, row.model)"
              >
                检测
              </el-button>
              <el-tooltip v-else-if="row.model" content="该模型不在模型列表中，请先同步或添加">
                <el-text type="info" size="small">无法检测</el-text>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>

        <el-card shadow="never" header="切换对话模型" class="route-form">
          <el-form label-width="110px" @submit.prevent="saveRoutes">
            <el-form-item label="对话模型" required>
              <el-select
                v-model="routeForm.chat"
                filterable
                placeholder="选择类型为「对话」的模型"
                style="width: 420px"
              >
                <el-option
                  v-for="m in chatOptions"
                  :key="m.id"
                  :label="optionLabel(m)"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="备用对话模型">
              <el-select
                v-model="routeForm.fallback"
                filterable
                clearable
                placeholder="可选：主模型失败时自动改用"
                style="width: 420px"
              >
                <el-option
                  v-for="m in chatOptions.filter((o) => o.id !== routeForm.chat)"
                  :key="m.id"
                  :label="optionLabel(m)"
                  :value="m.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="savingRoutes">
                检测并切换
              </el-button>
              <el-button v-if="pageRouting" :disabled="savingRoutes" @click="resetRoutes">
                恢复为部署配置
              </el-button>
            </el-form-item>
          </el-form>
          <div class="sub">
            保存前会自动检测所选模型，检测通过才会切换；切换后当前服务立即生效，其他服务在
            {{ overview?.refresh_seconds ?? 5 }}
            秒内生效，无需重启。向量与重排模型关系到已建索引和检索质量，此处只读。
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="`模型 (${modelTotal})`" name="models">
        <div class="toolbar">
          <el-form :inline="true" @submit.prevent="searchModels">
            <el-form-item>
              <el-select
                v-model="modelFilters.provider_id"
                clearable
                placeholder="全部提供方"
                style="width: 180px"
                @change="searchModels"
              >
                <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-select
                v-model="modelFilters.kind"
                clearable
                placeholder="全部类型"
                style="width: 120px"
                @change="searchModels"
              >
                <el-option
                  v-for="(label, kind) in KIND_LABELS"
                  :key="kind"
                  :label="label"
                  :value="kind"
                />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-input
                v-model="modelFilters.keyword"
                clearable
                placeholder="模型名称"
                style="width: 200px"
                @clear="searchModels"
              />
            </el-form-item>
            <el-form-item>
              <el-button native-type="submit">查询</el-button>
            </el-form-item>
          </el-form>
          <el-button
            type="primary"
            :icon="Plus"
            :disabled="!providers.length"
            @click="openModelEditor()"
          >
            添加模型
          </el-button>
        </div>
        <el-table v-loading="loadingModels" :data="models" size="small" empty-text="暂无模型">
          <el-table-column label="模型" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.name }}</span>
              <el-tag v-for="s in row.scenes" :key="s" size="small" type="success" class="tag">
                {{ SCENE_LABELS[s as ModelScene] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ KIND_LABELS[row.kind as ModelKind] }}</template>
          </el-table-column>
          <el-table-column prop="provider_name" label="提供方" width="160" show-overflow-tooltip />
          <el-table-column label="接口地址" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.effective_base_url }}{{ row.path ?? '' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="来源" width="80">
            <template #default="{ row }">{{ row.origin === 'synced' ? '同步' : '手动' }}</template>
          </el-table-column>
          <el-table-column label="最近检测" width="200">
            <template #default="{ row }">
              <el-tooltip
                :disabled="!row.last_check_message"
                :content="row.last_check_message ?? ''"
                placement="top"
              >
                <el-tag :type="checkTag(row.last_check_status).type" size="small">
                  {{ checkTag(row.last_check_status).label }}
                </el-tag>
              </el-tooltip>
              <span v-if="row.last_check_at" class="sub check-meta">
                {{ row.last_check_latency_ms }} ms · {{ formatDateTime(row.last_check_at) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="checking[row.id]"
                @click="runCheck(row.id, row.name)"
              >
                检测
              </el-button>
              <el-button link type="primary" @click="openModelEditor(row as ModelItem)"
                >编辑</el-button
              >
              <el-button
                link
                type="danger"
                :disabled="row.scenes.length > 0"
                @click="removeModel(row as ModelItem)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="modelPager.page"
          v-model:page-size="modelPager.size"
          :total="modelPagerTotal"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          class="pager"
          @current-change="loadModels"
          @size-change="searchModels"
        />
      </el-tab-pane>

      <el-tab-pane :label="`提供方 (${providers.length})`" name="providers">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="openProviderEditor()"
            >添加提供方</el-button
          >
          <span class="sub">内部推理服务、阿里云百炼等，统一按 OpenAI 兼容接口访问</span>
        </div>
        <el-table
          v-loading="loadingProviders"
          :data="providers"
          size="small"
          empty-text="暂无提供方"
        >
          <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip />
          <el-table-column label="接口地址" min-width="280" show-overflow-tooltip>
            <template #default="{ row }"
              ><span class="mono">{{ row.base_url }}</span></template
            >
          </el-table-column>
          <el-table-column label="密钥" width="130">
            <template #default="{ row }">
              <span class="mono sub">{{ row.has_api_key ? row.api_key_hint : '未设置' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="model_count" label="模型数" width="80" />
          <el-table-column label="来源" width="90">
            <template #default="{ row }">{{
              row.source === 'env' ? '部署配置' : '手动添加'
            }}</template>
          </el-table-column>
          <el-table-column label="添加时间" width="160">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="启用" width="80">
            <template #default="{ row }">
              <el-tooltip :disabled="!row.in_use" content="正在用于对话，不能停用">
                <el-switch
                  :model-value="row.enabled"
                  :disabled="row.in_use && row.enabled"
                  @change="
                    (v: string | number | boolean) =>
                      toggleProvider(row as ModelProvider, Boolean(v))
                  "
                />
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="syncing[row.id]"
                @click="syncProvider(row as ModelProvider)"
              >
                同步模型
              </el-button>
              <el-button link type="primary" @click="openProviderEditor(row as ModelProvider)"
                >编辑</el-button
              >
              <el-button
                link
                type="danger"
                :disabled="row.in_use"
                @click="removeProvider(row as ModelProvider)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="providerEditor.visible"
      :title="providerEditor.id ? '编辑提供方' : '添加提供方'"
      width="560px"
    >
      <el-form label-width="90px" @submit.prevent="saveProvider">
        <el-form-item label="名称" required>
          <el-input v-model="providerEditor.name" maxlength="128" placeholder="例如：阿里云百炼" />
        </el-form-item>
        <el-form-item label="接口地址" required>
          <el-input
            v-model="providerEditor.base_url"
            placeholder="https://.../compatible-mode/v1"
          />
        </el-form-item>
        <el-form-item label="密钥">
          <el-input
            v-model="providerEditor.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="
              providerEditor.id
                ? `留空则不修改${providerEditor.hint ? `（当前 ${providerEditor.hint}）` : ''}`
                : 'sk-...'
            "
            :disabled="providerEditor.clear_api_key"
          />
        </el-form-item>
        <el-form-item v-if="providerEditor.id && providerEditor.hint">
          <el-checkbox v-model="providerEditor.clear_api_key">清除已保存的密钥</el-checkbox>
        </el-form-item>
        <div class="sub">密钥加密保存，任何接口都不会返回明文。</div>
      </el-form>
      <template #footer>
        <el-button @click="providerEditor.visible = false">取消</el-button>
        <el-button type="primary" :loading="providerEditor.saving" @click="saveProvider">
          保存
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="modelEditor.visible"
      :title="modelEditor.id ? '编辑模型' : '添加模型'"
      width="560px"
    >
      <el-form label-width="90px" @submit.prevent="saveModel">
        <el-form-item label="提供方" required>
          <el-select
            v-model="modelEditor.provider_id"
            :disabled="!!modelEditor.id"
            style="width: 100%"
          >
            <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称" required>
          <el-input
            v-model="modelEditor.name"
            :disabled="!!modelEditor.id"
            placeholder="与接口中的 model 字段一致，例如 qwen3-rerank"
          />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-radio-group v-model="modelEditor.kind" :disabled="modelEditor.inUse">
            <el-radio-button v-for="(label, kind) in KIND_LABELS" :key="kind" :value="kind">
              {{ label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="独立地址">
          <el-input v-model="modelEditor.base_url" placeholder="可选：与提供方地址不同时填写" />
        </el-form-item>
        <el-form-item v-if="modelEditor.kind === 'rerank'" label="接口路径">
          <el-input v-model="modelEditor.path" placeholder="可选：例如 /reranks（默认 /rerank）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelEditor.visible = false">取消</el-button>
        <el-button type="primary" :loading="modelEditor.saving" @click="saveModel">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<style scoped>
.models :deep(.el-tab-pane) {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.toolbar :deep(.el-form-item) {
  margin-bottom: 0;
}

.mono {
  font-family: var(--el-font-family-mono, ui-monospace, SFMono-Regular, Menlo, monospace);
  font-size: 12px;
}

.sub {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 20px;
}

.tag {
  margin-left: 6px;
}

.check-meta {
  margin-left: 6px;
}

.pager {
  justify-content: flex-end;
}

.route-form :deep(.el-form-item) {
  margin-bottom: 16px;
}
</style>
