<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  createGroup,
  deleteGroup,
  getGroupMembers,
  listGroups,
  listUsers,
  setGroupMembers,
  updateGroup,
} from '@/api/admin'
import type { Group, User } from '@/api/types'

const query = reactive({ keyword: '', page: 1, size: 20 })
const rows = ref<Group[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listGroups({ ...query, keyword: query.keyword || undefined })
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
const editor = reactive({
  visible: false,
  editingId: null as string | null,
  form: { name: '', description: '' as string | null },
})
const rules: FormRules = { name: [{ required: true, message: '请输入组名', trigger: 'blur' }] }

function openCreate(): void {
  editor.editingId = null
  editor.form = { name: '', description: '' }
  editor.visible = true
}

function openEdit(row: Group): void {
  editor.editingId = row.id
  editor.form = { name: row.name, description: row.description }
  editor.visible = true
}

async function submitEditor(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  const body = { ...editor.form, description: editor.form.description || null }
  if (editor.editingId) {
    await updateGroup(editor.editingId, body)
  } else {
    await createGroup(body)
  }
  ElMessage.success('保存成功')
  editor.visible = false
  await load()
}

async function remove(row: Group): Promise<void> {
  await ElMessageBox.confirm(`确定删除用户组「${row.name}」吗？`, '提示', { type: 'warning' })
  await deleteGroup(row.id)
  ElMessage.success('已删除')
  await load()
}

// ---- members ----------------------------------------------------------------

const members = reactive({
  visible: false,
  group: null as Group | null,
  selected: [] as string[],
  options: [] as User[],
  searching: false,
})

async function openMembers(row: Group): Promise<void> {
  const current = await getGroupMembers(row.id)
  members.group = row
  members.options = current
  members.selected = current.map((u) => u.id)
  members.visible = true
}

async function searchUsers(keyword: string): Promise<void> {
  members.searching = true
  try {
    const page = await listUsers({ keyword: keyword || undefined, size: 50 })
    const chosen = members.options.filter((u) => members.selected.includes(u.id))
    const extra = page.items.filter((u) => !members.selected.includes(u.id))
    members.options = [...chosen, ...extra]
  } finally {
    members.searching = false
  }
}

async function submitMembers(): Promise<void> {
  if (!members.group) return
  await setGroupMembers(members.group.id, members.selected)
  ElMessage.success('成员已更新')
  members.visible = false
  await load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <el-form :inline="true" @submit.prevent="search">
      <el-form-item>
        <el-input v-model="query.keyword" placeholder="组名" clearable />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
        <el-button v-permission="'admin:group'" @click="openCreate">新建用户组</el-button>
      </el-form-item>
    </el-form>

    <el-table v-loading="loading" :data="rows" empty-text="暂无用户组">
      <el-table-column prop="name" label="组名" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="200" />
      <el-table-column label="来源" width="110">
        <template #default="{ row }">
          <el-tag :type="row.source === 'keycloak' ? 'primary' : 'info'" effect="plain">
            {{ row.source === 'keycloak' ? 'Keycloak' : '本地' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="member_count" label="成员数" width="90" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <span v-permission="'admin:group'">
            <el-button link type="primary" @click="openMembers(row as Group)">成员</el-button>
            <el-button
              link
              type="primary"
              :disabled="row.source === 'keycloak'"
              @click="openEdit(row as Group)"
            >
              编辑
            </el-button>
            <el-button
              link
              type="danger"
              :disabled="row.source === 'keycloak'"
              @click="remove(row as Group)"
            >
              删除
            </el-button>
          </span>
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
    :title="editor.editingId ? '编辑用户组' : '新建用户组'"
    width="480px"
  >
    <el-form ref="formRef" :model="editor.form" :rules="rules" label-width="64px">
      <el-form-item label="组名" prop="name">
        <el-input v-model="editor.form.name" maxlength="128" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="editor.form.description" type="textarea" :rows="3" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="editor.visible = false">取消</el-button>
      <el-button type="primary" @click="submitEditor">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog
    v-model="members.visible"
    :title="`成员管理：${members.group?.name ?? ''}`"
    width="560px"
  >
    <el-alert
      v-if="members.group?.source === 'keycloak'"
      type="info"
      :closable="false"
      show-icon
      title="Keycloak 同步的成员会在用户下次登录时按令牌重新同步，此处仅维护本地成员"
      style="margin-bottom: 16px"
    />
    <el-select
      v-model="members.selected"
      multiple
      filterable
      remote
      :remote-method="searchUsers"
      :loading="members.searching"
      placeholder="搜索用户名 / 姓名添加成员"
      style="width: 100%"
    >
      <el-option
        v-for="u in members.options"
        :key="u.id"
        :label="u.display_name ? `${u.display_name}（${u.username}）` : u.username"
        :value="u.id"
      />
    </el-select>
    <template #footer>
      <el-button @click="members.visible = false">取消</el-button>
      <el-button type="primary" @click="submitMembers">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
