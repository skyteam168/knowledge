<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  addSemanticAttribute,
  updateSemanticAttribute,
  addSemanticEntity,
  addSemanticMapping,
  batchSetSemanticStatus,
  createSemanticVersion,
  getSemanticVersion,
  importOntologySchema,
  listSemanticVersions,
  publishSemanticVersion,
  suggestSemanticLabels,
} from '@/api/ontology'
import type {
  SchemaImportIn,
  SemanticAttribute,
  SemanticEntity,
  SemanticItemStatus,
  SemanticMapping,
  SemanticVersion,
  SemanticVersionDetail,
} from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

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

async function runSuggest(): Promise<void> {
  if (!detail.value || !isDraft.value) return
  actionBusy.value = true
  try {
    const out = await suggestSemanticLabels(detail.value.id)
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
    actionBusy.value = false
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

interface CanvasNode {
  id: string
  kind: 'entity' | 'attribute'
  label: string
  x: number
  y: number
  entityId?: string
}

interface CanvasEdge {
  from: string
  to: string
  label: string
}

const canvasNodes = computed<CanvasNode[]>(() => {
  if (!detail.value) return []
  const entities = detail.value.entities
  const attrs = detail.value.attributes
  const nodes: CanvasNode[] = []
  entities.forEach((e, i) => {
    const col = i % 3
    const row = Math.floor(i / 3)
    nodes.push({
      id: `e:${e.id}`,
      kind: 'entity',
      label: e.label || e.local_name,
      x: 80 + col * 220,
      y: 60 + row * 180,
    })
    const mine = attrs.filter((a) => a.entity_id === e.id)
    mine.forEach((a, j) => {
      nodes.push({
        id: `a:${a.id}`,
        kind: 'attribute',
        label: a.label || a.name,
        x: 80 + col * 220 + 40,
        y: 60 + row * 180 + 55 + j * 36,
        entityId: e.id,
      })
    })
  })
  return nodes
})

const canvasEdges = computed<CanvasEdge[]>(() => {
  if (!detail.value) return []
  const edges: CanvasEdge[] = []
  for (const a of detail.value.attributes) {
    edges.push({ from: `e:${a.entity_id}`, to: `a:${a.id}`, label: 'has' })
  }
  for (const m of detail.value.mappings) {
    edges.push({
      from: `a:${m.attribute_id}`,
      to: `a:${m.attribute_id}`,
      label: `${m.table_name}.${m.column_name}`,
    })
  }
  return edges.filter((e) => e.from !== e.to)
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
          <el-button @click="openCreateVersion">{{ t('ontology.createVersion') }}</el-button>
          <el-button @click="openImport">{{ t('ontology.importSchema') }}</el-button>
          <el-button
            :disabled="!isDraft"
            :loading="actionBusy"
            @click="runSuggest"
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
            <svg
              class="relation-canvas"
              viewBox="0 0 720 420"
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
                  v-if="canvasNodes.find((n) => n.id === edge.from) && canvasNodes.find((n) => n.id === edge.to)"
                  :x1="canvasNodes.find((n) => n.id === edge.from)!.x"
                  :y1="canvasNodes.find((n) => n.id === edge.from)!.y"
                  :x2="canvasNodes.find((n) => n.id === edge.to)!.x"
                  :y2="canvasNodes.find((n) => n.id === edge.to)!.y"
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
.relation-canvas {
  width: 100%;
  height: 420px;
  background: linear-gradient(180deg, #f8fafc, #eef2ff);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.canvas-node {
  cursor: pointer;
}
.canvas-node.active rect {
  stroke: #f59e0b;
  stroke-width: 3;
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
