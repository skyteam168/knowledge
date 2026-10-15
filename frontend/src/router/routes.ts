import type { RouteRecordRaw } from 'vue-router'
import type { PermissionRequirement } from '@/utils/permission'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    icon?: string
    /** Any one of these permissions grants access. */
    permission?: PermissionRequirement
    /** Menu entry to highlight for routes that are not in the menu themselves. */
    activeMenu?: string
  }
}

export interface MenuRoute {
  path: string
  name: string
  meta: { title: string; icon: string; permission?: PermissionRequirement }
  children?: MenuRoute[]
}

export const ADMIN_PERMISSIONS = [
  'admin:dept',
  'admin:user',
  'admin:group',
  'admin:role',
  'admin:audit',
  'admin:index',
  'admin:retrieval',
  'admin:openapi',
  'admin:directory',
  'admin:model',
] as const

const adminChildren: (RouteRecordRaw & MenuRoute)[] = [
  {
    path: '/admin/departments',
    name: 'admin-departments',
    component: () => import('@/views/admin/DepartmentsView.vue'),
    meta: { title: '部门管理', icon: 'OfficeBuilding', permission: 'admin:dept' },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/UsersView.vue'),
    meta: { title: '用户管理', icon: 'User', permission: 'admin:user' },
  },
  {
    path: '/admin/directory',
    name: 'admin-directory',
    component: () => import('@/views/admin/directory/DirectorySourcesView.vue'),
    meta: { title: '组织同步', icon: 'Share', permission: 'admin:directory' },
  },
  {
    path: '/admin/groups',
    name: 'admin-groups',
    component: () => import('@/views/admin/GroupsView.vue'),
    meta: { title: '用户组', icon: 'UserFilled', permission: 'admin:group' },
  },
  {
    path: '/admin/roles',
    name: 'admin-roles',
    component: () => import('@/views/admin/RolesView.vue'),
    meta: { title: '角色权限', icon: 'Lock', permission: 'admin:role' },
  },
  {
    path: '/admin/audit-logs',
    name: 'admin-audit-logs',
    component: () => import('@/views/admin/AuditLogsView.vue'),
    meta: { title: '审计日志', icon: 'Document', permission: 'admin:audit' },
  },
  {
    path: '/admin/indexing',
    name: 'admin-indexing',
    component: () => import('@/views/admin/IndexingView.vue'),
    meta: { title: '索引同步', icon: 'Refresh', permission: 'admin:index' },
  },
  {
    path: '/admin/models',
    name: 'admin-models',
    component: () => import('@/views/admin/models/ModelsView.vue'),
    meta: { title: '模型管理', icon: 'Cpu', permission: 'admin:model' },
  },
  {
    path: '/admin/retrieval',
    name: 'admin-retrieval',
    component: () => import('@/views/admin/RetrievalView.vue'),
    meta: { title: '检索策略', icon: 'Operation', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/eval-datasets',
    name: 'admin-eval-datasets',
    component: () => import('@/views/admin/evaluation/EvalDatasetsView.vue'),
    meta: { title: '评测集', icon: 'Files', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/eval-runs',
    name: 'admin-eval-runs',
    component: () => import('@/views/admin/evaluation/EvalRunsView.vue'),
    meta: { title: '离线评测', icon: 'TrendCharts', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/open-api',
    name: 'admin-open-api',
    component: () => import('@/views/admin/openApi/ApiClientsView.vue'),
    meta: { title: '开放平台', icon: 'Connection', permission: 'admin:openapi' },
  },
]

export const CURATION_PERMISSIONS = ['gap:review', 'ko:edit', 'review:approve'] as const

const curationChildren: (RouteRecordRaw & MenuRoute)[] = [
  {
    path: '/curation/gaps',
    name: 'curation-gaps',
    component: () => import('@/views/curation/GapBoardView.vue'),
    meta: { title: '知识缺口', icon: 'Warning', permission: 'gap:review' },
  },
  {
    path: '/curation/kos',
    name: 'curation-kos',
    component: () => import('@/views/curation/KoListView.vue'),
    meta: { title: '知识条目', icon: 'Notebook', permission: CURATION_PERMISSIONS },
  },
  {
    path: '/curation/reviews',
    name: 'curation-reviews',
    component: () => import('@/views/curation/ReviewTasksView.vue'),
    meta: { title: '发布审核', icon: 'Finished', permission: 'review:approve' },
  },
]

export const menuRoutes: (RouteRecordRaw & MenuRoute)[] = [
  {
    path: '/assistant',
    name: 'assistant',
    component: () => import('@/views/assistant/AssistantView.vue'),
    meta: { title: 'AI 助手', icon: 'ChatDotRound', permission: 'chat:use' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/knowledge/KnowledgeView.vue'),
    meta: { title: '知识库', icon: 'Collection', permission: 'kb:read' },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/search/SearchView.vue'),
    meta: { title: '搜索', icon: 'Search', permission: 'search:use' },
  },
  {
    path: '/curation',
    name: 'curation',
    component: () => import('@/views/curation/CurationView.vue'),
    meta: { title: '知识运营', icon: 'Opportunity', permission: CURATION_PERMISSIONS },
    children: curationChildren,
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/admin/AdminView.vue'),
    meta: { title: '管理', icon: 'Setting', permission: ADMIN_PERMISSIONS },
    children: adminChildren,
  },
  {
    path: '/analytics',
    name: 'analytics',
    component: () => import('@/views/analytics/AnalyticsView.vue'),
    meta: { title: '分析', icon: 'DataAnalysis', permission: 'analytics:view' },
  },
]

/**
 * Menu sections are flattened into siblings under the layout so every page sits at the same
 * RouterView depth; the layout's keep-alive would otherwise cache section shells, not pages.
 */
function flattenMenu(items: (RouteRecordRaw & MenuRoute)[]): RouteRecordRaw[] {
  return items.flatMap((item) => {
    if (!item.children) return [item]
    const { children, ...section } = item
    return [section as RouteRecordRaw, ...flattenMenu(children as (RouteRecordRaw & MenuRoute)[])]
  })
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/components/layout/AppLayout.vue'),
    children: [
      ...flattenMenu(menuRoutes),
      {
        path: '/knowledge/:kbId',
        name: 'knowledge-base',
        component: () => import('@/views/knowledge/KnowledgeBaseDetailView.vue'),
        props: true,
        meta: { title: '知识库详情', permission: 'kb:read', activeMenu: '/knowledge' },
      },
      {
        path: '/knowledge/:kbId/documents/:docId',
        name: 'knowledge-document',
        component: () => import('@/views/knowledge/DocumentDetailView.vue'),
        props: true,
        meta: { title: '文档详情', permission: 'kb:read', activeMenu: '/knowledge' },
      },
      {
        path: '/curation/gaps/:gapId',
        name: 'curation-gap',
        component: () => import('@/views/curation/GapWorkbenchView.vue'),
        props: true,
        meta: { title: '缺口处理', permission: 'gap:review', activeMenu: '/curation/gaps' },
      },
      {
        path: '/curation/kos/:koId',
        name: 'curation-ko',
        component: () => import('@/views/curation/KoEditorView.vue'),
        props: true,
        meta: {
          title: '知识条目编辑',
          permission: CURATION_PERMISSIONS,
          activeMenu: '/curation/kos',
        },
      },
      {
        path: '/admin/eval-datasets/:datasetId',
        name: 'admin-eval-dataset',
        component: () => import('@/views/admin/evaluation/EvalDatasetDetailView.vue'),
        props: true,
        meta: {
          title: '评测集详情',
          permission: 'admin:retrieval',
          activeMenu: '/admin/eval-datasets',
        },
      },
      {
        path: '/admin/eval-runs/compare',
        name: 'admin-eval-compare',
        component: () => import('@/views/admin/evaluation/EvalCompareView.vue'),
        meta: { title: '策略对比', permission: 'admin:retrieval', activeMenu: '/admin/eval-runs' },
      },
      {
        path: '/admin/eval-runs/:runId',
        name: 'admin-eval-run',
        component: () => import('@/views/admin/evaluation/EvalRunDetailView.vue'),
        props: true,
        meta: { title: '评测详情', permission: 'admin:retrieval', activeMenu: '/admin/eval-runs' },
      },
      {
        path: '/admin/open-api/:clientId',
        name: 'admin-open-api-client',
        component: () => import('@/views/admin/openApi/ApiClientDetailView.vue'),
        props: true,
        meta: { title: '接入应用详情', permission: 'admin:openapi', activeMenu: '/admin/open-api' },
      },
      {
        path: '/admin/directory/runs/:runId',
        name: 'admin-directory-run',
        component: () => import('@/views/admin/directory/SyncRunDetailView.vue'),
        props: true,
        meta: { title: '同步详情', permission: 'admin:directory', activeMenu: '/admin/directory' },
      },
      {
        path: '/notifications',
        name: 'notifications',
        component: () => import('@/views/NotificationsView.vue'),
        meta: { title: '消息通知' },
      },
      {
        path: '/guide',
        name: 'guide',
        component: () => import('@/views/guide/GuideView.vue'),
        meta: { title: '使用说明' },
      },
      {
        path: '/403',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { title: '无权访问' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]
