<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { getDirectoryDepartments, searchPrincipals } from '@/api/knowledge'
import type {
  AclEntryOut,
  AclPermission,
  DirectoryDepartment,
  PrincipalOption,
  PrincipalType,
} from '@/api/types'
import { PERMISSION_LABELS, PRINCIPAL_LABELS } from '@/utils/document'

const entries = defineModel<AclEntryOut[]>({ required: true })
const props = defineProps<{ disabled?: boolean }>()

const departments = ref<DirectoryDepartment[]>([])
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

const draft = reactive({
  type: 'group' as PrincipalType,
  ids: [] as string[],
  permission: 'read' as AclPermission,
})
const options = ref<PrincipalOption[]>([])
const searching = ref(false)

async function search(keyword: string): Promise<void> {
  searching.value = true
  try {
    options.value = await searchPrincipals(draft.type, keyword || undefined)
  } finally {
    searching.value = false
  }
}

function changeType(): void {
  draft.ids = []
  options.value = []
  if (draft.type !== 'dept') void search('')
}

// Matches on the full path so "织造车间" under different factories can be told apart.
function filterDepartment(keyword: string, node: Record<string, unknown>): boolean {
  const dept = node as unknown as DirectoryDepartment
  return (dept.path_name ?? dept.name).toLowerCase().includes(keyword.toLowerCase())
}

function nameOf(type: PrincipalType, id: string): string {
  if (type === 'dept') return departmentNames.value.get(id) ?? id
  return options.value.find((o) => o.type === type && o.id === id)?.name ?? id
}

function add(): void {
  const next = [...entries.value]
  for (const id of draft.ids) {
    const existing = next.find((e) => e.principal_type === draft.type && e.principal_id === id)
    if (existing) {
      existing.permission = draft.permission
    } else {
      next.push({
        principal_type: draft.type,
        principal_id: id,
        permission: draft.permission,
        principal_name: nameOf(draft.type, id),
      })
    }
  }
  entries.value = next
  draft.ids = []
}

function remove(index: number): void {
  entries.value = entries.value.filter((_, i) => i !== index)
}

onMounted(async () => {
  if (props.disabled) return
  departments.value = await getDirectoryDepartments()
  await search('')
})
</script>

<template>
  <div class="acl-editor">
    <div v-if="!disabled" class="add-row">
      <el-select v-model="draft.type" style="width: 110px" @change="changeType">
        <el-option
          v-for="(label, key) in PRINCIPAL_LABELS"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-tree-select
        v-if="draft.type === 'dept'"
        v-model="draft.ids"
        :data="departments"
        :props="{ label: 'name', children: 'children' }"
        node-key="id"
        multiple
        check-strictly
        filterable
        :filter-node-method="filterDepartment"
        placeholder="选择部门（含下级部门）"
        class="picker"
      >
        <template #label="{ value }">{{ departmentNames.get(value) ?? value }}</template>
      </el-tree-select>
      <el-select
        v-else
        v-model="draft.ids"
        multiple
        filterable
        remote
        :remote-method="search"
        :loading="searching"
        :placeholder="`搜索${PRINCIPAL_LABELS[draft.type]}`"
        class="picker"
      >
        <el-option v-for="o in options" :key="o.id" :label="o.name" :value="o.id">
          <span>{{ o.name }}</span>
          <span v-if="o.description" class="option-desc">{{ o.description }}</span>
        </el-option>
      </el-select>
      <el-select v-model="draft.permission" style="width: 96px">
        <el-option
          v-for="(label, key) in PERMISSION_LABELS"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-button type="primary" :disabled="!draft.ids.length" @click="add">添加</el-button>
    </div>

    <el-table :data="entries" size="small" empty-text="暂无授权" max-height="320">
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag effect="plain" size="small">
            {{ PRINCIPAL_LABELS[(row as AclEntryOut).principal_type] }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="名称" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          {{ (row as AclEntryOut).principal_name ?? (row as AclEntryOut).principal_id }}
        </template>
      </el-table-column>
      <el-table-column label="权限" width="120">
        <template #default="{ row }">
          <el-select v-model="(row as AclEntryOut).permission" size="small" :disabled="disabled">
            <el-option
              v-for="(label, key) in PERMISSION_LABELS"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column v-if="!disabled" label="操作" width="70">
        <template #default="{ $index }">
          <el-button link type="danger" @click="remove($index)">移除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.add-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.picker {
  flex: 1;
  min-width: 0;
}
.option-desc {
  margin-left: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
