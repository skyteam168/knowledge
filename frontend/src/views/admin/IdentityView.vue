<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import {
  addIdentifier,
  createCanonical,
  getCanonical,
  listCanonical,
  listIdentityConflicts,
} from '@/api/identity'
import type { CanonicalEntity, IdentifierOut } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

const { t } = useI18n()

const tab = ref<'list' | 'conflicts'>('list')
const loading = ref(false)
const items = ref<CanonicalEntity[]>([])
const total = ref(0)
const page = ref(1)
const q = ref('')
const objectType = ref('')

const drawer = ref(false)
const detail = ref<CanonicalEntity | null>(null)
const detailLoading = ref(false)

const createDialog = ref(false)
const createSaving = ref(false)
const createFormRef = ref<FormInstance>()
const createForm = reactive({ object_type: 'device', display_name: '' })
const createRules: FormRules = {
  object_type: [{ required: true, message: () => t('identity.typeRequired'), trigger: 'blur' }],
  display_name: [{ required: true, message: () => t('identity.nameRequired'), trigger: 'blur' }],
}

const idDialog = ref(false)
const idSaving = ref(false)
const idFormRef = ref<FormInstance>()
const idForm = reactive({ system: '', external_id: '', id_kind: 'external_id', is_primary: false })

async function load(): Promise<void> {
  loading.value = true
  try {
    const res =
      tab.value === 'conflicts'
        ? await listIdentityConflicts({ page: page.value, size: 20 })
        : await listCanonical({
            page: page.value,
            size: 20,
            q: q.value.trim() || undefined,
            object_type: objectType.value.trim() || undefined,
          })
    items.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

async function openDetail(row: CanonicalEntity): Promise<void> {
  drawer.value = true
  detailLoading.value = true
  try {
    detail.value = await getCanonical(row.id)
  } finally {
    detailLoading.value = false
  }
}

async function submitCreate(): Promise<void> {
  if (!(await createFormRef.value?.validate().catch(() => false))) return
  createSaving.value = true
  try {
    await createCanonical({
      object_type: createForm.object_type.trim(),
      display_name: createForm.display_name.trim(),
    })
    createDialog.value = false
    ElMessage.success(t('identity.saveOk'))
    await load()
  } finally {
    createSaving.value = false
  }
}

function openAddId(): void {
  idForm.system = ''
  idForm.external_id = ''
  idForm.id_kind = 'external_id'
  idForm.is_primary = false
  idDialog.value = true
}

async function submitId(): Promise<void> {
  if (!detail.value) return
  if (!idForm.system.trim() || !idForm.external_id.trim()) {
    ElMessage.warning(t('identity.idRequired'))
    return
  }
  idSaving.value = true
  try {
    await addIdentifier(detail.value.id, {
      system: idForm.system.trim(),
      external_id: idForm.external_id.trim(),
      id_kind: idForm.id_kind.trim() || 'external_id',
      is_primary: idForm.is_primary,
    })
    idDialog.value = false
    ElMessage.success(t('identity.saveOk'))
    detail.value = await getCanonical(detail.value.id)
    await load()
  } finally {
    idSaving.value = false
  }
}

function onTabChange(): void {
  page.value = 1
  void load()
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" class="identity-page">
    <template #header>
      <div class="header">
        <div>
          <div class="title">{{ t('identity.title') }}</div>
          <div class="hint">{{ t('identity.hint') }}</div>
        </div>
        <el-button type="primary" @click="createDialog = true">{{ t('identity.create') }}</el-button>
      </div>
    </template>

    <el-tabs v-model="tab" @tab-change="onTabChange">
      <el-tab-pane :label="t('identity.tabList')" name="list" />
      <el-tab-pane :label="t('identity.tabConflicts')" name="conflicts" />
    </el-tabs>

    <div v-if="tab === 'list'" class="filters">
      <el-input v-model="q" :placeholder="t('identity.search')" clearable style="width: 220px" />
      <el-input
        v-model="objectType"
        :placeholder="t('identity.objectType')"
        clearable
        style="width: 160px"
      />
      <el-button type="primary" @click="load">{{ t('common.search') }}</el-button>
    </div>

    <el-table v-loading="loading" :data="items" size="small" @row-click="openDetail">
      <el-table-column prop="display_name" :label="t('identity.displayName')" min-width="160" />
      <el-table-column prop="object_type" :label="t('identity.objectType')" width="120" />
      <el-table-column prop="status" :label="t('common.status')" width="100" />
      <el-table-column :label="t('identity.updated')" width="170">
        <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
      </el-table-column>
      <template #empty>
        <EmptyState :description="t('identity.empty')" />
      </template>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        layout="prev, pager, next"
        :page-size="20"
        :total="total"
        @current-change="load"
      />
    </div>
  </el-card>

  <el-drawer v-model="drawer" size="480px" :title="t('identity.detail')">
    <div v-loading="detailLoading">
      <template v-if="detail">
        <p><b>{{ detail.display_name }}</b> · {{ detail.object_type }} · {{ detail.status }}</p>
        <p class="mono">{{ detail.id }}</p>
        <div class="id-head">
          <span>{{ t('identity.identifiers') }}</span>
          <el-button size="small" type="primary" @click="openAddId">{{ t('identity.addId') }}</el-button>
        </div>
        <el-table :data="detail.identifiers || []" size="small">
          <el-table-column prop="system" :label="t('identity.system')" width="90" />
          <el-table-column prop="id_kind" label="kind" width="100" />
          <el-table-column prop="external_id" :label="t('identity.externalId')" min-width="120" />
          <el-table-column prop="is_primary" label="P" width="50">
            <template #default="{ row }">
              {{ (row as IdentifierOut).is_primary ? 'Y' : '' }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
  </el-drawer>

  <el-dialog v-model="createDialog" :title="t('identity.create')" width="440px" destroy-on-close>
    <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
      <el-form-item :label="t('identity.objectType')" prop="object_type">
        <el-input v-model="createForm.object_type" maxlength="64" />
      </el-form-item>
      <el-form-item :label="t('identity.displayName')" prop="display_name">
        <el-input v-model="createForm.display_name" maxlength="256" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="createDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="createSaving" @click="submitCreate">
        {{ t('common.save') }}
      </el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="idDialog" :title="t('identity.addId')" width="440px" destroy-on-close>
    <el-form ref="idFormRef" :model="idForm" label-width="100px">
      <el-form-item :label="t('identity.system')">
        <el-input v-model="idForm.system" maxlength="32" placeholder="mes / erp" />
      </el-form-item>
      <el-form-item :label="t('identity.externalId')">
        <el-input v-model="idForm.external_id" maxlength="128" />
      </el-form-item>
      <el-form-item label="kind">
        <el-input v-model="idForm.id_kind" maxlength="32" />
      </el-form-item>
      <el-form-item :label="t('identity.primary')">
        <el-switch v-model="idForm.is_primary" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="idDialog = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="idSaving" @click="submitId">{{ t('common.save') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}
.title {
  font-weight: 600;
}
.hint {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  margin-top: 4px;
}
.filters {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.id-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 16px 0 8px;
}
</style>
