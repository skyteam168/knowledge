<script setup lang="ts">
import { onActivated, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { deleteApiClient, listApiClients, updateApiClient } from '@/api/openApi'
import type { ApiClient, ApiClientStatus } from '@/api/types'
import { formatDateTime } from '@/utils/format'
import ApiClientEditor from './ApiClientEditor.vue'
import { PRINCIPAL_LABEL, SCOPE_INFO } from './meta'

const router = useRouter()
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
      `停用后「${row.name}」的所有密钥将立即无法调用，确定停用吗？`,
      '停用应用',
      { type: 'warning' },
    )
  }
  await updateApiClient(row.id, { status: disable ? 'disabled' : 'active' })
  ElMessage.success(disable ? '已停用' : '已启用')
  await load()
}

async function remove(row: ApiClient): Promise<void> {
  await ElMessageBox.confirm(
    `删除「${row.name}」将同时删除其全部密钥，调用日志保留。此操作不可恢复。`,
    '删除应用',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await deleteApiClient(row.id)
  ElMessage.success('已删除')
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
        <h2 class="page-header__title">开放平台</h2>
        <p class="page-header__desc">
          为集团内其他 Agent / 系统签发 API 密钥：按知识库授权上限 +
          绑定身份的文档权限双重限定可见内容，所有调用均有日志与审计。
        </p>
      </div>
      <el-button type="primary" :icon="Plus" data-test="new-client" @click="openCreate">
        新建接入应用
      </el-button>
    </div>

    <el-card shadow="never">
      <el-form :inline="true" @submit.prevent="search">
        <el-form-item>
          <el-input v-model="query.keyword" placeholder="应用名称 / 联系人" clearable />
        </el-form-item>
        <el-form-item>
          <el-select v-model="query.status" placeholder="全部状态" clearable style="width: 120px">
            <el-option label="启用" value="active" />
            <el-option label="停用" value="disabled" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="rows" empty-text="暂无接入应用" data-test="client-table">
        <el-table-column label="应用" min-width="200">
          <template #default="{ row }">
            <button type="button" class="name-link" @click="openDetail(row as ApiClient)">
              {{ row.name }}
            </button>
            <div class="muted small">
              {{ [row.owner_department_name, row.contact].filter(Boolean).join(' · ') || '—' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="授权知识库" min-width="180">
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
        <el-table-column label="代理身份" min-width="160">
          <template #default="{ row }">
            <div
              v-for="p in (row as ApiClient).principals.slice(0, 2)"
              :key="p.type + p.id"
              class="small"
            >
              <span class="muted">{{ PRINCIPAL_LABEL[p.type] }}：</span>{{ p.name ?? p.id }}
            </div>
            <div v-if="row.principals.length > 2" class="muted small">
              等 {{ row.principals.length }} 项
            </div>
          </template>
        </el-table-column>
        <el-table-column label="能力" width="150">
          <template #default="{ row }">
            <el-tag
              v-for="s in (row as ApiClient).scopes"
              :key="s"
              size="small"
              type="success"
              effect="light"
              class="tag"
            >
              {{ SCOPE_INFO[s].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span v-if="expired(row as ApiClient)" class="status status--off">已过期</span>
            <span v-else-if="row.status === 'active'" class="status status--on">启用</span>
            <span v-else class="status status--off">停用</span>
          </template>
        </el-table-column>
        <el-table-column label="密钥" width="70" align="center" prop="active_keys" />
        <el-table-column label="今日调用" width="90" align="right" prop="calls_today" />
        <el-table-column label="最近调用" width="160">
          <template #default="{ row }">
            <span class="small">{{
              row.last_used_at ? formatDateTime(row.last_used_at) : '—'
            }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as ApiClient)">详情</el-button>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onCommand(row as ApiClient, cmd)"
            >
              <el-button link type="primary">更多</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="edit">编辑授权</el-dropdown-item>
                  <el-dropdown-item command="toggle">
                    {{ row.status === 'active' ? '停用' : '启用' }}
                  </el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <span class="danger">删除</span>
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
