<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  bulkAssignRole,
  createRole,
  deleteRole,
  listGroups,
  listPermissions,
  listRoles,
  setRolePermissions,
  updateRole,
} from '@/api/admin'
import { getDirectoryDepartments } from '@/api/knowledge'
import type {
  DirectoryDepartment,
  Group,
  Permission,
  Role,
  RoleBulkAssign,
  RoleBulkResult,
} from '@/api/types'
import { permissionName, roleName } from '@/i18n/catalog'

const { t } = useI18n()

const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const loading = ref(false)
const currentId = ref<string | null>(null)
const checked = ref<string[]>([])
const saving = ref(false)

const current = computed(() => roles.value.find((r) => r.id === currentId.value) ?? null)

const GROUP_LABEL_KEYS: Record<string, string> = {
  '*': 'super',
  kb: 'kb',
  doc: 'doc',
  review: 'review',
  chat: 'chat',
  search: 'search',
  analytics: 'analytics',
  admin: 'admin',
}

const permissionGroups = computed(() => {
  const groups = new Map<string, Permission[]>()
  for (const p of permissions.value) {
    const key = p.code === '*' ? '*' : p.code.split(':')[0]!
    groups.set(key, [...(groups.get(key) ?? []), p])
  }
  return [...groups.entries()].map(([key, items]) => {
    const labelKey = GROUP_LABEL_KEYS[key]
    return { key, label: labelKey ? t(`roles.permissionGroups.${labelKey}`) : key, items }
  })
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const [r, p] = await Promise.all([listRoles(), listPermissions()])
    roles.value = r
    permissions.value = p
    if (!current.value && r.length) select(r[0]!)
    else if (current.value) checked.value = [...current.value.permissions]
  } finally {
    loading.value = false
  }
}

function select(role: Role): void {
  currentId.value = role.id
  checked.value = [...role.permissions]
}

async function savePermissions(): Promise<void> {
  if (!current.value) return
  saving.value = true
  try {
    await setRolePermissions(current.value.id, checked.value)
    ElMessage.success(t('roles.permissions.saved'))
    await load()
  } finally {
    saving.value = false
  }
}

// ---- create / edit ----------------------------------------------------------

const formRef = ref<FormInstance>()
const editor = reactive({
  visible: false,
  editingId: null as string | null,
  form: { code: '', name: '', description: '' as string | null, is_default: false },
})
const editingPrivileged = computed(() => {
  const role = roles.value.find((r) => r.id === editor.editingId)
  return !!role && isPrivileged(role.permissions)
})

function isPrivileged(codes: string[]): boolean {
  return codes.some((c) => c === '*' || c.startsWith('admin:'))
}
const rules = computed<FormRules>(() => ({
  code: [
    { required: true, message: t('roles.rules.codeRequired'), trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_]*$/, message: t('roles.rules.codePattern') },
  ],
  name: [{ required: true, message: t('roles.rules.nameRequired'), trigger: 'blur' }],
}))

function openCreate(): void {
  editor.editingId = null
  editor.form = { code: '', name: '', description: '', is_default: false }
  editor.visible = true
}

function openEdit(role: Role): void {
  editor.editingId = role.id
  editor.form = {
    code: role.code,
    name: role.name,
    description: role.description,
    is_default: role.is_default,
  }
  editor.visible = true
}

async function submitEditor(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  const { code, name, is_default } = editor.form
  const description = editor.form.description || null
  if (editor.editingId) {
    await updateRole(editor.editingId, { name, description, is_default })
  } else {
    const role = await createRole({ code, name, description })
    if (is_default) await updateRole(role.id, { is_default })
    currentId.value = role.id
  }
  ElMessage.success(t('roles.saveSuccess'))
  editor.visible = false
  await load()
}

async function remove(role: Role): Promise<void> {
  await ElMessageBox.confirm(t('roles.deleteConfirm', { name: roleName(role) }), t('common.tip'), {
    type: 'warning',
  })
  await deleteRole(role.id)
  ElMessage.success(t('common.deleted'))
  if (currentId.value === role.id) currentId.value = null
  await load()
}

// ---- bulk assignment --------------------------------------------------------

const departments = ref<DirectoryDepartment[]>([])
const groups = ref<Group[]>([])
const bulk = reactive({
  visible: false,
  running: false,
  form: {
    action: 'grant' as RoleBulkAssign['action'],
    department_ids: [] as string[],
    group_ids: [] as string[],
    include_inactive: false,
  },
  preview: null as RoleBulkResult | null,
})
const departmentNames = computed(() => {
  const map = new Map<string, string>()
  const walk = (nodes: DirectoryDepartment[]) =>
    nodes.forEach((n) => {
      map.set(n.id, n.path_name ?? n.name)
      walk(n.children)
    })
  walk(departments.value)
  return map
})
const bulkHasTarget = computed(
  () => bulk.form.department_ids.length > 0 || bulk.form.group_ids.length > 0,
)
const bulkGrantBlocked = computed(
  () => bulk.form.action === 'grant' && !!current.value && isPrivileged(current.value.permissions),
)

const previewText = computed(() => {
  const preview = bulk.preview
  if (!preview) return ''
  const key =
    bulk.form.action === 'grant'
      ? 'roles.bulk.previewGrant'
      : preview.skipped
        ? 'roles.bulk.previewRevokeSkipped'
        : 'roles.bulk.previewRevoke'
  return t(key, {
    matched: preview.matched,
    changed: preview.changed,
    unchanged: preview.unchanged,
    skipped: preview.skipped,
  })
})

function filterDepartment(keyword: string, node: Record<string, unknown>): boolean {
  const dept = node as unknown as DirectoryDepartment
  return (dept.path_name ?? dept.name).toLowerCase().includes(keyword.toLowerCase())
}

async function openBulk(): Promise<void> {
  bulk.form = { action: 'grant', department_ids: [], group_ids: [], include_inactive: false }
  bulk.preview = null
  bulk.visible = true
  const [depts, page] = await Promise.all([
    getDirectoryDepartments(),
    listGroups({ page: 1, size: 200 }),
  ])
  departments.value = depts
  groups.value = page.items
}

async function searchGroups(keyword: string): Promise<void> {
  groups.value = (await listGroups({ page: 1, size: 200, keyword: keyword || undefined })).items
}

async function runBulk(dryRun: boolean): Promise<void> {
  const role = current.value
  if (!role || !bulkHasTarget.value) return
  bulk.running = true
  try {
    const result = await bulkAssignRole(role.id, { ...bulk.form, dry_run: dryRun })
    if (dryRun) {
      bulk.preview = result
      return
    }
    const key = `roles.bulk.${bulk.form.action}Done${result.skipped ? 'Skipped' : ''}`
    ElMessage.success(
      t(key, { changed: result.changed, skipped: result.skipped, name: roleName(role) }),
    )
    bulk.visible = false
  } finally {
    bulk.running = false
  }
}

async function confirmBulk(): Promise<void> {
  const role = current.value
  if (!role) return
  if (!bulk.preview) await runBulk(true)
  const preview = bulk.preview
  if (!preview) return
  await ElMessageBox.confirm(
    t(bulk.form.action === 'grant' ? 'roles.bulk.confirmGrant' : 'roles.bulk.confirmRevoke', {
      changed: preview.changed,
      name: role.name,
      matched: preview.matched,
    }),
    t('roles.bulk.confirmTitle'),
    { type: 'warning' },
  )
  await runBulk(false)
}

function resetPreview(): void {
  bulk.preview = null
}

onMounted(load)
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="9">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>{{ t('roles.list.title') }}</span>
            <el-button v-permission="'admin:role'" type="primary" size="small" @click="openCreate">
              {{ t('roles.list.create') }}
            </el-button>
          </div>
        </template>
        <el-table
          v-loading="loading"
          :data="roles"
          highlight-current-row
          :current-row-key="currentId ?? undefined"
          row-key="id"
          @row-click="select"
        >
          <el-table-column :label="t('roles.list.role')" min-width="140">
            <template #default="{ row }">
              <div>{{ roleName(row as Role) }}</div>
              <div class="muted">{{ row.code }}</div>
            </template>
          </el-table-column>
          <el-table-column :label="t('roles.list.type')" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.is_system" size="small">{{ t('roles.list.system') }}</el-tag>
              <el-tooltip
                v-if="row.is_default"
                :content="t('roles.list.defaultTip')"
                placement="top"
              >
                <el-tag size="small" type="success" class="default-tag">{{
                  t('roles.list.default')
                }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column :label="t('common.actions')" width="110">
            <template #default="{ row }">
              <span v-permission="'admin:role'">
                <el-button link type="primary" @click.stop="openEdit(row as Role)">{{
                  t('common.edit')
                }}</el-button>
                <el-button
                  v-if="!row.is_system"
                  link
                  type="danger"
                  @click.stop="remove(row as Role)"
                >
                  {{ t('common.delete') }}
                </el-button>
              </span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-col>
    <el-col :span="15">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>{{
              current
                ? t('roles.permissions.title', { name: roleName(current) })
                : t('roles.permissions.selectRole')
            }}</span>
            <span v-if="current" v-permission="'admin:role'">
              <el-button size="small" @click="openBulk">{{ t('roles.bulk.open') }}</el-button>
              <el-button type="primary" size="small" :loading="saving" @click="savePermissions">
                {{ t('roles.permissions.save') }}
              </el-button>
            </span>
          </div>
        </template>
        <el-checkbox-group v-if="current" v-model="checked">
          <div v-for="group in permissionGroups" :key="group.key" class="perm-group">
            <div class="perm-group__title">{{ group.label }}</div>
            <el-checkbox v-for="p in group.items" :key="p.code" :value="p.code">
              {{ permissionName(p.code, p.name) }} <span class="muted">{{ p.code }}</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
        <el-empty v-else :description="t('roles.permissions.selectRoleHint')" />
      </el-card>
    </el-col>
  </el-row>

  <el-dialog
    v-model="editor.visible"
    :title="editor.editingId ? t('roles.editor.editTitle') : t('roles.editor.createTitle')"
    width="480px"
  >
    <el-form ref="formRef" :model="editor.form" :rules="rules" label-width="80px">
      <el-form-item :label="t('roles.editor.code')" prop="code">
        <el-input v-model="editor.form.code" :disabled="!!editor.editingId" maxlength="64" />
      </el-form-item>
      <el-form-item :label="t('common.name')" prop="name">
        <el-input v-model="editor.form.name" maxlength="128" />
      </el-form-item>
      <el-form-item :label="t('common.description')">
        <el-input v-model="editor.form.description" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item :label="t('roles.editor.isDefault')">
        <el-switch v-model="editor.form.is_default" :disabled="editingPrivileged" />
        <div class="form-help">
          {{
            editingPrivileged
              ? t('roles.editor.privilegedDefaultHint')
              : t('roles.editor.defaultHint')
          }}
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editor.visible = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" @click="submitEditor">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="bulk.visible"
    :title="
      current ? t('roles.bulk.title', { name: roleName(current) }) : t('roles.bulk.titleFallback')
    "
    width="560px"
  >
    <el-form label-width="90px">
      <el-form-item :label="t('roles.bulk.action')">
        <el-radio-group v-model="bulk.form.action" @change="resetPreview">
          <el-radio value="grant">{{ t('roles.bulk.grant') }}</el-radio>
          <el-radio value="revoke">{{ t('roles.bulk.revoke') }}</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item :label="t('roles.bulk.departments')">
        <el-tree-select
          v-model="bulk.form.department_ids"
          :data="departments"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          multiple
          check-strictly
          filterable
          :filter-node-method="filterDepartment"
          :placeholder="t('roles.bulk.departmentsPlaceholder')"
          style="width: 100%"
          @change="resetPreview"
        >
          <template #label="{ value }">{{ departmentNames.get(value) ?? value }}</template>
        </el-tree-select>
      </el-form-item>
      <el-form-item :label="t('roles.bulk.groups')">
        <el-select
          v-model="bulk.form.group_ids"
          multiple
          filterable
          remote
          :remote-method="searchGroups"
          :placeholder="t('roles.bulk.groupsPlaceholder')"
          style="width: 100%"
          @change="resetPreview"
        >
          <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="">
        <el-checkbox v-model="bulk.form.include_inactive" @change="resetPreview">
          {{ t('roles.bulk.includeInactive') }}
        </el-checkbox>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="bulkGrantBlocked"
      type="warning"
      :closable="false"
      :title="t('roles.bulk.privilegedBlocked')"
    />
    <el-alert v-else-if="bulk.preview" type="info" :closable="false" :title="previewText" />
    <template #footer>
      <el-button @click="bulk.visible = false">{{ t('common.cancel') }}</el-button>
      <el-button
        :disabled="!bulkHasTarget || bulkGrantBlocked"
        :loading="bulk.running"
        @click="runBulk(true)"
      >
        {{ t('roles.bulk.preview') }}
      </el-button>
      <el-button
        type="primary"
        :disabled="!bulkHasTarget || bulkGrantBlocked"
        :loading="bulk.running"
        @click="confirmBulk"
      >
        {{ t('roles.bulk.run') }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.perm-group {
  margin-bottom: 16px;
}

.default-tag {
  margin-left: 4px;
}

.form-help {
  width: 100%;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.perm-group__title {
  font-weight: 500;
  margin-bottom: 8px;
}
</style>
