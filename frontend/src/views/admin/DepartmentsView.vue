<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import type { TreeInstance } from 'element-plus'
import { createDepartment, deleteDepartment, listUsers, updateDepartment } from '@/api/admin'
import type { DepartmentNode, User } from '@/api/types'
import { useDepartmentTree } from '@/composables/useDepartmentTree'
import { SOURCE_LABEL } from './directory/meta'

const { tree, loading, reload } = useDepartmentTree()
const selected = ref<DepartmentNode | null>(null)
const members = ref<User[]>([])
const membersTotal = ref(0)
const membersLoading = ref(false)
const showArchived = ref(false)
const keyword = ref('')
const treeRef = ref<TreeInstance>()

function prune(nodes: DepartmentNode[]): DepartmentNode[] {
  return nodes
    .filter((n) => n.status !== 'archived')
    .map((n) => ({ ...n, children: prune(n.children) }))
}

const visibleTree = computed(() => (showArchived.value ? tree.value : prune(tree.value)))
const archivedCount = computed(() => {
  const walk = (nodes: DepartmentNode[]): number =>
    nodes.reduce((n, d) => n + (d.status === 'archived' ? 1 : 0) + walk(d.children), 0)
  return walk(tree.value)
})
const expandedKeys = computed(() => visibleTree.value.map((n) => n.id))

const dialog = reactive({
  visible: false,
  editingId: null as string | null,
  managed: false,
  form: { name: '', parent_id: null as string | null, sort_order: 0 },
})
const formRef = ref<FormInstance>()
const rules: FormRules = { name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }] }

function isManaged(node: DepartmentNode): boolean {
  return node.source !== 'local'
}

function openCreate(parent: DepartmentNode | null): void {
  dialog.editingId = null
  dialog.managed = false
  dialog.form = { name: '', parent_id: parent?.id ?? null, sort_order: 0 }
  dialog.visible = true
}

function openEdit(node: DepartmentNode): void {
  dialog.editingId = node.id
  dialog.managed = isManaged(node)
  dialog.form = { name: node.name, parent_id: node.parent_id, sort_order: node.sort_order }
  dialog.visible = true
}

async function submit(): Promise<void> {
  if (!(await formRef.value?.validate().catch(() => false))) return
  if (dialog.editingId) {
    await updateDepartment(
      dialog.editingId,
      dialog.managed ? { sort_order: dialog.form.sort_order } : dialog.form,
    )
  } else {
    await createDepartment(dialog.form)
  }
  ElMessage.success('保存成功')
  dialog.visible = false
  await reload()
}

async function remove(node: DepartmentNode): Promise<void> {
  await ElMessageBox.confirm(`确定删除部门「${node.name}」吗？`, '提示', { type: 'warning' })
  await deleteDepartment(node.id)
  ElMessage.success('已删除')
  if (selected.value?.id === node.id) selected.value = null
  await reload()
}

async function loadMembers(): Promise<void> {
  if (!selected.value) {
    members.value = []
    return
  }
  membersLoading.value = true
  try {
    const page = await listUsers({ department_id: selected.value.id, size: 50 })
    members.value = page.items
    membersTotal.value = page.total
  } finally {
    membersLoading.value = false
  }
}

function filterNode(value: string, data: Record<string, unknown>): boolean {
  if (!value) return true
  const dept = data as unknown as DepartmentNode
  return (dept.path_name ?? dept.name).toLowerCase().includes(value.toLowerCase())
}

watch(keyword, (v) => treeRef.value?.filter(v))
watch(selected, loadMembers)
onMounted(reload)
</script>

<template>
  <el-row :gutter="16">
    <el-col :span="10">
      <el-card shadow="never">
        <template #header>
          <div class="card-header">
            <span>部门树</span>
            <el-button
              v-permission="'admin:dept'"
              type="primary"
              size="small"
              @click="openCreate(null)"
            >
              新增根部门
            </el-button>
          </div>
        </template>
        <div class="toolbar">
          <el-input
            v-model="keyword"
            placeholder="搜索部门（支持完整路径）"
            clearable
            size="small"
          />
          <el-checkbox v-if="archivedCount" v-model="showArchived" size="small">
            显示已归档（{{ archivedCount }}）
          </el-checkbox>
        </div>
        <el-tree
          ref="treeRef"
          v-loading="loading"
          :data="visibleTree"
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          :default-expanded-keys="expandedKeys"
          :filter-node-method="filterNode"
          highlight-current
          :expand-on-click-node="false"
          empty-text="暂无部门"
          data-test="department-tree"
          @current-change="(d: DepartmentNode) => (selected = d)"
        >
          <template #default="{ data }">
            <div class="tree-node" :class="{ 'tree-node--archived': data.status === 'archived' }">
              <span class="tree-node__label">
                {{ data.name }}
                <el-tag
                  v-if="isManaged(data as DepartmentNode)"
                  size="small"
                  effect="plain"
                  class="tree-node__tag"
                >
                  {{ SOURCE_LABEL[(data as DepartmentNode).source] ?? data.source }}
                </el-tag>
                <el-tag
                  v-if="data.status === 'archived'"
                  size="small"
                  type="info"
                  class="tree-node__tag"
                >
                  已归档
                </el-tag>
              </span>
              <span v-permission="'admin:dept'" class="tree-node__actions">
                <el-button link type="primary" size="small" @click.stop="openCreate(data)">
                  添加子部门
                </el-button>
                <el-button link type="primary" size="small" @click.stop="openEdit(data)">
                  编辑
                </el-button>
                <el-button
                  v-if="!isManaged(data as DepartmentNode)"
                  link
                  type="danger"
                  size="small"
                  @click.stop="remove(data)"
                  >删除</el-button
                >
              </span>
            </div>
          </template>
        </el-tree>
      </el-card>
    </el-col>
    <el-col :span="14">
      <el-card shadow="never">
        <template #header>
          <template v-if="selected">
            <div>「{{ selected.name }}」成员（含下级，共 {{ membersTotal }} 人）</div>
            <div class="muted small">{{ selected.path_name }}</div>
          </template>
          <template v-else>请选择部门</template>
        </template>
        <el-table v-loading="membersLoading" :data="members" empty-text="暂无成员">
          <el-table-column prop="username" label="用户名" />
          <el-table-column prop="display_name" label="姓名" />
          <el-table-column label="职务">
            <template #default="{ row }">{{ row.job_title || '-' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_active ? 'success' : 'info'">
                {{ row.is_active ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-col>
  </el-row>

  <el-dialog
    v-model="dialog.visible"
    :title="dialog.editingId ? '编辑部门' : '新增部门'"
    width="480px"
  >
    <el-alert
      v-if="dialog.managed"
      type="info"
      :closable="false"
      show-icon
      title="该部门由组织同步维护，名称和上级只读，请在源系统中修改。"
      style="margin-bottom: 16px"
    />
    <el-form ref="formRef" :model="dialog.form" :rules="rules" label-width="88px">
      <el-form-item label="部门名称" prop="name">
        <el-input v-model="dialog.form.name" maxlength="128" :disabled="dialog.managed" />
      </el-form-item>
      <el-form-item label="上级部门">
        <el-tree-select
          v-model="dialog.form.parent_id"
          :data="visibleTree"
          node-key="id"
          :props="{ label: 'name', children: 'children' }"
          check-strictly
          filterable
          clearable
          :disabled="dialog.managed"
          placeholder="无（根部门）"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item label="排序">
        <el-input-number v-model="dialog.form.sort_order" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog.visible = false">取消</el-button>
      <el-button type="primary" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.tree-node {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-right: 8px;
}

.tree-node__label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.tree-node__tag {
  transform: scale(0.9);
}

.tree-node--archived .tree-node__label {
  color: var(--ekb-text-3);
  text-decoration: line-through;
}

.tree-node__actions {
  visibility: hidden;
}

.tree-node:hover .tree-node__actions {
  visibility: visible;
}

.small {
  font-size: 12px;
}
</style>
