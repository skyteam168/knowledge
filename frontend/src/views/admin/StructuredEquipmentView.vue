<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  createStructuredDomain,
  createStructuredLink,
  createStructuredRecord,
  createStructuredSource,
  deleteStructuredLink,
  listEquipDevices,
  listEquipSpareParts,
  listEquipWorkOrders,
  listStructuredDomains,
  listStructuredLinks,
  listStructuredRecords,
  listStructuredSources,
  resolveStructured,
  syncStructuredSource,
} from '@/api/structured'
import type {
  EquipDevice,
  EquipSparePart,
  EquipWorkOrder,
  StructuredDomain,
  StructuredLink,
  StructuredRecord,
  StructuredResolve,
  StructuredSource,
} from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'

const { t } = useI18n()

const domains = ref<StructuredDomain[]>([])
const activeDomainId = ref('')
const activeDomain = computed(
  () => domains.value.find((d) => d.id === activeDomainId.value) ?? null,
)
const isEquipment = computed(() => activeDomain.value?.kind === 'equipment')

const tab = ref('devices')
const sources = ref<StructuredSource[]>([])
const sourceFilter = ref('')
const q = ref('')
const pager = reactive({ page: 1, size: 20 })
const total = ref(0)
const loading = ref(false)

const devices = ref<EquipDevice[]>([])
const workOrders = ref<EquipWorkOrder[]>([])
const spareParts = ref<EquipSparePart[]>([])
const records = ref<StructuredRecord[]>([])

const selectedObject = ref<{ type: string; id: string; label: string } | null>(null)
const links = ref<StructuredLink[]>([])
const linksLoading = ref(false)

async function loadDomains(): Promise<void> {
  domains.value = await listStructuredDomains()
  if (!activeDomainId.value && domains.value.length) {
    activeDomainId.value = domains.value[0]!.id
  }
}

async function loadSources(): Promise<void> {
  sources.value = await listStructuredSources()
}

const syncing = ref(false)

async function syncSelectedSource(): Promise<void> {
  if (!sourceFilter.value) {
    ElMessage.warning(t('structured.syncNeedSource'))
    return
  }
  syncing.value = true
  try {
    const result = await syncStructuredSource(sourceFilter.value)
    const created =
      (result.stats?.devices as { created?: number } | undefined)?.created ?? 0
    ElMessage.success(`${t('structured.syncOk')} (+${created})`)
    await Promise.all([loadSources(), loadRows()])
  } catch {
    ElMessage.error(t('structured.syncFail'))
  } finally {
    syncing.value = false
  }
}

async function loadRows(): Promise<void> {
  if (!activeDomain.value) return
  loading.value = true
  try {
    const params = {
      page: pager.page,
      size: pager.size,
      q: q.value.trim() || undefined,
      source_id: sourceFilter.value || undefined,
    }
    if (isEquipment.value) {
      if (tab.value === 'devices') {
        const page = await listEquipDevices(params)
        devices.value = page.items
        total.value = page.total
      } else if (tab.value === 'workOrders') {
        const page = await listEquipWorkOrders(params)
        workOrders.value = page.items
        total.value = page.total
      } else {
        const page = await listEquipSpareParts(params)
        spareParts.value = page.items
        total.value = page.total
      }
    } else {
      const page = await listStructuredRecords({
        ...params,
        domain_id: activeDomain.value.id,
      })
      records.value = page.items
      total.value = page.total
    }
  } finally {
    loading.value = false
  }
}

function search(): void {
  pager.page = 1
  void loadRows()
}

watch(activeDomainId, () => {
  selectedObject.value = null
  links.value = []
  tab.value = 'devices'
  search()
})

watch(tab, () => {
  if (!isEquipment.value) return
  selectedObject.value = null
  links.value = []
  search()
})

async function selectRow(type: string, id: string, label: string): Promise<void> {
  selectedObject.value = { type, id, label }
  linksLoading.value = true
  try {
    links.value = await listStructuredLinks(type, id)
  } finally {
    linksLoading.value = false
  }
}

const sourceDialog = ref(false)
const sourceFormRef = ref<FormInstance>()
const sourceForm = reactive({ name: '', type: 'manual', enabled: true })
const sourceSaving = ref(false)
const sourceRules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('structured.nameRequired'), trigger: 'blur' }],
}))

async function submitSource(): Promise<void> {
  if (!(await sourceFormRef.value?.validate().catch(() => false))) return
  sourceSaving.value = true
  try {
    await createStructuredSource({
      name: sourceForm.name.trim(),
      type: sourceForm.type,
      enabled: sourceForm.enabled,
    })
    ElMessage.success(t('common.saved'))
    sourceDialog.value = false
    sourceForm.name = ''
    await loadSources()
  } finally {
    sourceSaving.value = false
  }
}

const domainDialog = ref(false)
const domainFormRef = ref<FormInstance>()
const domainForm = reactive({ code: '', name: '', description: '' })
const domainSaving = ref(false)
const domainRules = computed<FormRules>(() => ({
  code: [{ required: true, message: t('structured.codeRequired'), trigger: 'blur' }],
  name: [{ required: true, message: t('structured.nameRequired'), trigger: 'blur' }],
}))

async function submitDomain(): Promise<void> {
  if (!(await domainFormRef.value?.validate().catch(() => false))) return
  domainSaving.value = true
  try {
    const created = await createStructuredDomain({
      code: domainForm.code.trim(),
      name: domainForm.name.trim(),
      description: domainForm.description.trim() || null,
    })
    ElMessage.success(t('common.saved'))
    domainDialog.value = false
    domainForm.code = ''
    domainForm.name = ''
    domainForm.description = ''
    await loadDomains()
    activeDomainId.value = created.id
  } finally {
    domainSaving.value = false
  }
}

const recordDialog = ref(false)
const recordFormRef = ref<FormInstance>()
const recordForm = reactive({
  source_id: '',
  object_type: '',
  external_id: '',
  title: '',
  status: 'active',
})
const recordSaving = ref(false)
const recordRules = computed<FormRules>(() => ({
  source_id: [{ required: true, message: t('structured.sourceRequired'), trigger: 'change' }],
  object_type: [{ required: true, message: t('structured.objectTypeRequired'), trigger: 'blur' }],
  external_id: [{ required: true, message: t('structured.externalIdRequired'), trigger: 'blur' }],
  title: [{ required: true, message: t('structured.nameRequired'), trigger: 'blur' }],
}))

function openRecordDialog(): void {
  if (!sources.value.length) {
    ElMessage.warning(t('structured.needSource'))
    return
  }
  recordForm.source_id = sources.value[0]!.id
  recordForm.object_type = ''
  recordForm.external_id = ''
  recordForm.title = ''
  recordForm.status = 'active'
  recordDialog.value = true
}

async function submitRecord(): Promise<void> {
  if (!activeDomain.value) return
  if (!(await recordFormRef.value?.validate().catch(() => false))) return
  recordSaving.value = true
  try {
    await createStructuredRecord({
      domain_id: activeDomain.value.id,
      source_id: recordForm.source_id,
      object_type: recordForm.object_type.trim(),
      external_id: recordForm.external_id.trim(),
      title: recordForm.title.trim(),
      status: recordForm.status.trim() || 'active',
    })
    ElMessage.success(t('common.saved'))
    recordDialog.value = false
    await loadRows()
  } finally {
    recordSaving.value = false
  }
}

const linkForm = reactive({ terminology_entity_id: '', ko_id: '' })
const linkSaving = ref(false)

async function addLink(): Promise<void> {
  if (!selectedObject.value) return
  const term = linkForm.terminology_entity_id.trim() || null
  const ko = linkForm.ko_id.trim() || null
  if (!term && !ko) return
  linkSaving.value = true
  try {
    await createStructuredLink({
      object_type: selectedObject.value.type,
      object_id: selectedObject.value.id,
      terminology_entity_id: term,
      ko_id: ko,
    })
    linkForm.terminology_entity_id = ''
    linkForm.ko_id = ''
    links.value = await listStructuredLinks(selectedObject.value.type, selectedObject.value.id)
    ElMessage.success(t('common.saved'))
  } finally {
    linkSaving.value = false
  }
}

async function removeLink(link: StructuredLink): Promise<void> {
  await ElMessageBox.confirm(t('structured.deleteLinkConfirm'), t('common.delete'))
  await deleteStructuredLink(link.id)
  if (selectedObject.value) {
    links.value = await listStructuredLinks(selectedObject.value.type, selectedObject.value.id)
  }
}

const resolveForm = reactive({ object_type: 'device', external_id: '', source_id: '' })
const resolveResult = ref<StructuredResolve | null>(null)
const resolving = ref(false)

async function doResolve(): Promise<void> {
  resolving.value = true
  try {
    resolveResult.value = await resolveStructured({
      object_type: resolveForm.object_type.trim(),
      external_id: resolveForm.external_id.trim(),
      source_id: resolveForm.source_id || undefined,
    })
  } finally {
    resolving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadDomains(), loadSources()])
  await loadRows()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>{{ t('structured.title') }}</h2>
        <p class="hint">{{ t('structured.hint') }}</p>
      </div>
      <div class="head-actions">
        <el-button @click="sourceDialog = true">{{ t('structured.createSource') }}</el-button>
        <el-button type="primary" @click="domainDialog = true">{{ t('structured.createDomain') }}</el-button>
      </div>
    </div>

    <div class="layout">
      <el-card shadow="never" class="domain-panel">
        <template #header>{{ t('structured.domains') }}</template>
        <el-menu
          :default-active="activeDomainId"
          class="domain-menu"
          @select="(id: string) => (activeDomainId = id)"
        >
          <el-menu-item v-for="d in domains" :key="d.id" :index="d.id">
            <div class="domain-item">
              <span>{{ d.name }}</span>
              <el-tag size="small" type="info">{{ d.code }}</el-tag>
            </div>
          </el-menu-item>
        </el-menu>
        <EmptyState v-if="!domains.length" :description="t('structured.emptyDomains')" />
      </el-card>

      <div class="main-col">
        <el-card shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span>
                {{ activeDomain?.name || t('structured.domains') }}
                <span v-if="activeDomain?.description" class="sub">· {{ activeDomain.description }}</span>
              </span>
              <el-button
                v-if="activeDomain && !isEquipment"
                type="primary"
                @click="openRecordDialog"
              >
                {{ t('structured.createRecord') }}
              </el-button>
            </div>
          </template>

          <div class="toolbar">
            <el-select
              v-model="sourceFilter"
              clearable
              :placeholder="t('structured.sources')"
              style="width: 180px"
              @change="search"
            >
              <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-input
              v-model="q"
              clearable
              :placeholder="t('structured.search')"
              style="width: 220px"
              @keyup.enter="search"
            />
            <el-button @click="search">{{ t('structured.search') }}</el-button>
            <el-button
              :disabled="!sourceFilter"
              :loading="syncing"
              @click="syncSelectedSource"
            >
              {{ t('structured.syncSource') }}
            </el-button>
          </div>

          <template v-if="isEquipment">
            <el-tabs v-model="tab">
              <el-tab-pane :label="t('structured.devices')" name="devices">
                <el-table
                  v-loading="loading"
                  :data="devices"
                  size="small"
                  highlight-current-row
                  @row-click="(row: EquipDevice) => selectRow('device', row.id, row.name)"
                >
                  <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
                  <el-table-column prop="name" :label="t('structured.name')" min-width="160" />
                  <el-table-column prop="status" :label="t('structured.status')" width="100" />
                  <el-table-column prop="location" :label="t('structured.location')" min-width="120" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane :label="t('structured.workOrders')" name="workOrders">
                <el-table
                  v-loading="loading"
                  :data="workOrders"
                  size="small"
                  highlight-current-row
                  @row-click="(row: EquipWorkOrder) => selectRow('work_order', row.id, row.title)"
                >
                  <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
                  <el-table-column prop="title" :label="t('structured.titleCol')" min-width="200" />
                  <el-table-column prop="device_external_id" :label="t('structured.deviceExt')" width="140" />
                  <el-table-column prop="status" :label="t('structured.status')" width="100" />
                </el-table>
              </el-tab-pane>
              <el-tab-pane :label="t('structured.spareParts')" name="spareParts">
                <el-table
                  v-loading="loading"
                  :data="spareParts"
                  size="small"
                  highlight-current-row
                  @row-click="(row: EquipSparePart) => selectRow('spare_part', row.id, row.name)"
                >
                  <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
                  <el-table-column prop="name" :label="t('structured.name')" min-width="160" />
                  <el-table-column prop="sku" :label="t('structured.sku')" width="120" />
                  <el-table-column prop="qty_on_hand" :label="t('structured.qty')" width="100" />
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </template>

          <template v-else>
            <el-table
              v-loading="loading"
              :data="records"
              size="small"
              highlight-current-row
              @row-click="(row: StructuredRecord) => selectRow(row.object_type, row.id, row.title)"
            >
              <template #empty>
                <EmptyState :description="t('structured.emptyRows')" />
              </template>
              <el-table-column prop="object_type" :label="t('structured.objectType')" width="120" />
              <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
              <el-table-column prop="title" :label="t('structured.titleCol')" min-width="180" />
              <el-table-column prop="status" :label="t('structured.status')" width="100" />
            </el-table>
          </template>

          <div class="pager">
            <el-pagination
              v-model:current-page="pager.page"
              v-model:page-size="pager.size"
              layout="total, prev, pager, next"
              :total="total"
              @current-change="loadRows"
            />
          </div>
        </el-card>

        <el-card v-if="selectedObject" shadow="never" class="block">
          <template #header>
            {{ t('structured.links') }} · {{ selectedObject.label }}
          </template>
          <el-table v-loading="linksLoading" :data="links" size="small">
            <el-table-column :label="t('structured.term')" min-width="160">
              <template #default="{ row }">
                <span v-if="row.terminology_entity_id">{{ row.terminology_name || row.terminology_entity_id }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('structured.ko')" min-width="160">
              <template #default="{ row }">
                <span v-if="row.ko_id">{{ row.ko_title || row.ko_id }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column width="90">
              <template #default="{ row }">
                <el-button link type="danger" @click.stop="removeLink(row as StructuredLink)">
                  {{ t('common.delete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="link-form">
            <el-input
              v-model="linkForm.terminology_entity_id"
              :placeholder="t('structured.termId')"
              style="width: 220px"
            />
            <el-input v-model="linkForm.ko_id" :placeholder="t('structured.koId')" style="width: 220px" />
            <el-button type="primary" :loading="linkSaving" @click="addLink">
              {{ t('structured.addLink') }}
            </el-button>
          </div>
        </el-card>

        <el-card shadow="never" class="block">
          <template #header>{{ t('structured.resolve') }}</template>
          <div class="toolbar">
            <el-input
              v-model="resolveForm.object_type"
              :placeholder="t('structured.objectType')"
              style="width: 140px"
            />
            <el-input
              v-model="resolveForm.external_id"
              :placeholder="t('structured.externalId')"
              style="width: 200px"
            />
            <el-select
              v-model="resolveForm.source_id"
              clearable
              :placeholder="t('structured.sources')"
              style="width: 180px"
            >
              <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
            </el-select>
            <el-button type="primary" :loading="resolving" @click="doResolve">
              {{ t('structured.resolveBtn') }}
            </el-button>
          </div>
          <pre v-if="resolveResult" class="json">{{ JSON.stringify(resolveResult, null, 2) }}</pre>
        </el-card>
      </div>
    </div>

    <el-dialog v-model="sourceDialog" :title="t('structured.createSource')" width="420px">
      <el-form ref="sourceFormRef" :model="sourceForm" :rules="sourceRules" label-position="top">
        <el-form-item :label="t('structured.sourceName')" prop="name">
          <el-input v-model="sourceForm.name" />
        </el-form-item>
        <el-form-item :label="t('structured.sourceType')">
          <el-select v-model="sourceForm.type" style="width: 100%">
            <el-option
              v-for="ty in ['manual', 'mes', 'erp', 'qms', 'plm', 'wms']"
              :key="ty"
              :label="t(`structured.types.${ty}`, ty)"
              :value="ty"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="sourceDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="sourceSaving" @click="submitSource">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="domainDialog" :title="t('structured.createDomain')" width="460px">
      <el-form ref="domainFormRef" :model="domainForm" :rules="domainRules" label-position="top">
        <el-form-item :label="t('structured.domainCode')" prop="code">
          <el-input v-model="domainForm.code" placeholder="process_v2" />
        </el-form-item>
        <el-form-item :label="t('structured.domainName')" prop="name">
          <el-input v-model="domainForm.name" />
        </el-form-item>
        <el-form-item :label="t('structured.domainDesc')">
          <el-input v-model="domainForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="domainDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="domainSaving" @click="submitDomain">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recordDialog" :title="t('structured.createRecord')" width="480px">
      <el-form ref="recordFormRef" :model="recordForm" :rules="recordRules" label-position="top">
        <el-form-item :label="t('structured.sources')" prop="source_id">
          <el-select v-model="recordForm.source_id" style="width: 100%">
            <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('structured.objectType')" prop="object_type">
          <el-input v-model="recordForm.object_type" placeholder="recipe / sku / inspection" />
        </el-form-item>
        <el-form-item :label="t('structured.externalId')" prop="external_id">
          <el-input v-model="recordForm.external_id" />
        </el-form-item>
        <el-form-item :label="t('structured.titleCol')" prop="title">
          <el-input v-model="recordForm.title" />
        </el-form-item>
        <el-form-item :label="t('structured.status')">
          <el-input v-model="recordForm.status" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="recordSaving" @click="submitRecord">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.page-head h2 {
  margin: 0 0 4px;
  font-size: 20px;
}
.head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.hint {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.layout {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.domain-panel {
  border-radius: 8px;
}
.domain-menu {
  border-right: none;
}
.domain-item {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.main-col {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.block {
  border-radius: 8px;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.sub {
  color: var(--el-text-color-secondary);
  font-weight: normal;
  font-size: 13px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.link-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
.json {
  margin: 0;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 12px;
  overflow: auto;
}
@media (max-width: 960px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
