<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getDirectoryDepartments, searchPrincipals } from '@/api/knowledge'
import type {
  AclEffect,
  AclEntryOut,
  AclPermission,
  DirectoryDepartment,
  PrincipalOption,
  PrincipalType,
} from '@/api/types'
import { permissionLabels, principalLabel, principalLabels } from '@/utils/document'

const entries = defineModel<AclEntryOut[]>({ required: true })
const props = defineProps<{
  disabled?: boolean
  /** When true, new rows are DENY-only (used under inherit). */
  denyOnly?: boolean
}>()
const { t } = useI18n()

const permissionOptions = computed(() => permissionLabels())
const principalOptions = computed(() => principalLabels())
const effectOptions = computed(() => ({
  allow: t('knowledge.acl.effectAllow'),
  deny: t('knowledge.acl.effectDeny'),
}))

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
  effect: (props.denyOnly ? 'deny' : 'allow') as AclEffect,
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

function filterDepartment(keyword: string, node: Record<string, unknown>): boolean {
  const dept = node as unknown as DirectoryDepartment
  return (dept.path_name ?? dept.name).toLowerCase().includes(keyword.toLowerCase())
}

function optionOf(type: PrincipalType, id: string): PrincipalOption | undefined {
  return options.value.find((o) => o.type === type && o.id === id)
}

function nameOf(type: PrincipalType, id: string): string {
  if (type === 'dept') return departmentNames.value.get(id) ?? id
  return optionOf(type, id)?.name ?? id
}

function add(): void {
  const effect: AclEffect = props.denyOnly ? 'deny' : draft.effect
  const permission: AclPermission = effect === 'deny' ? 'read' : draft.permission
  const next = [...entries.value]
  for (const id of draft.ids) {
    const existing = next.find(
      (e) =>
        e.principal_type === draft.type &&
        e.principal_id === id &&
        (e.effect ?? 'allow') === effect,
    )
    if (existing) {
      existing.permission = permission
      existing.effect = effect
    } else {
      next.push({
        principal_type: draft.type,
        principal_id: id,
        permission,
        effect,
        principal_name: nameOf(draft.type, id),
        principal_detail: draft.type === 'user' ? optionOf(draft.type, id)?.description : null,
        principal_active: true,
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
          v-for="(label, key) in principalOptions"
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
        :placeholder="t('knowledge.acl.deptPlaceholder')"
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
        :placeholder="t(`knowledge.acl.searchPlaceholder.${draft.type}`)"
        class="picker"
      >
        <el-option v-for="o in options" :key="o.id" :label="o.name" :value="o.id">
          <span>{{ o.name }}</span>
          <span v-if="o.description" class="option-desc">{{ o.description }}</span>
        </el-option>
      </el-select>
      <el-select
        v-if="!denyOnly"
        v-model="draft.effect"
        style="width: 96px"
      >
        <el-option
          v-for="(label, key) in effectOptions"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-select
        v-if="!denyOnly && draft.effect !== 'deny'"
        v-model="draft.permission"
        style="width: 96px"
      >
        <el-option
          v-for="(label, key) in permissionOptions"
          :key="key"
          :label="label"
          :value="key"
        />
      </el-select>
      <el-button type="primary" :disabled="!draft.ids.length" @click="add">{{
        t('common.add')
      }}</el-button>
    </div>

    <el-table :data="entries" size="small" :empty-text="t('knowledge.acl.empty')" max-height="320">
      <el-table-column :label="t('knowledge.acl.type')" width="90">
        <template #default="{ row }">
          <el-tag effect="plain" size="small">
            {{ principalLabel((row as AclEntryOut).principal_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('common.name')" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span :class="{ 'entry--inactive': (row as AclEntryOut).principal_active === false }">
            {{ (row as AclEntryOut).principal_name ?? (row as AclEntryOut).principal_id }}
          </span>
          <span v-if="(row as AclEntryOut).principal_detail" class="option-desc">
            {{ (row as AclEntryOut).principal_detail }}
          </span>
          <el-tooltip
            v-if="(row as AclEntryOut).principal_name == null"
            :content="t('knowledge.acl.missingHint')"
          >
            <el-tag type="danger" size="small" class="entry-tag">
              {{ t('knowledge.acl.missing') }}
            </el-tag>
          </el-tooltip>
          <el-tooltip
            v-else-if="(row as AclEntryOut).principal_active === false"
            :content="t('knowledge.acl.inactiveHint')"
          >
            <el-tag type="danger" size="small" effect="plain" class="entry-tag">
              {{ t('knowledge.acl.inactive') }}
            </el-tag>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column :label="t('knowledge.acl.effect')" width="110">
        <template #default="{ row }">
          <el-tag
            :type="((row as AclEntryOut).effect ?? 'allow') === 'deny' ? 'danger' : 'success'"
            size="small"
            effect="plain"
          >
            {{
              ((row as AclEntryOut).effect ?? 'allow') === 'deny'
                ? t('knowledge.acl.effectDeny')
                : t('knowledge.acl.effectAllow')
            }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('knowledge.acl.permission')" width="120">
        <template #default="{ row }">
          <template v-if="((row as AclEntryOut).effect ?? 'allow') === 'deny'">—</template>
          <el-select
            v-else
            v-model="(row as AclEntryOut).permission"
            size="small"
            :disabled="disabled"
          >
            <el-option
              v-for="(label, key) in permissionOptions"
              :key="key"
              :label="label"
              :value="key"
            />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column v-if="!disabled" :label="t('common.actions')" width="70">
        <template #default="{ $index }">
          <el-button link type="danger" @click="remove($index)">{{ t('common.remove') }}</el-button>
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
.entry--inactive {
  color: var(--el-text-color-secondary);
  text-decoration: line-through;
}
.entry-tag {
  margin-left: 6px;
}
</style>
