<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  addSemanticAttribute,
  addSemanticEvidence,
  updateSemanticAttribute,
  addSemanticEntity,
  addSemanticMapping,
  batchSetSemanticStatus,
  createSemanticVersion,
  deleteSemanticEvidence,
  getSemanticVersion,
  importOntologySchema,
  listSemanticVersions,
  publishSemanticVersion,
  rollbackSemanticVersion,
  suggestSemanticLabels,
} from '@/api/ontology'
import {
  listMongoCollections,
  listMssqlTables,
  listMysqlTables,
  listPostgresTables,
  listStructuredSources,
  probeMongoCollection,
  probeMssqlTable,
  probeMysqlTable,
  probePostgresTable,
} from '@/api/structured'
import type {
  MysqlColumnInfo,
  MysqlTableInfo,
  SchemaImportIn,
  SchemaTableIn,
  SemanticAttribute,
  SemanticEntity,
  SemanticEvidence,
  SemanticItemStatus,
  SemanticMapping,
  SemanticVersion,
  SemanticVersionDetail,
  StructuredSource,
} from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'
import { layoutOntologyCanvas } from './ontologyCanvasLayout'

const { t } = useI18n()

const versions = ref<SemanticVersion[]>([])
const activeVersionId = ref('')
const detail = ref<SemanticVersionDetail | null>(null)
const loading = ref(false)
const detailLoading = ref(false)

const selectedEntityId = ref('')
const selectedEntityIds = ref<string[]>([])
const selectedAttrIds = ref<string[]>([])

const isDraft = computed(() => detail.value?.status === 'draft')
const canRollback = computed(() => {
  const d = detail.value
  if (!d) return false
  if (d.status === 'archived') return true
  return d.status === 'published' && !d.is_active
})
const selectedEntity = computed(
  () => detail.value?.entities.find((e) => e.id === selectedEntityId.value) ?? null,
)
const entityAttributes = computed(() => {
  if (!detail.value || !selectedEntityId.value) return []
  return detail.value.attributes.filter((a) => a.entity_id === selectedEntityId.value)
})
const mappingsByAttr = computed(() => {
  const map = new Map<string, SemanticMapping[]>()
  for (const m of detail.value?.mappings ?? []) {
    const list = map.get(m.attribute_id) ?? []
    list.push(m)
    map.set(m.attribute_id, list)
  }
  return map
})

function statusTagType(status: string): 'info' | 'success' | 'danger' | 'warning' {
  if (status === 'approved' || status === 'published') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'archived') return 'info'
  return 'warning'
}

function itemStatusLabel(status: string): string {
  if (status === 'approved') return t('ontology.statusApproved')
  if (status === 'rejected') return t('ontology.statusRejected')
  if (status === 'published') return t('ontology.published')
  if (status === 'archived') return t('ontology.archived')
  return t('ontology.statusDraft')
}

function versionStatusLabel(v: SemanticVersion): string {
  if (v.is_active && v.status === 'published') return t('ontology.publishedBadge')
  if (v.status === 'published') return t('ontology.published')
  if (v.status === 'archived') return t('ontology.archived')
  return t('ontology.draft')
}

function representedBy(attrId: string): string {
  const maps = mappingsByAttr.value.get(attrId) ?? []
  if (!maps.length) return '—'
  return maps.map((m) => `${m.table_name}.${m.column_name}`).join(', ')
}

async function loadVersions(): Promise<void> {
  loading.value = true
  try {
    versions.value = await listSemanticVersions()
    if (!activeVersionId.value) {
      const draft = versions.value.find((v) => v.status === 'draft')
      const active = versions.value.find((v) => v.is_active)
      activeVersionId.value = draft?.id ?? active?.id ?? versions.value[0]?.id ?? ''
    }
  } catch {
    ElMessage.error(t('ontology.loadFail'))
  } finally {
    loading.value = false
  }
}

async function loadDetail(): Promise<void> {
  if (!activeVersionId.value) {
    detail.value = null
    return
  }
  detailLoading.value = true
  try {
    detail.value = await getSemanticVersion(activeVersionId.value)
    if (
      selectedEntityId.value &&
      !detail.value.entities.some((e) => e.id === selectedEntityId.value)
    ) {
      selectedEntityId.value = ''
    }
    if (!selectedEntityId.value && detail.value.entities.length) {
      selectedEntityId.value = detail.value.entities[0]!.id
    }
    selectedEntityIds.value = []
    selectedAttrIds.value = []
  } catch {
    ElMessage.error(t('ontology.loadFail'))
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

watch(activeVersionId, () => {
  selectedEntityId.value = ''
  void loadDetail()
})

onMounted(async () => {
  await loadVersions()
  await loadDetail()
})

/* ---- create version ---- */
const versionDialog = ref(false)
const versionSaving = ref(false)
const versionFormRef = ref<FormInstance>()
const versionForm = reactive({ name: '', notes: '' })
const versionRules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('ontology.versionNameRequired'), trigger: 'blur' }],
}))

function openCreateVersion(): void {
  versionForm.name = ''
  versionForm.notes = ''
  versionDialog.value = true
}

async function submitVersion(): Promise<void> {
  if (!(await versionFormRef.value?.validate().catch(() => false))) return
  versionSaving.value = true
  try {
    const created = await createSemanticVersion({
      name: versionForm.name.trim(),
      notes: versionForm.notes.trim() || null,
    })
    versionDialog.value = false
    ElMessage.success(t('ontology.saveOk'))
    await loadVersions()
    activeVersionId.value = created.id
  } finally {
    versionSaving.value = false
  }
}

/* ---- entity / attr / mapping dialogs ---- */
const entityDialog = ref(false)
const entitySaving = ref(false)
const entityFormRef = ref<FormInstance>()
const entityForm = reactive({
  local_name: '',
  label: '',
  description: '',
  object_type: '',
})
const entityRules = computed<FormRules>(() => ({
  local_name: [{ required: true, message: t('ontology.entityLocalRequired'), trigger: 'blur' }],
  label: [{ required: true, message: t('ontology.entityLabelRequired'), trigger: 'blur' }],
}))

function openAddEntity(): void {
  entityForm.local_name = ''
  entityForm.label = ''
  entityForm.description = ''
  entityForm.object_type = ''
  entityDialog.value = true
}

async function submitEntity(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  if (!(await entityFormRef.value?.validate().catch(() => false))) return
  entitySaving.value = true
  try {
    const created = await addSemanticEntity(detail.value.id, {
      local_name: entityForm.local_name.trim(),
      label: entityForm.label.trim(),
      description: entityForm.description.trim() || null,
      object_type: entityForm.object_type.trim() || null,
    })
    entityDialog.value = false
    ElMessage.success(t('ontology.saveOk'))
    await loadDetail()
    selectedEntityId.value = created.id
  } finally {
    entitySaving.value = false
  }
}

const attrDialog = ref(false)
const attrSaving = ref(false)
const attrEditingId = ref<string | null>(null)
const attrFormRef = ref<FormInstance>()
const attrForm = reactive({
  name: '',
  label: '',
  description: '',
  attr_kind: 'string',
  unit: '',
  enum_map_json: '',
  label_zh: '',
  label_en: '',
  label_vi: '',
  compute_expr: '',
  compute_inputs: '',
})

const evidenceForm = reactive({
  target_kind: 'entity' as 'entity' | 'attribute',
  target_id: '',
  evidence_kind: 'document' as 'ko' | 'document' | 'chunk',
  evidence_id: '',
  note: '',
})
const evidenceSaving = ref(false)

const entityEvidences = computed(() => {
  const list = detail.value?.evidences ?? []
  if (!selectedEntityId.value) return []
  const attrIds = new Set(entityAttributes.value.map((a) => a.id))
  return list.filter(
    (e) =>
      (e.target_kind === 'entity' && e.target_id === selectedEntityId.value) ||
      (e.target_kind === 'attribute' && attrIds.has(e.target_id)),
  )
})
const attrRules = computed<FormRules>(() => ({
  name: [{ required: true, message: t('ontology.attrNameRequired'), trigger: 'blur' }],
  label: [{ required: true, message: t('ontology.attrLabelRequired'), trigger: 'blur' }],
}))

function resetAttrForm(): void {
  attrForm.name = ''
  attrForm.label = ''
  attrForm.description = ''
  attrForm.attr_kind = 'string'
  attrForm.unit = ''
  attrForm.enum_map_json = ''
  attrForm.label_zh = ''
  attrForm.label_en = ''
  attrForm.label_vi = ''
  attrForm.compute_expr = ''
  attrForm.compute_inputs = ''
  attrEditingId.value = null
}

function openAddAttribute(): void {
  if (!selectedEntityId.value) {
    ElMessage.warning(t('ontology.selectEntity'))
    return
  }
  resetAttrForm()
  attrDialog.value = true
}

function openEditAttribute(attr: SemanticAttribute): void {
  if (!isDraft.value) return
  attrEditingId.value = attr.id
  attrForm.name = attr.name
  attrForm.label = attr.label
  attrForm.description = attr.description || ''
  attrForm.attr_kind = attr.attr_kind || 'string'
  attrForm.unit = attr.unit || ''
  attrForm.enum_map_json = attr.enum_map && Object.keys(attr.enum_map).length
    ? JSON.stringify(attr.enum_map, null, 2)
    : ''
  attrForm.label_zh = attr.labels?.zh || ''
  attrForm.label_en = attr.labels?.en || ''
  attrForm.label_vi = attr.labels?.vi || ''
  attrForm.compute_expr = attr.compute_expr || ''
  attrForm.compute_inputs = (attr.compute_inputs || []).join(', ')
  attrDialog.value = true
}

function parseEnumMapJson(): Record<string, unknown> | null {
  const text = attrForm.enum_map_json.trim()
  if (!text) return {}
  try {
    const parsed = JSON.parse(text) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    /* fall through */
  }
  ElMessage.error(t('ontology.attrEnumMapHint'))
  return null
}

async function submitAttribute(): Promise<void> {
  if (!isDraft.value) return
  if (!(await attrFormRef.value?.validate().catch(() => false))) return
  const enumMap = parseEnumMapJson()
  if (enumMap === null) return
  const labels: Record<string, string> = {}
  if (attrForm.label_zh.trim()) labels.zh = attrForm.label_zh.trim()
  if (attrForm.label_en.trim()) labels.en = attrForm.label_en.trim()
  if (attrForm.label_vi.trim()) labels.vi = attrForm.label_vi.trim()
  const computeExpr = attrForm.compute_expr.trim() || null
  const computeInputs = attrForm.compute_inputs
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  attrSaving.value = true
  try {
    if (attrEditingId.value) {
      await updateSemanticAttribute(attrEditingId.value, {
        label: attrForm.label.trim(),
        description: attrForm.description.trim() || null,
        attr_kind: attrForm.attr_kind.trim() || 'string',
        unit: attrForm.unit.trim() || null,
        enum_map: enumMap,
        labels,
        compute_expr: computeExpr,
        compute_inputs: computeInputs,
      })
    } else {
      if (!selectedEntityId.value) return
      await addSemanticAttribute(selectedEntityId.value, {
        name: attrForm.name.trim(),
        label: attrForm.label.trim(),
        description: attrForm.description.trim() || null,
        attr_kind: attrForm.attr_kind.trim() || 'string',
        unit: attrForm.unit.trim() || null,
        enum_map: enumMap,
        labels,
        compute_expr: computeExpr,
        compute_inputs: computeInputs,
      })
    }
    attrDialog.value = false
    ElMessage.success(t('ontology.saveOk'))
    await loadDetail()
  } finally {
    attrSaving.value = false
  }
}

const mappingDialog = ref(false)
const mappingSaving = ref(false)
const mappingAttrId = ref('')
const mappingFormRef = ref<FormInstance>()
const mappingForm = reactive({
  table_name: '',
  column_name: '',
  source_id: '',
  source_of_truth: false,
  freshness_sla_seconds: null as number | null,
})
const mappingRules = computed<FormRules>(() => ({
  table_name: [{ required: true, message: t('ontology.tableRequired'), trigger: 'blur' }],
  column_name: [{ required: true, message: t('ontology.columnRequired'), trigger: 'blur' }],
}))

function openAddMapping(attr: SemanticAttribute | Record<string, unknown>): void {
  mappingAttrId.value = String((attr as SemanticAttribute).id)
  mappingForm.table_name = ''
  mappingForm.column_name = ''
  mappingForm.source_id = ''
  mappingForm.source_of_truth = false
  mappingForm.freshness_sla_seconds = null
  mappingDialog.value = true
}

async function submitEvidence(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  if (!evidenceForm.evidence_id.trim()) {
    ElMessage.warning(t('ontology.evidenceIdRequired'))
    return
  }
  const targetId =
    evidenceForm.target_kind === 'entity'
      ? selectedEntityId.value
      : evidenceForm.target_id || selectedAttrIds.value[0] || ''
  if (!targetId) {
    ElMessage.warning(t('ontology.selectEntity'))
    return
  }
  evidenceSaving.value = true
  try {
    await addSemanticEvidence(detail.value.id, {
      target_kind: evidenceForm.target_kind,
      target_id: targetId,
      evidence_kind: evidenceForm.evidence_kind,
      evidence_id: evidenceForm.evidence_id.trim(),
      note: evidenceForm.note.trim() || null,
    })
    evidenceForm.evidence_id = ''
    evidenceForm.note = ''
    ElMessage.success(t('ontology.saveOk'))
    await loadDetail()
  } finally {
    evidenceSaving.value = false
  }
}

async function removeEvidence(row: SemanticEvidence): Promise<void> {
  if (!isDraft.value) return
  await deleteSemanticEvidence(row.id)
  ElMessage.success(t('ontology.saveOk'))
  await loadDetail()
}

async function submitMapping(): Promise<void> {
  if (!mappingAttrId.value || !isDraft.value) return
  if (!(await mappingFormRef.value?.validate().catch(() => false))) return
  mappingSaving.value = true
  try {
    await addSemanticMapping(mappingAttrId.value, {
      table_name: mappingForm.table_name.trim(),
      column_name: mappingForm.column_name.trim(),
      source_id: mappingForm.source_id.trim() || null,
      source_of_truth: mappingForm.source_of_truth,
      freshness_sla_seconds: mappingForm.freshness_sla_seconds || null,
    })
    mappingDialog.value = false
    ElMessage.success(t('ontology.saveOk'))
    await loadDetail()
  } finally {
    mappingSaving.value = false
  }
}

/* ---- batch / suggest / publish ---- */
const actionBusy = ref(false)

async function runBatch(status: SemanticItemStatus): Promise<void> {
  if (!detail.value || !isDraft.value) return
  if (!selectedEntityIds.value.length && !selectedAttrIds.value.length) {
    ElMessage.warning(t('ontology.batchNeedSelection'))
    return
  }
  actionBusy.value = true
  try {
    const mappingIds = (detail.value.mappings ?? [])
      .filter((m) => selectedAttrIds.value.includes(m.attribute_id))
      .map((m) => m.id)
    const out = await batchSetSemanticStatus(detail.value.id, {
      entity_ids: selectedEntityIds.value,
      attribute_ids: selectedAttrIds.value,
      mapping_ids: mappingIds,
      status,
    })
    ElMessage.success(
      t('ontology.batchOk', {
        e: out.entities_updated,
        a: out.attributes_updated,
        m: out.mappings_updated,
      }),
    )
    await loadDetail()
  } finally {
    actionBusy.value = false
  }
}

interface SuggestRow {
  kind: string
  id: string
  code: string
  before_label: string
  label: string
  before_extra: string
  extra: string
  selected: boolean
}

const suggestDialog = ref(false)
const suggestRows = ref<SuggestRow[]>([])
const suggestApplying = ref(false)

async function openSuggestPreview(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  actionBusy.value = true
  try {
    const out = await suggestSemanticLabels(detail.value.id, true)
    suggestRows.value = (out.suggestions || []).map((s) => {
      const kind = String(s.kind || '')
      const code = kind === 'entity' ? String(s.local_name || '') : String(s.name || '')
      const beforeExtra =
        kind === 'entity'
          ? String(s.before_object_type || '')
          : String(s.before_attr_kind || '')
      const extra =
        kind === 'entity' ? String(s.object_type || '') : String(s.attr_kind || '')
      return {
        kind,
        id: String(s.id || ''),
        code,
        before_label: String(s.before_label || ''),
        label: String(s.label || ''),
        before_extra: beforeExtra,
        extra,
        selected: true,
      }
    })
    if (!suggestRows.value.length) {
      ElMessage.info(t('ontology.suggestEmpty'))
      return
    }
    suggestDialog.value = true
  } catch {
    ElMessage.error(t('ontology.suggestFail'))
  } finally {
    actionBusy.value = false
  }
}

async function applySuggest(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  suggestApplying.value = true
  try {
    const out = await suggestSemanticLabels(detail.value.id, false)
    suggestDialog.value = false
    ElMessage.success(
      t('ontology.suggestOk', {
        entities: out.entities_updated,
        attrs: out.attributes_updated,
      }),
    )
    await loadDetail()
  } catch {
    ElMessage.error(t('ontology.suggestFail'))
  } finally {
    suggestApplying.value = false
  }
}

async function approveAllDraft(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  const entityIds = detail.value.entities
    .filter((e) => e.status === 'draft')
    .map((e) => e.id)
  const attrIds = detail.value.attributes
    .filter((a) => a.status === 'draft')
    .map((a) => a.id)
  const mappingIds = (detail.value.mappings ?? [])
    .filter((m) => m.status === 'draft')
    .map((m) => m.id)
  if (!entityIds.length && !attrIds.length && !mappingIds.length) {
    ElMessage.warning(t('ontology.approveAllEmpty'))
    return
  }
  actionBusy.value = true
  try {
    const out = await batchSetSemanticStatus(detail.value.id, {
      entity_ids: entityIds,
      attribute_ids: attrIds,
      mapping_ids: mappingIds,
      status: 'approved',
    })
    ElMessage.success(
      t('ontology.batchOk', {
        e: out.entities_updated,
        a: out.attributes_updated,
        m: out.mappings_updated,
      }),
    )
    await loadDetail()
  } finally {
    actionBusy.value = false
  }
}

/* ---- connect MySQL → import schema ---- */
const dbDialog = ref(false)
const dbStep = ref(0)
const dbBusy = ref(false)
type DbEngine = 'mysql' | 'postgres' | 'mongo' | 'mssql'
const dbEngine = ref<DbEngine>('mysql')
const dbMode = ref<'manual' | 'source'>('manual')
const engineSources = ref<StructuredSource[]>([])
const dbForm = reactive({
  source_id: '',
  host: '127.0.0.1',
  port: 3306,
  database: '',
  user: '',
  password_env: 'MES_MYSQL_PASSWORD',
  password: '',
  charset: 'utf8mb4',
  schema: 'public',
  auth_source: 'admin',
})
const dbTables = ref<MysqlTableInfo[]>([])
const selectedTableNames = ref<string[]>([])
const probedTables = ref<
  { name: string; columns: MysqlColumnInfo[]; row_count: number; comment?: string | null }[]
>([])
const dbAutoApprove = ref(false)

function defaultPasswordEnv(engine: DbEngine): string {
  if (engine === 'postgres') return 'MES_PG_PASSWORD'
  if (engine === 'mongo') return 'MES_MONGO_PASSWORD'
  if (engine === 'mssql') return 'MES_MSSQL_PASSWORD'
  return 'MES_MYSQL_PASSWORD'
}

function defaultPort(engine: DbEngine): number {
  if (engine === 'postgres') return 5432
  if (engine === 'mongo') return 27017
  if (engine === 'mssql') return 1433
  return 3306
}

function defaultSchema(engine: DbEngine): string {
  if (engine === 'mssql') return 'dbo'
  return 'public'
}

function onEngineChange(engine: DbEngine): void {
  dbEngine.value = engine
  dbForm.port = defaultPort(engine)
  dbForm.password_env = defaultPasswordEnv(engine)
  dbForm.schema = defaultSchema(engine)
  dbForm.source_id = ''
  refreshEngineSources()
}

function dbConnectBody() {
  const passwordEnv = dbForm.password_env || defaultPasswordEnv(dbEngine.value)
  if (dbMode.value === 'source' && dbForm.source_id) {
    return {
      source_id: dbForm.source_id,
      host: dbForm.host || 'unused',
      database: dbForm.database || 'unused',
      user: dbForm.user || (dbEngine.value === 'mongo' ? '' : 'unused'),
      password_env: passwordEnv,
      password: dbForm.password || null,
      charset: dbForm.charset,
      schema: dbForm.schema || defaultSchema(dbEngine.value),
      auth_source: dbForm.auth_source || 'admin',
      port: dbForm.port,
    }
  }
  return {
    host: dbForm.host.trim(),
    port: dbForm.port,
    database: dbForm.database.trim(),
    user: dbForm.user.trim(),
    password_env: dbForm.password_env.trim() || defaultPasswordEnv(dbEngine.value),
    password: dbForm.password || null,
    charset: dbForm.charset,
    schema: dbForm.schema.trim() || defaultSchema(dbEngine.value),
    auth_source: dbForm.auth_source.trim() || 'admin',
  }
}

async function refreshEngineSources(): Promise<void> {
  try {
    const sources = await listStructuredSources()
    engineSources.value = sources.filter((s) => s.meta?.connector === dbEngine.value)
  } catch {
    engineSources.value = []
  }
}

async function openConnectDb(): Promise<void> {
  dbStep.value = 0
  dbTables.value = []
  selectedTableNames.value = []
  probedTables.value = []
  await refreshEngineSources()
  dbDialog.value = true
}

async function dbListTables(): Promise<void> {
  if (dbMode.value === 'manual') {
    const needUser = dbEngine.value !== 'mongo'
    if (
      !dbForm.host.trim() ||
      !dbForm.database.trim() ||
      (needUser && !dbForm.user.trim())
    ) {
      ElMessage.warning(t('ontology.dbConnectRequired'))
      return
    }
  } else if (!dbForm.source_id) {
    ElMessage.warning(t('ontology.dbSourceRequired'))
    return
  }
  dbBusy.value = true
  try {
    const body = dbConnectBody()
    const out =
      dbEngine.value === 'postgres'
        ? await listPostgresTables(body)
        : dbEngine.value === 'mongo'
          ? await listMongoCollections(body)
          : dbEngine.value === 'mssql'
            ? await listMssqlTables(body)
            : await listMysqlTables(body)
    dbTables.value =
      dbEngine.value === 'mongo'
        ? out.tables
        : out.tables.filter((t) => t.table_type !== 'VIEW')
    selectedTableNames.value = []
    dbStep.value = 1
    if (!dbTables.value.length) {
      ElMessage.warning(
        dbEngine.value === 'mongo' ? t('ontology.dbNoCollections') : t('ontology.dbNoTables'),
      )
    }
  } catch {
    ElMessage.error(t('ontology.dbConnectFail'))
  } finally {
    dbBusy.value = false
  }
}

async function dbProbeSelected(): Promise<void> {
  if (!selectedTableNames.value.length) {
    ElMessage.warning(
      dbEngine.value === 'mongo' ? t('ontology.dbSelectCollections') : t('ontology.dbSelectTables'),
    )
    return
  }
  dbBusy.value = true
  try {
    const body = dbConnectBody()
    const results = []
    for (const name of selectedTableNames.value) {
      const probed =
        dbEngine.value === 'postgres'
          ? await probePostgresTable({ ...body, table: name, sample_limit: 2 })
          : dbEngine.value === 'mongo'
            ? await probeMongoCollection({ ...body, table: name, sample_limit: 2 })
            : dbEngine.value === 'mssql'
              ? await probeMssqlTable({ ...body, table: name, sample_limit: 2 })
              : await probeMysqlTable({ ...body, table: name, sample_limit: 2 })
      const meta = dbTables.value.find((t) => t.name === name)
      results.push({
        name: probed.table,
        columns: probed.columns,
        row_count: probed.row_count,
        comment: meta?.comment ?? null,
      })
    }
    probedTables.value = results
    dbStep.value = 2
  } catch {
    ElMessage.error(t('ontology.dbProbeFail'))
  } finally {
    dbBusy.value = false
  }
}

async function dbImportSchema(): Promise<void> {
  if (!probedTables.value.length) return
  const tables: SchemaTableIn[] = probedTables.value.map((t) => ({
    name: t.name,
    comment: t.comment || null,
    columns: t.columns.map((c) => ({
      name: c.name,
      data_type: c.type,
      comment: null,
    })),
  }))
  dbBusy.value = true
  try {
    const body: SchemaImportIn = {
      tables,
      source_id: dbMode.value === 'source' ? dbForm.source_id || null : null,
      auto_approve: dbAutoApprove.value,
    }
    if (detail.value?.status === 'draft') {
      body.version_id = detail.value.id
    } else {
      body.version_name = `import-${new Date().toISOString().slice(0, 10)}`
    }
    const out = await importOntologySchema(body)
    dbDialog.value = false
    ElMessage.success(
      t('ontology.importOk', {
        entities: out.stats.entities_created,
        attrs: out.stats.attributes_created,
        maps: out.stats.mappings_created,
      }),
    )
    await loadVersions()
    activeVersionId.value = out.version.id
    await loadDetail()
  } catch {
    ElMessage.error(t('ontology.importFail'))
  } finally {
    dbBusy.value = false
  }
}

async function runPublish(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  const approved = detail.value.entities.some((e) => e.status === 'approved')
  if (!approved) {
    ElMessage.warning(t('ontology.publishNeedApproved'))
    return
  }
  try {
    await ElMessageBox.confirm(t('ontology.publishConfirm'), t('ontology.publish'), {
      type: 'warning',
    })
  } catch {
    return
  }
  actionBusy.value = true
  try {
    await publishSemanticVersion(detail.value.id)
    ElMessage.success(t('ontology.publishOk'))
    await loadVersions()
    await loadDetail()
  } catch {
    ElMessage.error(t('ontology.publishFail'))
  } finally {
    actionBusy.value = false
  }
}

async function runRollback(): Promise<void> {
  if (!detail.value || !canRollback.value) return
  try {
    await ElMessageBox.confirm(t('ontology.rollbackConfirm'), t('ontology.rollback'), {
      type: 'warning',
    })
  } catch {
    return
  }
  actionBusy.value = true
  try {
    await rollbackSemanticVersion(detail.value.id)
    ElMessage.success(t('ontology.rollbackOk'))
    await loadVersions()
    await loadDetail()
  } catch {
    ElMessage.error(t('ontology.rollbackFail'))
  } finally {
    actionBusy.value = false
  }
}

/* ---- schema import ---- */
const importDialog = ref(false)
const importSaving = ref(false)
const importJson = ref(
  JSON.stringify(
    {
      tables: [
        {
          name: 'equip_device',
          comment: '设备',
          columns: [
            { name: 'external_id', data_type: 'varchar', comment: '设备编号' },
            { name: 'name', data_type: 'varchar', comment: '名称' },
          ],
        },
      ],
    },
    null,
    2,
  ),
)
const importAutoApprove = ref(false)

function openImport(): void {
  importDialog.value = true
}

async function submitImport(): Promise<void> {
  let parsed: { tables?: SchemaImportIn['tables']; source_id?: string }
  try {
    parsed = JSON.parse(importJson.value) as {
      tables?: SchemaImportIn['tables']
      source_id?: string
    }
  } catch {
    ElMessage.error(t('ontology.importJsonInvalid'))
    return
  }
  if (!Array.isArray(parsed.tables) || !parsed.tables.length) {
    ElMessage.error(t('ontology.importJsonInvalid'))
    return
  }
  importSaving.value = true
  try {
    const body: SchemaImportIn = {
      tables: parsed.tables,
      source_id: parsed.source_id ?? null,
      auto_approve: importAutoApprove.value,
    }
    if (detail.value?.status === 'draft') {
      body.version_id = detail.value.id
    } else {
      body.version_name = `import-${new Date().toISOString().slice(0, 10)}`
    }
    const out = await importOntologySchema(body)
    importDialog.value = false
    ElMessage.success(
      t('ontology.importOk', {
        entities: out.stats.entities_created,
        attrs: out.stats.attributes_created,
        maps: out.stats.mappings_created,
      }),
    )
    await loadVersions()
    activeVersionId.value = out.version.id
    await loadDetail()
  } catch {
    ElMessage.error(t('ontology.importFail'))
  } finally {
    importSaving.value = false
  }
}

function onEntityRowClick(row: SemanticEntity): void {
  selectedEntityId.value = row.id
}

function entityRowClassName({ row }: { row: SemanticEntity }): string {
  return row.id === selectedEntityId.value ? 'is-current' : ''
}

function onEntitySelectionChange(rows: SemanticEntity[]): void {
  selectedEntityIds.value = rows.map((r) => r.id)
}

function onAttrSelectionChange(rows: SemanticAttribute[]): void {
  selectedAttrIds.value = rows.map((r) => r.id)
}

/* ---- relation canvas (Wave B Task9) ---- */
const canvasInspectorId = ref<string | null>(null)
const canvasMode = ref<'table' | 'canvas'>('table')

interface CanvasEdge {
  from: string
  to: string
  label: string
}

const canvasLayout = computed(() => {
  if (!detail.value) return { nodes: [], width: 720, height: 420 }
  return layoutOntologyCanvas(detail.value.entities, detail.value.attributes)
})

const canvasNodes = computed(() => canvasLayout.value.nodes)

const canvasEdges = computed<CanvasEdge[]>(() => {
  if (!detail.value) return []
  return detail.value.attributes.map((a) => ({
    from: `e:${a.entity_id}`,
    to: `a:${a.id}`,
    label: 'has',
  }))
})

const canvasNodeMap = computed(() => {
  const map = new Map<string, (typeof canvasNodes.value)[number]>()
  for (const n of canvasNodes.value) map.set(n.id, n)
  return map
})

const canvasInspector = computed(() => {
  if (!detail.value || !canvasInspectorId.value) return null
  const id = canvasInspectorId.value
  if (id.startsWith('e:')) {
    const ent = detail.value.entities.find((e) => e.id === id.slice(2))
    if (!ent) return null
    return {
      kind: 'entity' as const,
      title: ent.label,
      rows: [
        ['local_name', ent.local_name],
        ['object_type', ent.object_type || '-'],
        ['status', ent.status],
        ['description', ent.description || '-'],
      ],
    }
  }
  if (id.startsWith('a:')) {
    const attr = detail.value.attributes.find((a) => a.id === id.slice(2))
    if (!attr) return null
    const maps = (detail.value.mappings ?? []).filter((m) => m.attribute_id === attr.id)
    return {
      kind: 'attribute' as const,
      title: attr.label,
      rows: [
        ['name', attr.name],
        ['kind', attr.attr_kind],
        ['unit', attr.unit || '-'],
        ['status', attr.status],
        [
          'represented_by',
          maps.map((m) => `${m.table_name}.${m.column_name}`).join(', ') || '-',
        ],
      ],
    }
  }
  return null
})

function selectCanvasNode(id: string): void {
  canvasInspectorId.value = id
  if (id.startsWith('e:')) {
    selectedEntityId.value = id.slice(2)
  }
}
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-header">
        <div>
          <h2>{{ t('ontology.title') }}</h2>
          <p class="hint">{{ t('ontology.hint') }}</p>
        </div>
        <div class="header-actions">
          <el-button type="primary" plain @click="openConnectDb">
            {{ t('ontology.connectDb') }}
          </el-button>
          <el-button @click="openCreateVersion">{{ t('ontology.createVersion') }}</el-button>
          <el-button @click="openImport">{{ t('ontology.importSchema') }}</el-button>
          <el-button
            :disabled="!isDraft"
            :loading="actionBusy"
            @click="openSuggestPreview"
          >
            {{ t('ontology.suggest') }}
          </el-button>
          <el-button
            type="primary"
            :disabled="!isDraft"
            :loading="actionBusy"
            @click="runPublish"
          >
            {{ t('ontology.publish') }}
          </el-button>
          <el-button
            type="warning"
            plain
            :disabled="!canRollback"
            :loading="actionBusy"
            @click="runRollback"
          >
            {{ t('ontology.rollback') }}
          </el-button>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="studio-layout">
      <aside class="version-pane">
        <div class="pane-title">{{ t('ontology.versions') }}</div>
        <EmptyState v-if="!versions.length" :description="t('ontology.emptyVersions')" />
        <el-menu
          v-else
          :default-active="activeVersionId"
          @select="(id: string) => (activeVersionId = id)"
        >
          <el-menu-item v-for="v in versions" :key="v.id" :index="v.id">
            <div class="version-item">
              <span class="version-name">{{ v.name }}</span>
              <el-tag size="small" :type="statusTagType(v.status)" effect="plain">
                {{ versionStatusLabel(v) }}
              </el-tag>
            </div>
          </el-menu-item>
        </el-menu>
      </aside>

      <section v-loading="detailLoading" class="detail-pane">
        <EmptyState v-if="!detail" :description="t('ontology.selectVersion')" />
        <template v-else>
          <div class="detail-meta">
            <div>
              <strong>{{ detail.name }}</strong>
              <el-tag class="ml" size="small" :type="statusTagType(detail.status)">
                {{ versionStatusLabel(detail) }}
              </el-tag>
              <span v-if="!isDraft" class="readonly">{{ t('ontology.readOnly') }}</span>
            </div>
            <div class="meta-sub">
              <span v-if="detail.published_at">
                {{ formatDateTime(detail.published_at) }}
              </span>
              <span v-else>{{ formatDateTime(detail.created_at) }}</span>
              <span v-if="detail.notes"> · {{ detail.notes }}</span>
            </div>
          </div>

          <div class="toolbar">
            <el-radio-group v-model="canvasMode" size="small" class="view-toggle">
              <el-radio-button value="table">{{ t('ontology.viewTable') }}</el-radio-button>
              <el-radio-button value="canvas">{{ t('ontology.viewCanvas') }}</el-radio-button>
            </el-radio-group>
            <el-button size="small" :disabled="!isDraft" @click="openAddEntity">
              {{ t('ontology.addEntity') }}
            </el-button>
            <el-button
              size="small"
              type="success"
              plain
              :disabled="!isDraft"
              :loading="actionBusy"
              @click="runBatch('approved')"
            >
              {{ t('ontology.batchApprove') }}
            </el-button>
            <el-button
              size="small"
              type="success"
              :disabled="!isDraft"
              :loading="actionBusy"
              @click="approveAllDraft"
            >
              {{ t('ontology.approveAll') }}
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="!isDraft"
              :loading="actionBusy"
              @click="runBatch('rejected')"
            >
              {{ t('ontology.batchReject') }}
            </el-button>
          </div>

          <div v-if="canvasMode === 'canvas'" class="canvas-split">
            <div class="relation-canvas-scroll">
              <svg
                class="relation-canvas"
                :viewBox="`0 0 ${canvasLayout.width} ${canvasLayout.height}`"
                :width="canvasLayout.width"
                :height="canvasLayout.height"
                role="img"
                :aria-label="t('ontology.viewCanvas')"
              >
                <defs>
                  <marker
                    id="arrow"
                    viewBox="0 0 10 10"
                    refX="8"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse"
                  >
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b" />
                  </marker>
                </defs>
                <g v-for="(edge, idx) in canvasEdges" :key="'edge-' + idx">
                  <line
                    v-if="canvasNodeMap.get(edge.from) && canvasNodeMap.get(edge.to)"
                    :x1="canvasNodeMap.get(edge.from)!.x"
                    :y1="canvasNodeMap.get(edge.from)!.y"
                    :x2="canvasNodeMap.get(edge.to)!.x"
                    :y2="canvasNodeMap.get(edge.to)!.y"
                    stroke="#94a3b8"
                    stroke-width="1.5"
                    marker-end="url(#arrow)"
                  />
                </g>
                <g
                  v-for="node in canvasNodes"
                  :key="node.id"
                  class="canvas-node"
                  :class="{ active: canvasInspectorId === node.id }"
                  @click="selectCanvasNode(node.id)"
                >
                  <rect
                    v-if="node.kind === 'entity'"
                    :x="node.x - 48"
                    :y="node.y - 18"
                    width="96"
                    height="36"
                    rx="8"
                    fill="#1d4ed8"
                  />
                  <rect
                    v-else
                    :x="node.x - 42"
                    :y="node.y - 14"
                    width="84"
                    height="28"
                    rx="6"
                    fill="#0f766e"
                  />
                  <text
                    :x="node.x"
                    :y="node.y + 4"
                    text-anchor="middle"
                    fill="#fff"
                    font-size="11"
                  >
                    {{ node.label.length > 10 ? node.label.slice(0, 10) + '…' : node.label }}
                  </text>
                </g>
              </svg>
            </div>
            <aside class="canvas-inspector">
              <div class="pane-title">{{ t('ontology.inspector') }}</div>
              <EmptyState
                v-if="!canvasInspector"
                :description="t('ontology.inspectorHint')"
              />
              <template v-else>
                <div class="inspector-title">{{ canvasInspector.title }}</div>
                <dl class="inspector-dl">
                  <template v-for="[k, v] in canvasInspector.rows" :key="k">
                    <dt>{{ k }}</dt>
                    <dd>{{ v }}</dd>
                  </template>
                </dl>
              </template>
            </aside>
          </div>

          <div v-else class="tables-split">
            <div class="entities-col">
              <div class="pane-title">{{ t('ontology.entities') }}</div>
              <el-table
                :data="detail.entities"
                size="small"
                highlight-current-row
                :row-class-name="entityRowClassName"
                @row-click="onEntityRowClick"
                @selection-change="onEntitySelectionChange"
              >
                <el-table-column v-if="isDraft" type="selection" width="40" />
                <el-table-column prop="local_name" :label="t('ontology.localName')" min-width="100" />
                <el-table-column prop="label" :label="t('ontology.label')" min-width="120" />
                <el-table-column prop="object_type" :label="t('ontology.objectType')" width="110" />
                <el-table-column :label="t('common.status')" width="100">
                  <template #default="{ row }">
                    <el-tag size="small" :type="statusTagType(row.status)" effect="plain">
                      {{ itemStatusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <template #empty>
                  <span>{{ t('ontology.emptyEntities') }}</span>
                </template>
              </el-table>
            </div>

            <div class="attrs-col">
              <div class="pane-title-row">
                <div class="pane-title">
                  {{ t('ontology.attributes') }}
                  <span v-if="selectedEntity" class="sub">
                    · {{ selectedEntity.label }}
                  </span>
                </div>
                <div>
                  <el-button
                    size="small"
                    :disabled="!isDraft || !selectedEntityId"
                    @click="openAddAttribute"
                  >
                    {{ t('ontology.addAttribute') }}
                  </el-button>
                </div>
              </div>
              <EmptyState
                v-if="!selectedEntityId"
                :description="t('ontology.selectEntity')"
              />
              <el-table
                v-else
                :data="entityAttributes"
                size="small"
                @selection-change="onAttrSelectionChange"
              >
                <el-table-column v-if="isDraft" type="selection" width="40" />
                <el-table-column prop="name" :label="t('ontology.attrName')" min-width="100" />
                <el-table-column prop="label" :label="t('ontology.label')" min-width="110" />
                <el-table-column prop="attr_kind" :label="t('ontology.attrKind')" width="90" />
                <el-table-column prop="unit" :label="t('ontology.attrUnit')" width="70" />
                <el-table-column :label="t('ontology.representedBy')" min-width="160">
                  <template #default="{ row }">
                    <span>{{ representedBy(row.id) }}</span>
                  </template>
                </el-table-column>
                <el-table-column :label="t('common.status')" width="100">
                  <template #default="{ row }">
                    <el-tag size="small" :type="statusTagType(row.status)" effect="plain">
                      {{ itemStatusLabel(row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column v-if="isDraft" width="160" fixed="right">
                  <template #default="{ row }">
                    <el-button
                      link
                      type="primary"
                      @click.stop="openEditAttribute(row as SemanticAttribute)"
                    >
                      {{ t('ontology.editAttribute') }}
                    </el-button>
                    <el-button
                      link
                      type="primary"
                      @click.stop="openAddMapping(row as SemanticAttribute)"
                    >
                      {{ t('ontology.addMapping') }}
                    </el-button>
                  </template>
                </el-table-column>
                <template #empty>
                  <span>{{ t('ontology.noAttributes') }}</span>
                </template>
              </el-table>

              <div v-if="selectedEntityId" class="evidence-panel">
                <div class="pane-title-row">
                  <div class="pane-title">{{ t('ontology.evidence') }}</div>
                </div>
                <p class="sub">{{ t('ontology.evidenceHint') }}</p>
                <el-table :data="entityEvidences" size="small">
                  <el-table-column prop="target_kind" :label="t('ontology.evidenceTarget')" width="90" />
                  <el-table-column prop="evidence_kind" :label="t('ontology.evidenceKind')" width="100" />
                  <el-table-column prop="evidence_id" :label="t('ontology.evidenceId')" min-width="120" />
                  <el-table-column prop="note" :label="t('ontology.evidenceNote')" min-width="120" />
                  <el-table-column v-if="isDraft" width="80">
                    <template #default="{ row }">
                      <el-button link type="danger" @click="removeEvidence(row as SemanticEvidence)">
                        {{ t('ontology.deleteEvidence') }}
                      </el-button>
                    </template>
                  </el-table-column>
                  <template #empty>
                    <span>{{ t('ontology.evidenceEmpty') }}</span>
                  </template>
                </el-table>
                <div v-if="isDraft" class="evidence-form">
                  <el-select v-model="evidenceForm.target_kind" style="width: 110px">
                    <el-option label="entity" value="entity" />
                    <el-option label="attribute" value="attribute" />
                  </el-select>
                  <el-select
                    v-if="evidenceForm.target_kind === 'attribute'"
                    v-model="evidenceForm.target_id"
                    style="width: 140px"
                    :placeholder="t('ontology.attrName')"
                  >
                    <el-option
                      v-for="a in entityAttributes"
                      :key="a.id"
                      :label="a.name"
                      :value="a.id"
                    />
                  </el-select>
                  <el-select v-model="evidenceForm.evidence_kind" style="width: 110px">
                    <el-option label="document" value="document" />
                    <el-option label="ko" value="ko" />
                    <el-option label="chunk" value="chunk" />
                  </el-select>
                  <el-input
                    v-model="evidenceForm.evidence_id"
                    :placeholder="t('ontology.evidenceId')"
                    style="width: 160px"
                  />
                  <el-input
                    v-model="evidenceForm.note"
                    :placeholder="t('ontology.evidenceNote')"
                    style="width: 140px"
                  />
                  <el-button type="primary" size="small" :loading="evidenceSaving" @click="submitEvidence">
                    {{ t('ontology.addEvidence') }}
                  </el-button>
                </div>
              </div>
            </div>
          </div>
        </template>
      </section>
    </div>
  </el-card>

  <el-dialog
    v-model="versionDialog"
    :title="t('ontology.createVersion')"
    width="480px"
    destroy-on-close
  >
    <el-form ref="versionFormRef" :model="versionForm" :rules="versionRules" label-width="100px">
      <el-form-item :label="t('ontology.versionName')" prop="name">
        <el-input v-model="versionForm.name" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('ontology.versionNotes')">
        <el-input v-model="versionForm.notes" type="textarea" :rows="2" maxlength="512" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="versionDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="versionSaving" @click="submitVersion">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="entityDialog"
    :title="t('ontology.addEntity')"
    width="520px"
    destroy-on-close
  >
    <el-form ref="entityFormRef" :model="entityForm" :rules="entityRules" label-width="100px">
      <el-form-item :label="t('ontology.localName')" prop="local_name">
        <el-input v-model="entityForm.local_name" maxlength="64" />
      </el-form-item>
      <el-form-item :label="t('ontology.label')" prop="label">
        <el-input v-model="entityForm.label" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('ontology.objectType')">
        <el-input v-model="entityForm.object_type" maxlength="64" placeholder="equipment" />
      </el-form-item>
      <el-form-item :label="t('ontology.description')">
        <el-input v-model="entityForm.description" type="textarea" :rows="2" maxlength="1024" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="entityDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="entitySaving" @click="submitEntity">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="attrDialog"
    :title="attrEditingId ? t('ontology.editAttribute') : t('ontology.addAttribute')"
    width="560px"
    destroy-on-close
  >
    <el-form ref="attrFormRef" :model="attrForm" :rules="attrRules" label-width="110px">
      <el-form-item :label="t('ontology.attrName')" prop="name">
        <el-input v-model="attrForm.name" maxlength="64" :disabled="!!attrEditingId" />
      </el-form-item>
      <el-form-item :label="t('ontology.label')" prop="label">
        <el-input v-model="attrForm.label" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('ontology.attrKind')">
        <el-select v-model="attrForm.attr_kind" style="width: 100%">
          <el-option value="string" label="string" />
          <el-option value="number" label="number" />
          <el-option value="boolean" label="boolean" />
          <el-option value="datetime" label="datetime" />
          <el-option value="quantity" label="quantity" />
          <el-option value="enum" label="enum" />
        </el-select>
      </el-form-item>
      <el-form-item :label="t('ontology.attrUnit')">
        <el-input v-model="attrForm.unit" maxlength="32" placeholder="kW / mm / ℃" />
      </el-form-item>
      <el-form-item :label="t('ontology.attrEnumMap')">
        <el-input
          v-model="attrForm.enum_map_json"
          type="textarea"
          :rows="4"
          :placeholder="t('ontology.attrEnumMapHint')"
        />
      </el-form-item>
      <el-form-item :label="t('ontology.attrLabels')">
        <div style="display: flex; flex-direction: column; gap: 6px; width: 100%">
          <el-input v-model="attrForm.label_zh" :placeholder="t('ontology.attrLabelZh')" />
          <el-input v-model="attrForm.label_en" :placeholder="t('ontology.attrLabelEn')" />
          <el-input v-model="attrForm.label_vi" :placeholder="t('ontology.attrLabelVi')" />
        </div>
      </el-form-item>
      <el-form-item :label="t('ontology.description')">
        <el-input v-model="attrForm.description" type="textarea" :rows="2" maxlength="1024" />
      </el-form-item>
      <el-form-item :label="t('ontology.computeExpr')">
        <el-input
          v-model="attrForm.compute_expr"
          maxlength="256"
          :placeholder="t('ontology.computeExprHint')"
        />
      </el-form-item>
      <el-form-item :label="t('ontology.computeInputs')">
        <el-input v-model="attrForm.compute_inputs" maxlength="256" placeholder="a, b" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="attrDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="attrSaving" @click="submitAttribute">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="mappingDialog"
    :title="t('ontology.addMapping')"
    width="480px"
    destroy-on-close
  >
    <el-form
      ref="mappingFormRef"
      :model="mappingForm"
      :rules="mappingRules"
      label-width="100px"
    >
      <el-form-item :label="t('ontology.tableName')" prop="table_name">
        <el-input v-model="mappingForm.table_name" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('ontology.columnName')" prop="column_name">
        <el-input v-model="mappingForm.column_name" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('ontology.sourceId')">
        <el-input v-model="mappingForm.source_id" maxlength="32" />
      </el-form-item>
      <el-form-item :label="t('ontology.sourceOfTruth')">
        <el-switch v-model="mappingForm.source_of_truth" />
      </el-form-item>
      <el-form-item :label="t('ontology.freshnessSla')">
        <el-input-number
          v-model="mappingForm.freshness_sla_seconds"
          :min="1"
          :controls="false"
          style="width: 100%"
          :placeholder="t('ontology.freshnessSlaHint')"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="mappingDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="mappingSaving" @click="submitMapping">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="importDialog"
    :title="t('ontology.importSchema')"
    width="640px"
    destroy-on-close
  >
    <p class="hint">{{ t('ontology.importHint') }}</p>
    <el-input
      v-model="importJson"
      type="textarea"
      :rows="14"
      :placeholder="t('ontology.importJson')"
    />
    <el-checkbox v-model="importAutoApprove" class="mt">
      {{ t('ontology.autoApprove') }}
    </el-checkbox>
    <template #footer>
      <el-button @click="importDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="importSaving" @click="submitImport">
        {{ t('ontology.importSchema') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="dbDialog"
    :title="t('ontology.connectDb')"
    width="720px"
    destroy-on-close
  >
    <el-steps :active="dbStep" finish-status="success" align-center class="db-steps">
      <el-step :title="t('ontology.dbStepConnect')" />
      <el-step :title="t('ontology.dbStepTables')" />
      <el-step :title="t('ontology.dbStepPreview')" />
    </el-steps>

    <div v-show="dbStep === 0" class="db-step-body">
      <p class="hint">{{ t('ontology.dbConnectHint') }}</p>
      <el-form label-width="120px" class="mb">
        <el-form-item :label="t('ontology.dbEngine')">
          <el-radio-group
            :model-value="dbEngine"
            @update:model-value="(v: string | number | boolean | undefined) => onEngineChange(String(v) as DbEngine)"
          >
            <el-radio-button value="mysql">MySQL</el-radio-button>
            <el-radio-button value="postgres">PostgreSQL</el-radio-button>
            <el-radio-button value="mssql">SQL Server</el-radio-button>
            <el-radio-button value="mongo">MongoDB</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-radio-group v-model="dbMode" class="mb">
        <el-radio-button value="manual">{{ t('ontology.dbModeManual') }}</el-radio-button>
        <el-radio-button value="source">{{ t('ontology.dbModeSource') }}</el-radio-button>
      </el-radio-group>
      <el-form v-if="dbMode === 'source'" label-width="120px">
        <el-form-item :label="t('ontology.dbSource')">
          <el-select v-model="dbForm.source_id" style="width: 100%" filterable>
            <el-option
              v-for="s in engineSources"
              :key="s.id"
              :label="s.name"
              :value="s.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item
          v-if="dbEngine === 'postgres' || dbEngine === 'mssql'"
          :label="t('ontology.dbSchema')"
        >
          <el-input v-model="dbForm.schema" :placeholder="defaultSchema(dbEngine)" />
        </el-form-item>
        <el-form-item v-if="dbEngine === 'mongo'" :label="t('ontology.dbAuthSource')">
          <el-input v-model="dbForm.auth_source" placeholder="admin" />
        </el-form-item>
        <el-form-item :label="t('ontology.dbPasswordEnv')">
          <el-input
            v-model="dbForm.password_env"
            :placeholder="defaultPasswordEnv(dbEngine)"
          />
        </el-form-item>
        <el-form-item :label="t('ontology.dbPasswordOnce')">
          <el-input v-model="dbForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <el-form v-else label-width="120px">
        <el-form-item :label="t('ontology.dbHost')">
          <el-input v-model="dbForm.host" />
        </el-form-item>
        <el-form-item :label="t('ontology.dbPort')">
          <el-input-number v-model="dbForm.port" :min="1" :max="65535" />
        </el-form-item>
        <el-form-item :label="t('ontology.dbDatabase')">
          <el-input v-model="dbForm.database" />
        </el-form-item>
        <el-form-item
          v-if="dbEngine === 'postgres' || dbEngine === 'mssql'"
          :label="t('ontology.dbSchema')"
        >
          <el-input v-model="dbForm.schema" :placeholder="defaultSchema(dbEngine)" />
        </el-form-item>
        <el-form-item v-if="dbEngine === 'mongo'" :label="t('ontology.dbAuthSource')">
          <el-input v-model="dbForm.auth_source" placeholder="admin" />
        </el-form-item>
        <el-form-item :label="t('ontology.dbUser')">
          <el-input
            v-model="dbForm.user"
            :placeholder="dbEngine === 'mongo' ? t('ontology.dbUserOptional') : ''"
          />
        </el-form-item>
        <el-form-item :label="t('ontology.dbPasswordEnv')">
          <el-input
            v-model="dbForm.password_env"
            :placeholder="defaultPasswordEnv(dbEngine)"
          />
        </el-form-item>
        <el-form-item :label="t('ontology.dbPasswordOnce')">
          <el-input v-model="dbForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
    </div>

    <div v-show="dbStep === 1" class="db-step-body">
      <p class="hint">{{ dbEngine === 'mongo' ? t('ontology.dbCollectionsHint') : t('ontology.dbTablesHint') }}</p>
      <el-table
        :data="dbTables"
        height="320"
        @selection-change="(rows: MysqlTableInfo[]) => (selectedTableNames = rows.map((r) => r.name))"
      >
        <el-table-column type="selection" width="42" />
        <el-table-column prop="name" :label="t('ontology.tableName')" min-width="160" />
        <el-table-column prop="approx_rows" :label="t('ontology.dbApproxRows')" width="100" />
        <el-table-column prop="comment" :label="t('ontology.description')" min-width="140" />
      </el-table>
    </div>

    <div v-show="dbStep === 2" class="db-step-body">
      <p class="hint">{{ t('ontology.dbPreviewHint') }}</p>
      <div v-for="trow in probedTables" :key="trow.name" class="probe-block">
        <div class="probe-title">
          <strong>{{ trow.name }}</strong>
          <span class="meta-sub"> · {{ trow.row_count }} rows · {{ trow.columns.length }} cols</span>
        </div>
        <el-table :data="trow.columns" size="small" max-height="180">
          <el-table-column prop="name" :label="t('ontology.columnName')" />
          <el-table-column prop="type" :label="t('ontology.attrKind')" width="140" />
          <el-table-column prop="key" label="Key" width="70" />
          <el-table-column prop="nullable" label="Null" width="70" />
        </el-table>
      </div>
      <el-checkbox v-model="dbAutoApprove" class="mt">
        {{ t('ontology.autoApprove') }}
      </el-checkbox>
    </div>

    <template #footer>
      <el-button @click="dbDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button v-if="dbStep > 0" :disabled="dbBusy" @click="dbStep -= 1">
        {{ t('ontology.dbPrev') }}
      </el-button>
      <el-button
        v-if="dbStep === 0"
        type="primary"
        :loading="dbBusy"
        @click="dbListTables"
      >
        {{ t('ontology.dbListTables') }}
      </el-button>
      <el-button
        v-else-if="dbStep === 1"
        type="primary"
        :loading="dbBusy"
        @click="dbProbeSelected"
      >
        {{ t('ontology.dbReadSchema') }}
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="dbBusy"
        @click="dbImportSchema"
      >
        {{ t('ontology.dbImportToDraft') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="suggestDialog"
    :title="t('ontology.suggestPreview')"
    width="780px"
    destroy-on-close
  >
    <p class="hint">{{ t('ontology.suggestPreviewHint') }}</p>
    <el-table :data="suggestRows" max-height="420">
      <el-table-column prop="kind" :label="t('ontology.suggestKind')" width="90" />
      <el-table-column prop="code" :label="t('ontology.localName')" min-width="120" />
      <el-table-column prop="before_label" :label="t('ontology.suggestBefore')" min-width="120" />
      <el-table-column prop="label" :label="t('ontology.suggestAfter')" min-width="120" />
      <el-table-column prop="before_extra" :label="t('ontology.suggestBeforeType')" width="110" />
      <el-table-column prop="extra" :label="t('ontology.suggestAfterType')" width="110" />
    </el-table>
    <template #footer>
      <el-button @click="suggestDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="suggestApplying" @click="applySuggest">
        {{ t('ontology.suggestApply') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.card-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}
.hint {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}
.studio-layout {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: 16px;
  min-height: 480px;
}
.version-pane {
  border-right: 1px solid var(--el-border-color-lighter);
  padding-right: 8px;
}
.evidence-panel {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
.evidence-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  align-items: center;
}
.pane-title {
  font-weight: 600;
  margin-bottom: 8px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.pane-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.pane-title .sub {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.version-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  line-height: 1.3;
  white-space: normal;
}
.version-name {
  font-size: 13px;
}
.detail-meta {
  margin-bottom: 12px;
}
.detail-meta .ml {
  margin-left: 8px;
}
.detail-meta .readonly {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.meta-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.tables-split {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
}
.view-toggle {
  margin-right: 8px;
}
.canvas-split {
  display: grid;
  grid-template-columns: 1fr 260px;
  gap: 12px;
  min-height: 420px;
}
.relation-canvas-scroll {
  max-height: min(70vh, 720px);
  overflow: auto;
  background: linear-gradient(180deg, #f8fafc, #eef2ff);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.relation-canvas {
  display: block;
  min-width: 100%;
}
.canvas-node {
  cursor: pointer;
}
.canvas-node.active rect {
  stroke: #f59e0b;
  stroke-width: 3;
}
html.dark .relation-canvas-scroll {
  background: linear-gradient(180deg, #0f172a, #1e293b);
}
.canvas-inspector {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
  background: var(--el-bg-color);
}
.inspector-title {
  font-weight: 600;
  margin-bottom: 8px;
}
.inspector-dl {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px 8px;
  font-size: 12px;
  margin: 0;
}
.inspector-dl dt {
  color: var(--el-text-color-secondary);
}
.inspector-dl dd {
  margin: 0;
  word-break: break-all;
}
.mt {
  margin-top: 12px;
}
.mb {
  margin-bottom: 12px;
}
.db-steps {
  margin-bottom: 16px;
}
.db-step-body {
  min-height: 280px;
}
.probe-block {
  margin-bottom: 14px;
}
.probe-title {
  margin-bottom: 6px;
}
@media (max-width: 1100px) {
  .studio-layout,
  .tables-split,
  .canvas-split {
    grid-template-columns: 1fr;
  }
  .version-pane {
    border-right: none;
    border-bottom: 1px solid var(--el-border-color-lighter);
    padding-right: 0;
    padding-bottom: 12px;
  }
}
</style>
