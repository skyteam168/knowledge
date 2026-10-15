<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
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

const roles = ref<Role[]>([])
const permissions = ref<Permission[]>([])
const loading = ref(false)
const currentId = ref<string | null>(null)
const checked = ref<string[]>([])
const saving = ref(false)

const current = computed(() => roles.value.find((r) => r.id === currentId.value) ?? null)

const GROUP_LABELS: Record<string, string> = {
  '*': '超级权限',
  kb: '知识库',
  doc: '文档',
  review: '审核',
  chat: 'AI 助手',
  search: '搜索',
  analytics: '分析',
  admin: '系统管理',
}

const permissionGroups = computed(() => {
  const groups = new Map<string, Permission[]>()
  for (const p of permissions.value) {
    const key = p.code === '*' ? '*' : p.code.split(':')[0]!
    groups.set(key, [...(groups.get(key) ?? []), p])
  }
  return [...groups.entries()].map(([key, items]) => ({
    key,
    label: GROUP_LABELS[key] ?? key,
    items,
  }))
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
    ElMessage.success('权限已保存，相关用户的权限缓存已刷新')
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
const rules: FormRules = {
  code: [
    { required: true, message: '请输入角色编码', trigger: 'blur' },
    { pattern: /^[a-z][a-z0-9_]*$/, message: '小写字母开头，仅含小写字母、数字、下划线' },
  ],
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
}

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
  ElMessage.success('保存成功')
  editor.visible = false
  await load()
}

async function remove(role: Role): Promise<void> {
  await ElMessageBox.confirm(`确定删除角色「${role.name}」吗？`, '提示', { type: 'warning' })
  await deleteRole(role.id)
  ElMessage.success('已删除')
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
    const verb = bulk.form.action === 'grant' ? '授予' : '撤销'
    const skipped = result.skipped ? `，跳过 ${result.skipped} 人` : ''
    ElMessage.success(`已为 ${result.changed} 人${verb}「${role.name}」${skipped}，立即生效`)
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
  const verb = bulk.form.action === 'grant' ? '授予' : '撤销'
  await ElMessageBox.confirm(
    `将为 ${preview.changed} 人${verb}角色「${role.name}」（匹配 ${preview.matched} 人），确定执行？`,
    '批量分配角色',
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
            <span>角色</span>
            <el-button v-permission="'admin:role'" type="primary" size="small" @click="openCreate">
              新建角色
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
          <el-table-column label="角色" min-width="140">
            <template #default="{ row }">
              <div>{{ row.name }}</div>
              <div class="muted">{{ row.code }}</div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.is_system" size="small">内置</el-tag>
              <el-tooltip
                v-if="row.is_default"
                content="同步或首次登录新建的用户自动获得此角色"
                placement="top"
              >
                <el-tag size="small" type="success" class="default-tag">默认</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <span v-permission="'admin:role'">
                <el-button link type="primary" @click.stop="openEdit(row as Role)">编辑</el-button>
                <el-button
                  v-if="!row.is_system"
                  link
                  type="danger"
                  @click.stop="remove(row as Role)"
                >
                  删除
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
            <span>{{ current ? `「${current.name}」的权限` : '请选择角色' }}</span>
            <span v-if="current" v-permission="'admin:role'">
              <el-button size="small" @click="openBulk">批量分配</el-button>
              <el-button type="primary" size="small" :loading="saving" @click="savePermissions">
                保存权限
              </el-button>
            </span>
          </div>
        </template>
        <el-checkbox-group v-if="current" v-model="checked">
          <div v-for="group in permissionGroups" :key="group.key" class="perm-group">
            <div class="perm-group__title">{{ group.label }}</div>
            <el-checkbox v-for="p in group.items" :key="p.code" :value="p.code">
              {{ p.name }} <span class="muted">{{ p.code }}</span>
            </el-checkbox>
          </div>
        </el-checkbox-group>
        <el-empty v-else description="请选择左侧角色" />
      </el-card>
    </el-col>
  </el-row>

  <el-dialog
    v-model="editor.visible"
    :title="editor.editingId ? '编辑角色' : '新建角色'"
    width="480px"
  >
    <el-form ref="formRef" :model="editor.form" :rules="rules" label-width="80px">
      <el-form-item label="编码" prop="code">
        <el-input v-model="editor.form.code" :disabled="!!editor.editingId" maxlength="64" />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="editor.form.name" maxlength="128" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="editor.form.description" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="默认角色">
        <el-switch v-model="editor.form.is_default" :disabled="editingPrivileged" />
        <div class="form-help">
          {{
            editingPrivileged
              ? '含超级权限或系统管理权限的角色不能设为默认角色'
              : '组织同步或首次登录新建的用户自动获得此角色；已有用户不受影响，可用「批量分配」补授'
          }}
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editor.visible = false">取消</el-button>
      <el-button type="primary" @click="submitEditor">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="bulk.visible"
    :title="current ? `批量分配「${current.name}」` : '批量分配'"
    width="560px"
  >
    <el-form label-width="90px">
      <el-form-item label="操作">
        <el-radio-group v-model="bulk.form.action" @change="resetPreview">
          <el-radio value="grant">授予</el-radio>
          <el-radio value="revoke">撤销</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="部门">
        <el-tree-select
          v-model="bulk.form.department_ids"
          :data="departments"
          :props="{ label: 'name', children: 'children' }"
          node-key="id"
          multiple
          check-strictly
          filterable
          :filter-node-method="filterDepartment"
          placeholder="选择部门（含下级部门），可按完整路径搜索"
          style="width: 100%"
          @change="resetPreview"
        >
          <template #label="{ value }">{{ departmentNames.get(value) ?? value }}</template>
        </el-tree-select>
      </el-form-item>
      <el-form-item label="用户组">
        <el-select
          v-model="bulk.form.group_ids"
          multiple
          filterable
          remote
          :remote-method="searchGroups"
          placeholder="选择用户组，如「职务/班组长」"
          style="width: 100%"
          @change="resetPreview"
        >
          <el-option v-for="g in groups" :key="g.id" :label="g.name" :value="g.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="">
        <el-checkbox v-model="bulk.form.include_inactive" @change="resetPreview">
          包含已停用的用户
        </el-checkbox>
      </el-form-item>
    </el-form>
    <el-alert
      v-if="bulkGrantBlocked"
      type="warning"
      :closable="false"
      title="含超级权限或系统管理权限的角色不能批量授予，请在用户管理中逐个分配"
    />
    <el-alert v-else-if="bulk.preview" type="info" :closable="false">
      <template #title>
        匹配 {{ bulk.preview.matched }} 人，将{{ bulk.form.action === 'grant' ? '授予' : '撤销' }}
        {{ bulk.preview.changed }} 人
        <template v-if="bulk.form.action === 'grant'">
          （{{ bulk.preview.unchanged }} 人已有此角色）
        </template>
        <template v-else>
          （{{ bulk.preview.unchanged }} 人没有此角色<template v-if="bulk.preview.skipped"
            >，{{ bulk.preview.skipped }} 人的角色来自 Keycloak 或为本人，不撤销</template
          >）
        </template>
      </template>
    </el-alert>
    <template #footer>
      <el-button @click="bulk.visible = false">取消</el-button>
      <el-button
        :disabled="!bulkHasTarget || bulkGrantBlocked"
        :loading="bulk.running"
        @click="runBulk(true)"
      >
        预览人数
      </el-button>
      <el-button
        type="primary"
        :disabled="!bulkHasTarget || bulkGrantBlocked"
        :loading="bulk.running"
        @click="confirmBulk"
      >
        执行
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
