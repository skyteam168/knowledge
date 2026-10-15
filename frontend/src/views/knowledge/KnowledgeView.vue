<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteKnowledgeBase, listKnowledgeBases } from '@/api/knowledge'
import type { KnowledgeBase } from '@/api/types'
import KbAclDialog from '@/components/knowledge/KbAclDialog.vue'
import KbFormDialog from '@/components/knowledge/KbFormDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { PERMISSION_LABELS, atLeast } from '@/utils/document'
import { formatDateTime } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

const query = reactive({ keyword: '', page: 1, size: 20 })
const rows = ref<KnowledgeBase[]>([])
const total = ref(0)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const page = await listKnowledgeBases({ ...query, keyword: query.keyword || undefined })
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

const form = reactive({ visible: false, kb: null as KnowledgeBase | null })
const acl = reactive({ visible: false, kb: null as KnowledgeBase | null })

function openCreate(): void {
  form.kb = null
  form.visible = true
}

function openEdit(kb: KnowledgeBase): void {
  form.kb = kb
  form.visible = true
}

function openAcl(kb: KnowledgeBase): void {
  acl.kb = kb
  acl.visible = true
}

function onSaved(kb: KnowledgeBase): void {
  if (form.kb) {
    void load()
  } else {
    void router.push({ name: 'knowledge-base', params: { kbId: kb.id } })
  }
}

async function remove(kb: KnowledgeBase): Promise<void> {
  await ElMessageBox.confirm(`确定删除知识库「${kb.name}」吗？`, '提示', { type: 'warning' })
  await deleteKnowledgeBase(kb.id)
  ElMessage.success('已删除')
  await load()
}

function open(kb: KnowledgeBase): void {
  void router.push({ name: 'knowledge-base', params: { kbId: kb.id } })
}

onMounted(load)
</script>

<template>
  <el-card shadow="never">
    <el-form :inline="true" @submit.prevent="search">
      <el-form-item data-guide="kb-search">
        <el-input v-model="query.keyword" placeholder="知识库名称 / 描述" clearable />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">查询</el-button>
        <el-button
          v-permission="'kb:create'"
          data-test="kb-create"
          data-guide="kb-create"
          @click="openCreate"
        >
          新建知识库
        </el-button>
      </el-form-item>
    </el-form>

    <el-table
      v-loading="loading"
      :data="rows"
      data-guide="kb-table"
      empty-text="暂无可访问的知识库"
      row-class-name="clickable"
      @row-click="(row: KnowledgeBase) => open(row)"
    >
      <el-table-column prop="name" label="名称" min-width="160">
        <template #default="{ row }">
          <el-link type="primary" :underline="false">{{ (row as KnowledgeBase).name }}</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
      <el-table-column label="可见范围" width="130">
        <template #default="{ row }">
          <el-tag :type="row.visibility === 'org' ? 'success' : 'info'" effect="plain">
            {{ row.visibility === 'org' ? '组织内可读' : '仅授权成员' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="document_count" label="文档数" width="90" />
      <el-table-column label="我的权限" width="100">
        <template #default="{ row }">
          {{ row.my_permission ? PERMISSION_LABELS[(row as KnowledgeBase).my_permission!] : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{
          formatDateTime((row as KnowledgeBase).updated_at)
        }}</template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <span v-if="atLeast((row as KnowledgeBase).my_permission, 'manage')" @click.stop>
            <el-button
              v-if="auth.can('kb:update')"
              link
              type="primary"
              @click="openEdit(row as KnowledgeBase)"
            >
              编辑
            </el-button>
            <el-button
              v-if="auth.can('kb:update')"
              link
              type="primary"
              @click="openAcl(row as KnowledgeBase)"
            >
              权限
            </el-button>
            <el-button
              v-if="auth.can('kb:delete')"
              link
              type="danger"
              @click="remove(row as KnowledgeBase)"
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

  <KbFormDialog v-model="form.visible" :kb="form.kb" @saved="onSaved" />
  <KbAclDialog v-model="acl.visible" :kb="acl.kb" @saved="load" />
</template>

<style scoped>
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}
:deep(.clickable) {
  cursor: pointer;
}
</style>
