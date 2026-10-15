<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  createUser,
  disableUser,
  getUser,
  listGroups,
  listRoles,
  listUsers,
  openPasswordLogin,
  setUserGroups,
  setUserRoles,
  updateUser,
} from '@/api/admin'
import type { DepartmentNode, Group, Role, User, UserIdentityBrief } from '@/api/types'
import { useDepartmentTree } from '@/composables/useDepartmentTree'
import { formatDateTime } from '@/utils/format'
import { SOURCE_LABEL } from './directory/meta'

const { tree, reload: reloadTree } = useDepartmentTree()
const treeProps = {
  label: 'name',
  children: 'children',
  disabled: (d: Record<string, unknown>) => (d as unknown as DepartmentNode).status === 'archived',
}

const query = reactive({
  keyword: '',
  department_id: undefined as string | undefined,
  is_active: undefined as boolean | undefined,
  page: 1,
  size: 20,
})
const rows = ref<User[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listUsers({ ...query, keyword: query.keyword || undefined })
    rows.value = page.items
    total.value = page.total
  } finally {
    loading.value = false
  }
}

function search(): void {
  query.page = 1
  void load()
}

// ---- create / edit ----------------------------------------------------------

const formRef = ref<FormInstance>()
function emptyForm() {
  return {
    username: '',
    display_name: '' as string | null,
    email: '' as string | null,
    employee_no: '' as string | null,
    mobile: '' as string | null,
    job_title: '' as string | null,
    department_id: null as string | null,
    department_ids: [] as string[],
    is_active: true,
  }
}
const editor = reactive({
  visible: false,
  editingId: null as string | null,
  source: 'local' as User['source'],
  identities: [] as UserIdentityBrief[],
  form: emptyForm(),
})
// Profile and departments of synced users are owned by the directory source.
const managed = computed(() => editor.source !== 'local' && editor.source !== 'keycloak')
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
}

function openCreate(): void {
  editor.editingId = null
  editor.source = 'local'
  editor.identities = []
  editor.form = emptyForm()
  editor.visible = true
}

async function openEdit(row: User): Promise<void> {
  editor.editingId = row.id
  editor.source = row.source
  editor.identities = []
  editor.form = {
    username: row.username,
    display_name: row.display_name,
    email: row.email,
    employee_no: row.employee_no,
    mobile: row.mobile,
    job_title: row.job_title,
    department_id: row.department_id,
    department_ids: row.departments.filter((d) => !d.is_primary).map((d) => d.id),
    is_active: row.is_active,
  }
  editor.visible = true
  editor.identities = (await getUser(row.id)).identities
}

const blank = (v: string | null) => (v ? v.trim() || null : null)

async function submitEditor(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  const f = editor.form
  if (editor.editingId) {
    await updateUser(
      editor.editingId,
      managed.value
        ? { is_active: f.is_active }
        : {
            display_name: blank(f.display_name),
            email: blank(f.email),
            employee_no: blank(f.employee_no),
            mobile: blank(f.mobile),
            job_title: blank(f.job_title),
            department_id: f.department_id,
            department_ids: f.department_ids.filter((d) => d !== f.department_id),
            is_active: f.is_active,
          },
    )
  } else {
    await createUser({
      username: f.username,
      display_name: blank(f.display_name),
      email: blank(f.email),
      employee_no: blank(f.employee_no),
      mobile: blank(f.mobile),
      job_title: blank(f.job_title),
      department_id: f.department_id,
      department_ids: f.department_ids.filter((d) => d !== f.department_id),
    })
  }
  ElMessage.success('保存成功')
  editor.visible = false
  await load()
}

const password = reactive({ visible: false, username: '', value: '', created: false })

async function enablePassword(row: User): Promise<void> {
  await ElMessageBox.confirm(
    `将为「${row.display_name || row.username}」开通账号密码登录并生成临时密码（首次登录须修改）。` +
      '已有 Keycloak 账号时会重置为新的临时密码。',
    '开通密码登录',
    { type: 'warning' },
  )
  const result = await openPasswordLogin(row.id)
  Object.assign(password, {
    visible: true,
    username: result.username,
    value: result.temporary_password,
    created: result.created,
  })
}

async function copyPassword(): Promise<void> {
  await navigator.clipboard.writeText(password.value)
  ElMessage.success('已复制')
}

async function disable(row: User): Promise<void> {
  await ElMessageBox.confirm(`确定禁用用户「${row.username}」吗？`, '提示', { type: 'warning' })
  await disableUser(row.id)
  ElMessage.success('已禁用')
  await load()
}

// ---- role / group assignment ------------------------------------------------

const allRoles = ref<Role[]>([])
const allGroups = ref<Group[]>([])
const assign = reactive({
  visible: false,
  kind: 'roles' as 'roles' | 'groups',
  user: null as User | null,
  selected: [] as string[],
})

async function openAssign(row: User, kind: 'roles' | 'groups'): Promise<void> {
  const [detail] = await Promise.all([
    getUser(row.id),
    kind === 'roles' && !allRoles.value.length
      ? listRoles().then((r) => (allRoles.value = r))
      : undefined,
    kind === 'groups' && !allGroups.value.length
      ? listGroups({ size: 200 }).then((p) => (allGroups.value = p.items))
      : undefined,
  ])
  assign.kind = kind
  assign.user = row
  assign.selected = (kind === 'roles' ? detail.roles : detail.groups).map((x) => x.id)
  assign.visible = true
}

async function submitAssign(): Promise<void> {
  if (!assign.user) return
  if (assign.kind === 'roles') {
    await setUserRoles(assign.user.id, assign.selected)
  } else {
    await setUserGroups(assign.user.id, assign.selected)
  }
  ElMessage.success('已更新')
  assign.visible = false
}

onMounted(() => Promise.all([reloadTree(), load()]))
</script>

<template>
  <el-card shadow="never">
    <el-form :inline="true" @submit.prevent="search">
      <el-form-item>
        <el-input v-model="query.keyword" placeholder="用户名 / 姓名 / 邮箱" clearable />
      </el-form-item>
      <el-form-item>
        <el-tree-select
          v-model="query.department_id"
          :data="tree"
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          filterable
          check-strictly
          clearable
          placeholder="部门（含下级）"
          style="width: 200px"
        />
      </el-form-item>
      <el-form-item>
        <el-select v-model="query.is_active" placeholder="状态" clearable style="width: 120px">
          <el-option label="启用" :value="true" />
          <el-option label="禁用" :value="false" />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
        <el-button v-permission="'admin:user'" @click="openCreate">预置用户</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" empty-text="暂无用户" data-test="user-table">
      <el-table-column label="用户" min-width="150">
        <template #default="{ row }">
          <div>{{ row.display_name || row.username }}</div>
          <div class="muted small">
            {{ row.username }}<template v-if="row.employee_no"> · {{ row.employee_no }}</template>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="部门" min-width="220">
        <template #default="{ row }">
          <div v-if="!(row as User).departments.length" class="muted">-</div>
          <el-tooltip
            v-for="d in (row as User).departments"
            :key="d.id"
            :content="d.path_name"
            placement="top"
          >
            <div class="dept-line">
              {{ d.name }}
              <el-tag v-if="d.is_primary && row.departments.length > 1" size="small" effect="plain">
                主
              </el-tag>
            </div>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="职务" min-width="110">
        <template #default="{ row }">{{ row.job_title || '-' }}</template>
      </el-table-column>
      <el-table-column label="来源" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'local' ? 'info' : 'primary'" effect="plain">
            {{ SOURCE_LABEL[(row as User).source] ?? row.source }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Keycloak" width="100">
        <template #default="{ row }">
          <el-tag :type="row.keycloak_bound ? 'primary' : 'warning'" effect="plain">
            {{ row.keycloak_bound ? '已绑定' : '待登录' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="最近登录" width="170">
        <template #default="{ row }">{{ formatDateTime(row.last_login_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="290" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row as User)">编辑</el-button>
          <el-button
            v-if="row.is_active"
            v-permission="'admin:user'"
            link
            type="primary"
            @click="enablePassword(row as User).catch(() => undefined)"
          >
            密码登录
          </el-button>
          <el-button
            v-permission="'admin:role'"
            link
            type="primary"
            @click="openAssign(row as User, 'roles')"
          >
            角色
          </el-button>
          <el-button link type="primary" @click="openAssign(row as User, 'groups')"
            >用户组</el-button
          >
          <el-button v-if="row.is_active" link type="danger" @click="disable(row as User)"
            >禁用</el-button
          >
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.size"
      class="pager"
      layout="total, sizes, prev, pager, next"
      :total="total"
      @current-change="load"
      @size-change="search"
    />
  </el-card>

  <el-dialog
    v-model="editor.visible"
    :title="editor.editingId ? '编辑用户' : '预置用户'"
    width="520px"
  >
    <el-alert
      v-if="!editor.editingId"
      type="info"
      :closable="false"
      show-icon
      title="用户首次通过 Keycloak 登录时，将按用户名自动绑定该预置账号"
      style="margin-bottom: 16px"
    />
    <el-alert
      v-if="managed"
      type="info"
      :closable="false"
      show-icon
      :title="`该用户由「${SOURCE_LABEL[editor.source]}」同步，资料与部门只读，请在源系统中修改；角色和本地用户组仍可在此分配。`"
      style="margin-bottom: 16px"
    />
    <el-form ref="formRef" :model="editor.form" :rules="rules" label-width="80px">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="editor.form.username" :disabled="!!editor.editingId" />
      </el-form-item>
      <el-form-item label="姓名">
        <el-input v-model="editor.form.display_name" :disabled="managed" />
      </el-form-item>
      <el-form-item label="工号">
        <el-input v-model="editor.form.employee_no" :disabled="managed" />
      </el-form-item>
      <el-form-item label="邮箱" prop="email">
        <el-input v-model="editor.form.email" :disabled="managed" />
      </el-form-item>
      <el-form-item label="手机">
        <el-input v-model="editor.form.mobile" :disabled="managed" />
      </el-form-item>
      <el-form-item label="职务">
        <el-input v-model="editor.form.job_title" :disabled="managed" />
      </el-form-item>
      <el-form-item label="主部门">
        <el-tree-select
          v-model="editor.form.department_id"
          :data="tree"
          node-key="id"
          :props="treeProps"
          check-strictly
          filterable
          clearable
          :disabled="managed"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="兼职部门">
        <el-tree-select
          v-model="editor.form.department_ids"
          :data="tree"
          node-key="id"
          :props="treeProps"
          multiple
          check-strictly
          filterable
          clearable
          :disabled="managed"
          placeholder="一人多部门时选择（权限按所有部门计算）"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item v-if="editor.identities.length" label="已绑定">
        <el-tag
          v-for="i in editor.identities"
          :key="i.provider"
          class="identity-tag"
          effect="plain"
        >
          {{ SOURCE_LABEL[i.provider as User['source']] ?? i.provider }}：{{ i.external_id }}
        </el-tag>
      </el-form-item>
      <el-form-item v-if="editor.editingId" label="启用">
        <el-switch v-model="editor.form.is_active" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editor.visible = false">取消</el-button>
      <el-button type="primary" @click="submitEditor">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="assign.visible"
    :title="`${assign.kind === 'roles' ? '分配角色' : '分配用户组'}：${assign.user?.username ?? ''}`"
    width="520px"
  >
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="此处仅管理本地分配；来自 Keycloak 的角色/组在每次登录时同步"
      style="margin-bottom: 16px"
    />
    <el-checkbox-group v-if="assign.kind === 'roles'" v-model="assign.selected">
      <el-checkbox v-for="r in allRoles" :key="r.id" :value="r.id">
        {{ r.name }}（{{ r.code }}）
      </el-checkbox>
    </el-checkbox-group>
    <el-select v-else v-model="assign.selected" multiple filterable style="width: 100%">
      <el-option v-for="g in allGroups" :key="g.id" :label="g.name" :value="g.id" />
    </el-select>
    <template #footer>
      <el-button @click="assign.visible = false">取消</el-button>
      <el-button type="primary" @click="submitAssign">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="password.visible" title="密码登录已开通" width="460px">
    <p>
      账号 <b>{{ password.username }}</b>
      {{ password.created ? '已在 Keycloak 中创建' : '已重置密码' }}，临时密码（只显示这一次）：
    </p>
    <el-input :model-value="password.value" readonly data-test="temp-password">
      <template #append>
        <el-button @click="copyPassword">复制</el-button>
      </template>
    </el-input>
    <p class="muted small">用户首次登录时必须修改密码。请通过安全渠道转交。</p>
    <template #footer>
      <el-button type="primary" @click="password.visible = false">我已记下</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
.small {
  font-size: 12px;
}
.dept-line {
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 22px;
}
.identity-tag {
  margin: 0 6px 6px 0;
}
</style>
