<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  createObjectRelation,
  createStructuredDomain,
  createStructuredLink,
  createStructuredRecord,
  createStructuredSource,
  deleteObjectRelation,
  deleteStructuredLink,
  getStructuredAttrSchema,
  getStructuredObjectAcl,
  listEquipDevices,
  listEquipSpareParts,
  listEquipWorkOrders,
  listObjectRelations,
  listStructuredAttrSchemas,
  listStructuredDomains,
  listStructuredLinks,
  listStructuredRecordChildren,
  listStructuredRecords,
  listStructuredSources,
  resolveStructured,
  setStructuredObjectAcl,
  syncStructuredSource,
} from '@/api/structured'
import type {
  AclEntryOut,
  EquipDevice,
  EquipSparePart,
  EquipWorkOrder,
  ObjectRelation,
  StructuredAttrSchema,
  StructuredDomain,
  StructuredLink,
  StructuredRecord,
  StructuredResolve,
  StructuredSource,
} from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import AclEditor from '@/components/knowledge/AclEditor.vue'

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
const selectedRecord = ref<StructuredRecord | null>(null)
const children = ref<StructuredRecord[]>([])
const childrenLoading = ref(false)
const links = ref<StructuredLink[]>([])
const linksLoading = ref(false)
const relations = ref<ObjectRelation[]>([])
const relationsLoading = ref(false)
const relationSaving = ref(false)
const relationTypes = [
  'has_part',
  'located_in',
  'has_failure_mode',
  'caused_by',
  'consumes',
  'work_order_for',
  'spare_for',
] as const
const relationForm = reactive({
  relation_type: 'has_failure_mode',
  direction: 'out' as 'out' | 'in',
  peer_object_type: 'failure_mode',
  peer_object_id: '',
})

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

async function syncSelectedSource(forceFull = false): Promise<void> {
  if (!sourceFilter.value) {
    ElMessage.warning(t('structured.syncNeedSource'))
    return
  }
  if (forceFull) {
    try {
      await ElMessageBox.confirm(t('structured.syncForceFullConfirm'), t('structured.syncForceFull'), {
        type: 'warning',
      })
    } catch {
      return
    }
  }
  syncing.value = true
  try {
    const result = await syncStructuredSource(sourceFilter.value, false, forceFull)
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
  selectedRecord.value = null
  children.value = []
  links.value = []
  relations.value = []
  tab.value = 'devices'
  search()
})

watch(tab, () => {
  if (!isEquipment.value) return
  selectedObject.value = null
  selectedRecord.value = null
  children.value = []
  links.value = []
  relations.value = []
  search()
})

async function loadRelationsForSelected(): Promise<void> {
  if (!selectedObject.value) {
    relations.value = []
    return
  }
  const id = selectedObject.value.id
  relationsLoading.value = true
  try {
    const [outbound, inbound] = await Promise.all([
      listObjectRelations({ from_kind: 'structured', from_id: id, limit: 200 }),
      listObjectRelations({ to_kind: 'structured', to_id: id, limit: 200 }),
    ])
    const byId = new Map<string, ObjectRelation>()
    for (const edge of [...outbound, ...inbound]) byId.set(edge.id, edge)
    relations.value = [...byId.values()]
  } finally {
    relationsLoading.value = false
  }
}

async function loadChildrenForRecord(row: StructuredRecord): Promise<void> {
  childrenLoading.value = true
  try {
    children.value = await listStructuredRecordChildren({
      parent_object_type: row.object_type,
      parent_external_id: row.external_id,
      source_id: row.source_id,
      limit: 200,
    })
  } catch {
    children.value = []
  } finally {
    childrenLoading.value = false
  }
}

async function selectRow(type: string, id: string, label: string): Promise<void> {
  selectedObject.value = { type, id, label }
  selectedRecord.value = null
  children.value = []
  linksLoading.value = true
  try {
    links.value = await listStructuredLinks(type, id)
  } finally {
    linksLoading.value = false
  }
  await loadRelationsForSelected()
}

async function selectRecordRow(row: StructuredRecord): Promise<void> {
  selectedRecord.value = row
  selectedObject.value = { type: row.object_type, id: row.id, label: row.title }
  linksLoading.value = true
  try {
    links.value = await listStructuredLinks(row.object_type, row.id)
  } finally {
    linksLoading.value = false
  }
  await Promise.all([loadRelationsForSelected(), loadChildrenForRecord(row)])
}

async function addRelation(): Promise<void> {
  if (!selectedObject.value) return
  const peerId = relationForm.peer_object_id.trim()
  const peerType = relationForm.peer_object_type.trim()
  if (!peerId || !peerType) return
  relationSaving.value = true
  try {
    const current = {
      kind: 'structured',
      id: selectedObject.value.id,
      object_type: selectedObject.value.type,
    }
    const peer = { kind: 'structured', id: peerId, object_type: peerType }
    const from = relationForm.direction === 'out' ? current : peer
    const to = relationForm.direction === 'out' ? peer : current
    const created = await createObjectRelation({
      relation_type: relationForm.relation_type,
      from_kind: from.kind,
      from_id: from.id,
      from_object_type: from.object_type,
      to_kind: to.kind,
      to_id: to.id,
      to_object_type: to.object_type,
    })
    relationForm.peer_object_id = ''
    await loadRelationsForSelected()
    if (created.warnings?.length) {
      ElMessage.warning(created.warnings.join('; '))
    } else {
      ElMessage.success(t('structured.relationCreated'))
    }
  } catch {
    ElMessage.error(t('structured.relationRejected'))
  } finally {
    relationSaving.value = false
  }
}

async function removeRelation(edge: ObjectRelation): Promise<void> {
  await ElMessageBox.confirm(t('structured.deleteRelationConfirm'), t('common.delete'))
  await deleteObjectRelation(edge.id)
  await loadRelationsForSelected()
}

const sourceDialog = ref(false)
const sourceFormRef = ref<FormInstance>()
const sourceForm = reactive({
  name: '',
  type: 'mes',
  enabled: true,
  connector: 'none' as 'none' | 'mysql' | 'postgres' | 'mssql' | 'mongo' | 'csv' | 'rest',
  mysql_host: '127.0.0.1',
  mysql_port: 3306,
  mysql_database: '',
  mysql_user: '',
  mysql_password_env: 'MES_MYSQL_PASSWORD',
  mysql_table: 'device_info',
  pg_host: '127.0.0.1',
  pg_port: 5432,
  pg_database: '',
  pg_user: '',
  pg_password_env: 'MES_PG_PASSWORD',
  pg_schema: 'public',
  pg_table: 'device_info',
  mssql_host: '127.0.0.1',
  mssql_port: 1433,
  mssql_database: '',
  mssql_user: '',
  mssql_password_env: 'MES_MSSQL_PASSWORD',
  mssql_schema: 'dbo',
  mssql_table: 'device_info',
  mongo_host: '127.0.0.1',
  mongo_port: 27017,
  mongo_database: '',
  mongo_user: '',
  mongo_password_env: 'MES_MONGO_PASSWORD',
  mongo_auth_source: 'admin',
  mongo_collection: 'devices',
  csv_devices: '',
  rest_base_url: '',
})
const sourceSaving = ref(false)
const sourceRules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('structured.nameRequired'), trigger: 'blur' }],
}))

function buildSourceMeta(): Record<string, unknown> {
  if (sourceForm.connector === 'mysql') {
    return {
      connector: 'mysql',
      mysql: {
        host: sourceForm.mysql_host.trim(),
        port: sourceForm.mysql_port,
        database: sourceForm.mysql_database.trim(),
        user: sourceForm.mysql_user.trim(),
        password_env: sourceForm.mysql_password_env.trim() || 'MES_MYSQL_PASSWORD',
        table: sourceForm.mysql_table.trim() || 'device_info',
      },
    }
  }
  if (sourceForm.connector === 'postgres') {
    return {
      connector: 'postgres',
      postgres: {
        host: sourceForm.pg_host.trim(),
        port: sourceForm.pg_port,
        database: sourceForm.pg_database.trim(),
        user: sourceForm.pg_user.trim(),
        password_env: sourceForm.pg_password_env.trim() || 'MES_PG_PASSWORD',
        schema: sourceForm.pg_schema.trim() || 'public',
        table: sourceForm.pg_table.trim() || 'device_info',
      },
    }
  }
  if (sourceForm.connector === 'mssql') {
    return {
      connector: 'mssql',
      mssql: {
        host: sourceForm.mssql_host.trim(),
        port: sourceForm.mssql_port,
        database: sourceForm.mssql_database.trim(),
        user: sourceForm.mssql_user.trim(),
        password_env: sourceForm.mssql_password_env.trim() || 'MES_MSSQL_PASSWORD',
        schema: sourceForm.mssql_schema.trim() || 'dbo',
        table: sourceForm.mssql_table.trim() || 'device_info',
      },
    }
  }
  if (sourceForm.connector === 'mongo') {
    return {
      connector: 'mongo',
      mongo: {
        host: sourceForm.mongo_host.trim(),
        port: sourceForm.mongo_port,
        database: sourceForm.mongo_database.trim(),
        user: sourceForm.mongo_user.trim(),
        password_env: sourceForm.mongo_password_env.trim() || 'MES_MONGO_PASSWORD',
        auth_source: sourceForm.mongo_auth_source.trim() || 'admin',
        collection: sourceForm.mongo_collection.trim() || 'devices',
      },
    }
  }
  if (sourceForm.connector === 'csv') {
    return {
      connector: 'csv',
      csv: {
        devices: sourceForm.csv_devices.trim() || null,
      },
    }
  }
  if (sourceForm.connector === 'rest') {
    return {
      connector: 'rest',
      rest: {
        base_url: sourceForm.rest_base_url.trim(),
      },
    }
  }
  return {}
}

async function submitSource(): Promise<void> {
  if (!(await sourceFormRef.value?.validate().catch(() => false))) return
  if (sourceForm.connector === 'mysql') {
    if (
      !sourceForm.mysql_host.trim() ||
      !sourceForm.mysql_database.trim() ||
      !sourceForm.mysql_user.trim()
    ) {
      ElMessage.warning(t('structured.mysqlRequired'))
      return
    }
  }
  if (sourceForm.connector === 'postgres') {
    if (
      !sourceForm.pg_host.trim() ||
      !sourceForm.pg_database.trim() ||
      !sourceForm.pg_user.trim()
    ) {
      ElMessage.warning(t('structured.pgRequired'))
      return
    }
  }
  if (sourceForm.connector === 'mssql') {
    if (
      !sourceForm.mssql_host.trim() ||
      !sourceForm.mssql_database.trim() ||
      !sourceForm.mssql_user.trim()
    ) {
      ElMessage.warning(t('structured.mssqlRequired'))
      return
    }
  }
  if (sourceForm.connector === 'mongo') {
    if (!sourceForm.mongo_host.trim() || !sourceForm.mongo_database.trim()) {
      ElMessage.warning(t('structured.mongoRequired'))
      return
    }
  }
  if (sourceForm.connector === 'rest' && !sourceForm.rest_base_url.trim()) {
    ElMessage.warning(t('structured.restRequired'))
    return
  }
  sourceSaving.value = true
  try {
    await createStructuredSource({
      name: sourceForm.name.trim(),
      type: sourceForm.type,
      enabled: sourceForm.enabled,
      meta: buildSourceMeta(),
    })
    ElMessage.success(t('common.saved'))
    sourceDialog.value = false
    sourceForm.name = ''
    sourceForm.connector = 'none'
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
  parent_object_type: '',
  parent_external_id: '',
  attrs_json: '{}',
})
const recordSaving = ref(false)
const attrSchemas = ref<StructuredAttrSchema[]>([])
const activeAttrSchema = ref<StructuredAttrSchema | null>(null)
const recordRules = computed<FormRules>(() => ({
  source_id: [{ required: true, message: t('structured.sourceRequired'), trigger: 'change' }],
  object_type: [{ required: true, message: t('structured.objectTypeRequired'), trigger: 'blur' }],
  external_id: [{ required: true, message: t('structured.externalIdRequired'), trigger: 'blur' }],
  title: [{ required: true, message: t('structured.nameRequired'), trigger: 'blur' }],
}))

const industrialObjectTypes = computed(() =>
  attrSchemas.value
    .map((s) => s.object_type)
    .filter((tp) => !['device', 'work_order', 'spare_part'].includes(tp)),
)

async function loadAttrSchemas(): Promise<void> {
  try {
    attrSchemas.value = await listStructuredAttrSchemas()
  } catch {
    attrSchemas.value = []
  }
}

async function onRecordObjectTypeChange(value: string): Promise<void> {
  const tp = value.trim().toLowerCase()
  if (!tp) {
    activeAttrSchema.value = null
    return
  }
  const cached = attrSchemas.value.find((s) => s.object_type === tp)
  if (cached) {
    activeAttrSchema.value = cached
    return
  }
  try {
    activeAttrSchema.value = await getStructuredAttrSchema(tp)
  } catch {
    activeAttrSchema.value = null
  }
}

function openRecordDialog(): void {
  if (!sources.value.length) {
    ElMessage.warning(t('structured.needSource'))
    return
  }
  recordForm.source_id = sources.value[0]!.id
  recordForm.object_type = industrialObjectTypes.value[0] ?? ''
  recordForm.external_id = ''
  recordForm.title = ''
  recordForm.status = 'active'
  recordForm.parent_object_type = ''
  recordForm.parent_external_id = ''
  recordForm.attrs_json = '{}'
  void onRecordObjectTypeChange(recordForm.object_type)
  recordDialog.value = true
}

async function submitRecord(): Promise<void> {
  if (!activeDomain.value) return
  if (!(await recordFormRef.value?.validate().catch(() => false))) return
  let attrs: Record<string, unknown> = {}
  try {
    attrs = JSON.parse(recordForm.attrs_json || '{}') as Record<string, unknown>
    if (attrs === null || typeof attrs !== 'object' || Array.isArray(attrs)) {
      throw new Error('attrs must be object')
    }
  } catch {
    ElMessage.error(t('structured.attrsJsonInvalid'))
    return
  }
  const parentType = recordForm.parent_object_type.trim() || null
  const parentExt = recordForm.parent_external_id.trim() || null
  if ((parentType && !parentExt) || (!parentType && parentExt)) {
    ElMessage.warning(t('structured.parentPairRequired'))
    return
  }
  recordSaving.value = true
  try {
    await createStructuredRecord({
      domain_id: activeDomain.value.id,
      source_id: recordForm.source_id,
      object_type: recordForm.object_type.trim(),
      external_id: recordForm.external_id.trim(),
      title: recordForm.title.trim(),
      status: recordForm.status.trim() || 'active',
      parent_object_type: parentType,
      parent_external_id: parentExt,
      attrs,
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

const aclDialog = ref(false)
const aclLoading = ref(false)
const aclSaving = ref(false)
const aclEntries = ref<AclEntryOut[]>([])

async function openAclDialog(): Promise<void> {
  if (!selectedObject.value) return
  aclDialog.value = true
  aclLoading.value = true
  try {
    const acl = await getStructuredObjectAcl(selectedObject.value.type, selectedObject.value.id)
    aclEntries.value = acl.entries.map((e) => ({ ...e, effect: e.effect ?? 'allow' }))
  } catch {
    aclDialog.value = false
  } finally {
    aclLoading.value = false
  }
}

async function saveAcl(): Promise<void> {
  if (!selectedObject.value) return
  aclSaving.value = true
  try {
    await setStructuredObjectAcl(
      selectedObject.value.type,
      selectedObject.value.id,
      aclEntries.value.map(({ principal_type, principal_id, permission, effect }) => ({
        principal_type,
        principal_id,
        permission: effect === 'deny' ? 'read' : permission,
        effect: effect ?? 'allow',
      })),
    )
    ElMessage.success(t('structured.aclUpdated'))
    aclDialog.value = false
  } finally {
    aclSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadDomains(), loadSources(), loadAttrSchemas()])
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
            <el-dropdown
              split-button
              :disabled="!sourceFilter"
              :loading="syncing"
              @click="syncSelectedSource(false)"
              @command="(cmd: string) => syncSelectedSource(cmd === 'force')"
            >
              {{ t('structured.syncSource') }}
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="force">
                    {{ t('structured.syncForceFull') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
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
              @row-click="(row: StructuredRecord) => selectRecordRow(row)"
            >
              <template #empty>
                <EmptyState :description="t('structured.emptyRows')" />
              </template>
              <el-table-column prop="object_type" :label="t('structured.objectType')" width="120" />
              <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
              <el-table-column prop="title" :label="t('structured.titleCol')" min-width="180" />
              <el-table-column :label="t('structured.parent')" min-width="160">
                <template #default="{ row }">
                  <span v-if="row.parent_object_type && row.parent_external_id">
                    {{ row.parent_object_type }} · {{ row.parent_external_id }}
                  </span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
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

        <el-card v-if="selectedRecord" shadow="never" class="block">
          <template #header>
            {{ t('structured.children') }} · {{ selectedRecord.title }}
          </template>
          <el-table
            v-loading="childrenLoading"
            :data="children"
            size="small"
            @row-click="(row: StructuredRecord) => selectRecordRow(row)"
          >
            <template #empty>
              <EmptyState :description="t('structured.emptyChildren')" />
            </template>
            <el-table-column prop="object_type" :label="t('structured.objectType')" width="120" />
            <el-table-column prop="external_id" :label="t('structured.externalId')" width="140" />
            <el-table-column prop="title" :label="t('structured.titleCol')" min-width="160" />
            <el-table-column prop="status" :label="t('structured.status')" width="100" />
          </el-table>
        </el-card>

        <el-card v-if="selectedObject" shadow="never" class="block">
          <template #header>
            <div class="card-head">
              <span>{{ t('structured.links') }} · {{ selectedObject.label }}</span>
              <el-button @click="openAclDialog">{{ t('structured.acl') }}</el-button>
            </div>
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

        <el-card v-if="selectedObject" shadow="never" class="block">
          <template #header>
            {{ t('structured.relations') }} · {{ selectedObject.label }}
          </template>
          <el-table v-loading="relationsLoading" :data="relations" size="small">
            <template #empty>
              <EmptyState :description="t('structured.emptyRelations')" />
            </template>
            <el-table-column :label="t('structured.relationType')" width="160">
              <template #default="{ row }">
                {{ row.relation_local_name || row.relation_type }}
              </template>
            </el-table-column>
            <el-table-column :label="t('structured.relationFrom')" min-width="180">
              <template #default="{ row }">
                {{ row.from_object_type || row.from_kind }} · {{ row.from_id }}
              </template>
            </el-table-column>
            <el-table-column :label="t('structured.relationTo')" min-width="180">
              <template #default="{ row }">
                {{ row.to_object_type || row.to_kind }} · {{ row.to_id }}
              </template>
            </el-table-column>
            <el-table-column width="90">
              <template #default="{ row }">
                <el-button link type="danger" @click.stop="removeRelation(row as ObjectRelation)">
                  {{ t('common.delete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div class="link-form">
            <el-select v-model="relationForm.relation_type" style="width: 200px">
              <el-option
                v-for="rt in relationTypes"
                :key="rt"
                :label="t(`structured.relationTypes.${rt}`, rt)"
                :value="rt"
              />
            </el-select>
            <el-select v-model="relationForm.direction" style="width: 160px">
              <el-option :label="t('structured.relationOut')" value="out" />
              <el-option :label="t('structured.relationIn')" value="in" />
            </el-select>
            <el-select
              v-model="relationForm.peer_object_type"
              filterable
              allow-create
              default-first-option
              style="width: 160px"
              :placeholder="t('structured.peerObjectType')"
            >
              <el-option
                v-for="tp in industrialObjectTypes"
                :key="tp"
                :label="t(`structured.objectTypes.${tp}`, tp)"
                :value="tp"
              />
            </el-select>
            <el-input
              v-model="relationForm.peer_object_id"
              :placeholder="t('structured.peerObjectId')"
              style="width: 220px"
            />
            <el-button type="primary" :loading="relationSaving" @click="addRelation">
              {{ t('structured.addRelation') }}
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

    <el-dialog v-model="sourceDialog" :title="t('structured.createSource')" width="560px">
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
        <el-form-item :label="t('structured.connector')">
          <el-select v-model="sourceForm.connector" style="width: 100%">
            <el-option value="none" :label="t('structured.connectorNone')" />
            <el-option value="mysql" label="MySQL" />
            <el-option value="postgres" label="PostgreSQL" />
            <el-option value="mssql" label="SQL Server" />
            <el-option value="mongo" label="MongoDB" />
            <el-option value="csv" label="CSV" />
            <el-option value="rest" label="REST" />
          </el-select>
        </el-form-item>
        <template v-if="sourceForm.connector === 'mysql'">
          <p class="hint">{{ t('structured.mysqlHint') }}</p>
          <el-form-item :label="t('structured.mysqlHost')">
            <el-input v-model="sourceForm.mysql_host" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPort')">
            <el-input-number v-model="sourceForm.mysql_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlDatabase')">
            <el-input v-model="sourceForm.mysql_database" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlUser')">
            <el-input v-model="sourceForm.mysql_user" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPasswordEnv')">
            <el-input v-model="sourceForm.mysql_password_env" placeholder="MES_MYSQL_PASSWORD" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlTable')">
            <el-input v-model="sourceForm.mysql_table" placeholder="device_info" />
          </el-form-item>
        </template>
        <template v-else-if="sourceForm.connector === 'postgres'">
          <p class="hint">{{ t('structured.pgHint') }}</p>
          <el-form-item :label="t('structured.mysqlHost')">
            <el-input v-model="sourceForm.pg_host" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPort')">
            <el-input-number v-model="sourceForm.pg_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlDatabase')">
            <el-input v-model="sourceForm.pg_database" />
          </el-form-item>
          <el-form-item :label="t('structured.pgSchema')">
            <el-input v-model="sourceForm.pg_schema" placeholder="public" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlUser')">
            <el-input v-model="sourceForm.pg_user" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPasswordEnv')">
            <el-input v-model="sourceForm.pg_password_env" placeholder="MES_PG_PASSWORD" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlTable')">
            <el-input v-model="sourceForm.pg_table" placeholder="device_info" />
          </el-form-item>
        </template>
        <template v-else-if="sourceForm.connector === 'mssql'">
          <p class="hint">{{ t('structured.mssqlHint') }}</p>
          <el-form-item :label="t('structured.mysqlHost')">
            <el-input v-model="sourceForm.mssql_host" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPort')">
            <el-input-number v-model="sourceForm.mssql_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlDatabase')">
            <el-input v-model="sourceForm.mssql_database" />
          </el-form-item>
          <el-form-item :label="t('structured.pgSchema')">
            <el-input v-model="sourceForm.mssql_schema" placeholder="dbo" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlUser')">
            <el-input v-model="sourceForm.mssql_user" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPasswordEnv')">
            <el-input v-model="sourceForm.mssql_password_env" placeholder="MES_MSSQL_PASSWORD" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlTable')">
            <el-input v-model="sourceForm.mssql_table" placeholder="device_info" />
          </el-form-item>
        </template>
        <template v-else-if="sourceForm.connector === 'mongo'">
          <p class="hint">{{ t('structured.mongoHint') }}</p>
          <el-form-item :label="t('structured.mysqlHost')">
            <el-input v-model="sourceForm.mongo_host" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPort')">
            <el-input-number v-model="sourceForm.mongo_port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlDatabase')">
            <el-input v-model="sourceForm.mongo_database" />
          </el-form-item>
          <el-form-item :label="t('structured.mongoAuthSource')">
            <el-input v-model="sourceForm.mongo_auth_source" placeholder="admin" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlUser')">
            <el-input v-model="sourceForm.mongo_user" :placeholder="t('structured.mongoUserOptional')" />
          </el-form-item>
          <el-form-item :label="t('structured.mysqlPasswordEnv')">
            <el-input v-model="sourceForm.mongo_password_env" placeholder="MES_MONGO_PASSWORD" />
          </el-form-item>
          <el-form-item :label="t('structured.mongoCollection')">
            <el-input v-model="sourceForm.mongo_collection" placeholder="devices" />
          </el-form-item>
        </template>
        <template v-else-if="sourceForm.connector === 'csv'">
          <el-form-item :label="t('structured.csvDevices')">
            <el-input v-model="sourceForm.csv_devices" placeholder="/data/devices.csv" />
          </el-form-item>
        </template>
        <template v-else-if="sourceForm.connector === 'rest'">
          <el-form-item :label="t('structured.restBaseUrl')">
            <el-input v-model="sourceForm.rest_base_url" placeholder="https://mes.example/api" />
          </el-form-item>
        </template>
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

    <el-dialog v-model="recordDialog" :title="t('structured.createRecord')" width="560px">
      <el-form ref="recordFormRef" :model="recordForm" :rules="recordRules" label-position="top">
        <el-form-item :label="t('structured.sources')" prop="source_id">
          <el-select v-model="recordForm.source_id" style="width: 100%">
            <el-option v-for="s in sources" :key="s.id" :label="s.name" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('structured.objectType')" prop="object_type">
          <el-select
            v-model="recordForm.object_type"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            :placeholder="t('structured.objectTypePlaceholder')"
            @change="onRecordObjectTypeChange"
          >
            <el-option
              v-for="tp in industrialObjectTypes"
              :key="tp"
              :label="t(`structured.objectTypes.${tp}`, tp)"
              :value="tp"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('structured.parentObjectType')">
          <el-input
            v-model="recordForm.parent_object_type"
            :placeholder="t('structured.parentObjectTypeHint')"
          />
        </el-form-item>
        <el-form-item :label="t('structured.parentExternalId')">
          <el-input v-model="recordForm.parent_external_id" />
        </el-form-item>
        <el-alert
          v-if="activeAttrSchema"
          type="info"
          :closable="false"
          show-icon
          class="schema-hint"
          :title="activeAttrSchema.description"
          :description="
            activeAttrSchema.attributes
              .map(
                (a) =>
                  `${a.name}${a.required ? '*' : ''} (${a.kind}${a.unit ? '/' + a.unit : ''})`,
              )
              .join(' · ')
          "
        />
        <el-form-item :label="t('structured.externalId')" prop="external_id">
          <el-input v-model="recordForm.external_id" />
        </el-form-item>
        <el-form-item :label="t('structured.titleCol')" prop="title">
          <el-input v-model="recordForm.title" />
        </el-form-item>
        <el-form-item :label="t('structured.status')">
          <el-input v-model="recordForm.status" />
        </el-form-item>
        <el-form-item :label="t('structured.attrsJson')">
          <el-input
            v-model="recordForm.attrs_json"
            type="textarea"
            :rows="5"
            :placeholder="t('structured.attrsJsonHint')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="recordSaving" @click="submitRecord">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="aclDialog"
      :title="t('structured.aclTitle', { label: selectedObject?.label ?? '' })"
      width="760px"
    >
      <div v-loading="aclLoading">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          :title="t('structured.aclTip')"
          class="schema-hint"
        />
        <AclEditor v-model="aclEntries" />
      </div>
      <template #footer>
        <el-button @click="aclDialog = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="aclSaving" @click="saveAcl">
          {{ t('common.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.schema-hint {
  margin-bottom: 12px;
}
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
