<script setup lang="ts">
import { onActivated, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { deleteApiClient, listApiClients, updateApiClient } from '@/api/openApi'
import type { ApiClient, ApiClientStatus } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import ApiClientEditor from './ApiClientEditor.vue'
import { principalLabel, scopeLabel } from './meta'

const router = useRouter()
const { t } = useI18n()
const query = reactive({
  keyword: '',
  status: '' as ApiClientStatus | '',
  page: 1,
  size: 20,
})
const rows = ref<ApiClient[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listApiClients({
      page: query.page,
      size: query.size,
      keyword: query.keyword || undefined,
      status: query.status || undefined,
    })
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

const editor = reactive({ visible: false, client: null as ApiClient | null })

function openCreate(): void {
  editor.client = null
  editor.visible = true
}

function openEdit(row: ApiClient): void {
  editor.client = row
  editor.visible = true
}

function onSaved(client: ApiClient): void {
  if (!editor.client) {
    void router.push({ name: 'admin-open-api-client', params: { clientId: client.id } })
    return
  }
  void load()
}

async function toggle(row: ApiClient): Promise<void> {
  const disable = row.status === 'active'
  if (disable) {
    await ElMessageBox.confirm(
      t('openApi.list.disableConfirm', { name: row.name }),
      t('openApi.disableDialog.title'),
      { type: 'warning' },
    )
  }
  await updateApiClient(row.id, { status: disable ? 'disabled' : 'active' })
  ElMessage.success(disable ? t('openApi.toast.disabled') : t('openApi.toast.enabled'))
  await load()
}

async function remove(row: ApiClient): Promise<void> {
  await ElMessageBox.confirm(
    t('openApi.list.deleteConfirm', { name: row.name }),
    t('openApi.list.deleteTitle'),
    {
      type: 'warning',
      confirmButtonText: t('common.delete'),
      confirmButtonClass: 'el-button--danger',
    },
  )
  await deleteApiClient(row.id)
  ElMessage.success(t('common.deleted'))
  await load()
}

function onCommand(row: ApiClient, command: string): void {
  const action = command === 'toggle' ? toggle : command === 'delete' ? remove : null
  if (command === 'edit') openEdit(row)
  else action?.(row).catch(() => undefined)
}

function expired(row: ApiClient): boolean {
  return !!row.expires_at && new Date(row.expires_at).getTime() <= Date.now()
}

function openDetail(row: ApiClient): void {
  void router.push({ name: 'admin-open-api-client', params: { clientId: row.id } })
}

let firstActivation = true
onMounted(load)
onActivated(() => {
  if (firstActivation) firstActivation = false
  else void load()
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-header__title">{{ t('openApi.list.title') }}</h2>
        <p class="page-header__desc">{{ t('openApi.list.desc') }}</p>
      </div>
      <el-button type="primary" :icon="Plus" data-test="new-client" @click="openCreate">
        {{ t('openApi.list.newClient') }}
      </el-button>
    </div>

    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="search">
        <el-form-item>
          <el-input
            v-model="query.keyword"
            :placeholder="t('openApi.list.keywordPlaceholder')"
            clearable
          />
        </el-form-item>
        <el-form-item>
          <el-select
            v-model="query.status"
            :placeholder="t('openApi.list.statusPlaceholder')"
            clearable
            style="width: 120px"
          >
            <el-option :label="t('common.enabled')" value="active" />
            <el-option :label="t('common.disabled')" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">{{ t('openApi.list.query') }}</el-button>
        </el-form-item>
      </el-form>

      <el-table
        v-loading="loading"
        :data="rows"
        :empty-text="t('openApi.list.empty')"
        data-test="client-table"
      >
        <el-table-column :label="t('openApi.list.colClient')" min-width="200">
          <template #default="{ row }">
            <button type="button" class="name-link" @click="openDetail(row as ApiClient)">
              {{ row.name }}
            </button>
            <div class="muted small">
              {{ [row.owner_department_name, row.contact].filter(Boolean).join(' · ') || '—' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('openApi.list.colKbs')" min-width="180">
          <template #default="{ row }">
            <el-tag
              v-for="kb in (row as ApiClient).kbs.slice(0, 2)"
              :key="kb.id"
              size="small"
              effect="plain"
              class="tag"
            >
              {{ kb.name }}
            </el-tag>
            <el-tag v-if="row.kbs.length > 2" size="small" type="info" class="tag">
              +{{ row.kbs.length - 2 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('openApi.list.colPrincipals')" min-width="160">
          <template #default="{ row }">
            <div
              v-for="p in (row as ApiClient).principals.slice(0, 2)"
              :key="p.type + p.id"
              class="small"
            >
              <span class="muted">{{
                t('openApi.list.principalItem', { type: principalLabel(p.type) })
              }}</span
              >{{ p.name ?? p.id }}
            </div>
            <div v-if="row.principals.length > 2" class="muted small">
              {{ t('openApi.list.morePrincipals', { n: row.principals.length }) }}
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('openApi.list.colScopes')" width="150">
          <template #default="{ row }">
            <el-tag
              v-for="s in (row as ApiClient).scopes"
              :key="s"
              size="small"
              type="success"
              effect="light"
              class="tag"
            >
              {{ scopeLabel(s) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.status')" width="90">
          <template #default="{ row }">
            <span v-if="expired(row as ApiClient)" class="status status--off">{{
              t('openApi.fields.expired')
            }}</span>
            <span v-else-if="row.status === 'active'" class="status status--on">{{
              t('common.enabled')
            }}</span>
            <span v-else class="status status--off">{{ t('common.disabled') }}</span>
          </template>
        </el-table-column>
        <el-table-column
          :label="t('openApi.list.colKeys')"
          width="70"
          align="center"
          prop="active_keys"
        />
        <el-table-column
          :label="t('openApi.list.colCallsToday')"
          width="90"
          align="right"
          prop="calls_today"
        />
        <el-table-column :label="t('openApi.list.colLastCall')" width="160">
          <template #default="{ row }">
            <span class="small">{{
              row.last_used_at ? formatDateTime(row.last_used_at) : '—'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as ApiClient)">{{
              t('common.detail')
            }}</el-button>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onCommand(row as ApiClient, cmd)"
            >
              <el-button link type="primary">{{ t('openApi.list.more') }}</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">{{
                    t('openApi.actions.editAccess')
                  }}</el-dropdown-item>
                  <el-dropdown-item command="toggle">
                    {{
                      row.status === 'active'
                        ? t('openApi.actions.disable')
                        : t('openApi.actions.enable')
                    }}
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <span class="danger">{{ t('common.delete') }}</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
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

    <ApiClientEditor v-model="editor.visible" :client="editor.client" @saved="onSaved" />
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 16px;
}
.page-header__title {
  margin: 0 0 4px;
  font-size: 18px;
  font-weight: 600;
}
.page-header__desc {
  max-width: 720px;
  margin: 0;
  font-size: 13px;
  color: var(--ekb-text-3);
}
.name-link {
  padding: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--ekb-primary);
  background: none;
  border: 0;
  cursor: pointer;
}
.name-link:hover {
  text-decoration: underline;
}
.small {
  font-size: 12px;
}
.tag {
  margin: 2px 4px 2px 0;
}
.status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.status::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.status--on::before {
  background: var(--el-color-success);
}
.status--off {
  color: var(--ekb-text-3);
}
.status--off::before {
  background: var(--ekb-text-3);
}
.danger {
  color: var(--el-color-danger);
}
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
</style>
