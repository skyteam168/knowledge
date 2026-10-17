<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
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

const KINDS: ModelKind[] = ['chat', 'embedding', 'rerank']
const SOURCE_TYPES: Record<ModelSceneInfo['source'], TagType> = {
  page: 'success',
  config: 'info',
  index: 'warning',
}

const { t } = useI18n()

function sceneLabel(scene: ModelScene): string {
  return t(`models.scene.${scene}`)
}

const kindLabels = computed(
  () =>
    Object.fromEntries(KINDS.map((k) => [k, t(`models.kind.${k}`)])) as Record<ModelKind, string>,
)

function sourceTag(source: ModelSceneInfo['source']): { label: string; type: TagType } {
  return { label: t(`models.source.${source}`), type: SOURCE_TYPES[source] }
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
      const parts = [t('models.check.ok', { name, ms: r.latency_ms })]
      if (r.first_token_ms !== null) {
        parts.push(t('models.check.firstToken', { ms: r.first_token_ms }))
      }
      if (r.sample) parts.push(t('models.check.sample', { sample: r.sample }))
      ElMessage.success({ message: parts.join(t('models.check.separator')), duration: 5000 })
      if (r.warning) ElMessage.warning({ message: r.warning, duration: 8000 })
    } else {
      ElMessage.error({
        message: t('models.check.failed', { name, message: r.message }),
        duration: 8000,
      })
    }
    await Promise.all([loadOverview(), loadModels()])
  } finally {
    checking.value[modelId] = false
  }
}

function checkTag(status: string | null): { label: string; type: TagType } {
  if (status === 'ok') return { label: t('models.checkStatus.ok'), type: 'success' }
  if (status === 'error') return { label: t('models.checkStatus.error'), type: 'danger' }
  return { label: t('models.checkStatus.none'), type: 'info' }
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
  return t('models.optionLabel', { name: m.name, provider: m.provider_name })
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
        ? t('models.routes.switched', { seconds: overview.value.refresh_seconds })
        : t('models.routes.restored'),
    )
    await loadModels()
  } catch (e) {
    if (e instanceof HttpError && e.code === 'MODEL_CHECK_FAILED') {
      const failures = (e.detail as ModelCheckFailure[]) ?? []
      const text = failures
        .map((f) =>
          t('models.routes.failureLine', {
            scene: sceneLabel(f.scene),
            model: f.model,
            message: f.message,
          }),
        )
        .join('\n')
      await loadModels()
      try {
        await ElMessageBox.confirm(
          t('models.routes.forceConfirm', { failures: text }),
          t('models.routes.forceTitle'),
          {
            type: 'warning',
            confirmButtonText: t('models.routes.forceButton'),
            cancelButtonText: t('common.cancel'),
          },
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
    ElMessage.warning(t('models.routes.selectChat'))
    return
  }
  await submitRoutes(routeForm.chat, routeForm.fallback || null)
}

async function resetRoutes(): Promise<void> {
  await ElMessageBox.confirm(t('models.routes.resetConfirm'), t('models.routes.resetToConfig'), {
    type: 'warning',
  })
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
    ElMessage.success(t('common.saved'))
    modelEditor.visible = false
    await Promise.all([loadModels(), loadProviders(), loadOverview()])
  } finally {
    modelEditor.saving = false
  }
}

async function removeModel(model: ModelItem): Promise<void> {
  await ElMessageBox.confirm(
    t('models.list.deleteConfirm', { name: model.name }),
    t('common.delete'),
    { type: 'warning' },
  )
  await deleteModel(model.id)
  ElMessage.success(t('common.deleted'))
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
    ElMessage.success(t('common.saved'))
    providerEditor.visible = false
    await Promise.all([loadProviders(), loadModels(), loadOverview()])
  } finally {
    providerEditor.saving = false
  }
}

async function toggleProvider(provider: ModelProvider, enabled: boolean): Promise<void> {
  try {
    await updateModelProvider(provider.id, { enabled })
    ElMessage.success(
      enabled ? t('models.providers.enabledToast') : t('models.providers.disabledToast'),
    )
  } finally {
    await Promise.all([loadProviders(), loadModels()])
  }
}

async function syncProvider(provider: ModelProvider): Promise<void> {
  syncing.value[provider.id] = true
  try {
    const r = await syncProviderModels(provider.id)
    ElMessage.success(
      r.missing.length
        ? t('models.providers.syncResultMissing', {
            listed: r.listed,
            added: r.added,
            missing: r.missing.length,
          })
        : t('models.providers.syncResult', { listed: r.listed, added: r.added }),
    )
    await Promise.all([loadProviders(), loadModels()])
  } finally {
    syncing.value[provider.id] = false
  }
}

async function removeProvider(provider: ModelProvider): Promise<void> {
  await ElMessageBox.confirm(
    t('models.providers.deleteConfirm', { name: provider.name, count: provider.model_count }),
    t('common.delete'),
    { type: 'warning' },
  )
  await deleteModelProvider(provider.id)
  ElMessage.success(t('common.deleted'))
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
      <el-tab-pane :label="t('models.routes.tab')" name="routes">
        <el-table :data="overview?.scenes ?? []" size="small" class="scenes">
          <el-table-column :label="t('models.routes.scene')" width="150">
            <template #default="{ row }">{{ sceneLabel(row.scene as ModelScene) }}</template>
          </el-table-column>
          <el-table-column :label="t('models.routes.currentModel')" min-width="180">
            <template #default="{ row }">
              <span v-if="row.model" class="mono">{{ row.model }}</span>
              <el-text v-else type="info">{{ t('models.routes.notSet') }}</el-text>
              <div v-if="row.dim" class="sub">{{ t('models.routes.dim', { dim: row.dim }) }}</div>
            </template>
          </el-table-column>
          <el-table-column
            :label="t('models.routes.baseUrl')"
            min-width="260"
            show-overflow-tooltip
          >
            <template #default="{ row }">
              <span class="mono">{{ row.base_url ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('models.routes.source')" width="110">
            <template #default="{ row }">
              <el-tag :type="sourceTag(row.source as ModelSceneInfo['source']).type" size="small">
                {{ sourceTag(row.source as ModelSceneInfo['source']).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.status')" width="90">
            <template #default="{ row }">
              <el-tag :type="checkTag(row.last_check_status).type" size="small">
                {{ checkTag(row.last_check_status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('models.routes.note')" min-width="220">
            <template #default="{ row }">
              <span class="sub">{{
                row.note ?? (row.editable ? t('models.routes.editableBelow') : '')
              }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="90" fixed="right">
            <template #default="{ row }">
              <el-button
                v-if="row.model_id"
                link
                type="primary"
                :loading="checking[row.model_id]"
                @click="runCheck(row.model_id, row.model)"
              >
                {{ t('models.check.run') }}
              </el-button>
              <el-tooltip v-else-if="row.model" :content="t('models.check.notInList')">
                <el-text type="info" size="small">{{ t('models.check.unavailable') }}</el-text>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>

        <el-card shadow="never" :header="t('models.routes.formTitle')" class="route-form">
          <el-form label-width="110px" @submit.prevent="saveRoutes">
            <el-form-item :label="t('models.routes.chatModel')" required>
              <el-select
                v-model="routeForm.chat"
                filterable
                :placeholder="t('models.routes.chatPlaceholder')"
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
            <el-form-item :label="t('models.routes.fallbackModel')">
              <el-select
                v-model="routeForm.fallback"
                filterable
                clearable
                :placeholder="t('models.routes.fallbackPlaceholder')"
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
                {{ t('models.routes.checkAndSwitch') }}
              </el-button>
              <el-button v-if="pageRouting" :disabled="savingRoutes" @click="resetRoutes">
                {{ t('models.routes.resetToConfig') }}
              </el-button>
            </el-form-item>
          </el-form>
          <div class="sub">
            {{ t('models.routes.help', { seconds: overview?.refresh_seconds ?? 5 }) }}
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane :label="t('models.list.tab', { count: modelTotal })" name="models">
        <div class="toolbar">
          <el-form :inline="true" @submit.prevent="searchModels">
            <el-form-item>
              <el-select
                v-model="modelFilters.provider_id"
                clearable
                :placeholder="t('models.list.allProviders')"
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
                :placeholder="t('models.list.allKinds')"
                style="width: 120px"
                @change="searchModels"
              >
                <el-option
                  v-for="(label, kind) in kindLabels"
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
                :placeholder="t('models.list.namePlaceholder')"
                style="width: 200px"
                @clear="searchModels"
              />
            </el-form-item>
            <el-form-item>
              <el-button native-type="submit">{{ t('models.list.query') }}</el-button>
            </el-form-item>
          </el-form>
          <el-button
            type="primary"
            :icon="Plus"
            :disabled="!providers.length"
            @click="openModelEditor()"
          >
            {{ t('models.list.add') }}
          </el-button>
        </div>
        <el-table
          v-loading="loadingModels"
          :data="models"
          size="small"
          :empty-text="t('models.list.empty')"
        >
          <el-table-column :label="t('models.list.model')" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.name }}</span>
              <el-tag v-for="s in row.scenes" :key="s" size="small" type="success" class="tag">
                {{ sceneLabel(s as ModelScene) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('models.list.kind')" width="80">
            <template #default="{ row }">{{ kindLabels[row.kind as ModelKind] }}</template>
          </el-table-column>
          <el-table-column
            prop="provider_name"
            :label="t('models.list.provider')"
            width="160"
            show-overflow-tooltip
          />
          <el-table-column :label="t('models.list.baseUrl')" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.effective_base_url }}{{ row.path ?? '' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('models.list.source')" width="80">
            <template #default="{ row }">{{
              row.origin === 'synced' ? t('models.list.synced') : t('models.list.manual')
            }}</template>
          </el-table-column>
          <el-table-column :label="t('models.list.lastCheck')" width="200">
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
          <el-table-column :label="t('common.actions')" width="160" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="checking[row.id]"
                @click="runCheck(row.id, row.name)"
              >
                {{ t('models.check.run') }}
              </el-button>
              <el-button link type="primary" @click="openModelEditor(row as ModelItem)">{{
                t('common.edit')
              }}</el-button>
              <el-button
                link
                type="danger"
                :disabled="row.scenes.length > 0"
                @click="removeModel(row as ModelItem)"
              >
                {{ t('common.delete') }}
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

      <el-tab-pane :label="t('models.providers.tab', { count: providers.length })" name="providers">
        <div class="toolbar">
          <el-button type="primary" :icon="Plus" @click="openProviderEditor()">{{
            t('models.providers.add')
          }}</el-button>
          <span class="sub">{{ t('models.providers.hint') }}</span>
        </div>
        <el-table
          v-loading="loadingProviders"
          :data="providers"
          size="small"
          :empty-text="t('models.providers.empty')"
        >
          <el-table-column
            prop="name"
            :label="t('common.name')"
            min-width="160"
            show-overflow-tooltip
          />
          <el-table-column
            :label="t('models.providers.baseUrl')"
            min-width="280"
            show-overflow-tooltip
          >
            <template #default="{ row }"
              ><span class="mono">{{ row.base_url }}</span></template
            >
          </el-table-column>
          <el-table-column :label="t('models.providers.apiKey')" width="130">
            <template #default="{ row }">
              <span class="mono sub">{{
                row.has_api_key ? row.api_key_hint : t('models.providers.notSet')
              }}</span>
            </template>
          </el-table-column>
          <el-table-column
            prop="model_count"
            :label="t('models.providers.modelCount')"
            width="80"
          />
          <el-table-column :label="t('models.providers.source')" width="90">
            <template #default="{ row }">{{
              row.source === 'env' ? t('models.providers.fromConfig') : t('models.providers.manual')
            }}</template>
          </el-table-column>
          <el-table-column :label="t('models.providers.addedAt')" width="160">
            <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column :label="t('common.enabled')" width="80">
            <template #default="{ row }">
              <el-tooltip :disabled="!row.in_use" :content="t('models.providers.inUse')">
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
          <el-table-column :label="t('common.actions')" width="200" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :loading="syncing[row.id]"
                @click="syncProvider(row as ModelProvider)"
              >
                {{ t('models.providers.syncModels') }}
              </el-button>
              <el-button link type="primary" @click="openProviderEditor(row as ModelProvider)">{{
                t('common.edit')
              }}</el-button>
              <el-button
                link
                type="danger"
                :disabled="row.in_use"
                @click="removeProvider(row as ModelProvider)"
              >
                {{ t('common.delete') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog
      v-model="providerEditor.visible"
      :title="
        providerEditor.id
          ? t('models.providerEditor.editTitle')
          : t('models.providerEditor.addTitle')
      "
      width="560px"
    >
      <el-form label-width="90px" @submit.prevent="saveProvider">
        <el-form-item :label="t('common.name')" required>
          <el-input
            v-model="providerEditor.name"
            maxlength="128"
            :placeholder="t('models.providerEditor.namePlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('models.providers.baseUrl')" required>
          <el-input
            v-model="providerEditor.base_url"
            placeholder="https://.../compatible-mode/v1"
          />
        </el-form-item>
        <el-form-item :label="t('models.providers.apiKey')">
          <el-input
            v-model="providerEditor.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="
              providerEditor.id
                ? providerEditor.hint
                  ? t('models.providerEditor.keepKeyWithHint', { hint: providerEditor.hint })
                  : t('models.providerEditor.keepKey')
                : 'sk-...'
            "
            :disabled="providerEditor.clear_api_key"
          />
        </el-form-item>
        <el-form-item v-if="providerEditor.id && providerEditor.hint">
          <el-checkbox v-model="providerEditor.clear_api_key">{{
            t('models.providerEditor.clearKey')
          }}</el-checkbox>
        </el-form-item>
        <div class="sub">{{ t('models.providerEditor.keyNote') }}</div>
      </el-form>
      <template #footer>
        <el-button @click="providerEditor.visible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="providerEditor.saving" @click="saveProvider">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="modelEditor.visible"
      :title="modelEditor.id ? t('models.modelEditor.editTitle') : t('models.modelEditor.addTitle')"
      width="560px"
    >
      <el-form label-width="90px" @submit.prevent="saveModel">
        <el-form-item :label="t('models.modelEditor.provider')" required>
          <el-select
            v-model="modelEditor.provider_id"
            :disabled="!!modelEditor.id"
            style="width: 100%"
          >
            <el-option v-for="p in providers" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('models.modelEditor.name')" required>
          <el-input
            v-model="modelEditor.name"
            :disabled="!!modelEditor.id"
            :placeholder="t('models.modelEditor.namePlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('models.modelEditor.kind')" required>
          <el-radio-group v-model="modelEditor.kind" :disabled="modelEditor.inUse">
            <el-radio-button v-for="(label, kind) in kindLabels" :key="kind" :value="kind">
              {{ label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="t('models.modelEditor.baseUrl')">
          <el-input
            v-model="modelEditor.base_url"
            :placeholder="t('models.modelEditor.baseUrlPlaceholder')"
          />
        </el-form-item>
        <el-form-item v-if="modelEditor.kind === 'rerank'" :label="t('models.modelEditor.path')">
          <el-input
            v-model="modelEditor.path"
            :placeholder="t('models.modelEditor.pathPlaceholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="modelEditor.visible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="modelEditor.saving" @click="saveModel">{{
          t('common.save')
        }}</el-button>
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
