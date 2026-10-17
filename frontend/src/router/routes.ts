import type { RouteRecordRaw } from 'vue-router'
import type { PermissionRequirement } from '@/utils/permission'

declare module 'vue-router' {
  interface RouteMeta {
    /** i18n key, e.g. `route.assistant`. */
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
    meta: { title: 'route.adminDepartments', icon: 'OfficeBuilding', permission: 'admin:dept' },
  },
  {
    path: '/admin/users',
    name: 'admin-users',
    component: () => import('@/views/admin/UsersView.vue'),
    meta: { title: 'route.adminUsers', icon: 'User', permission: 'admin:user' },
  },
  {
    path: '/admin/directory',
    name: 'admin-directory',
    component: () => import('@/views/admin/directory/DirectorySourcesView.vue'),
    meta: { title: 'route.adminDirectory', icon: 'Share', permission: 'admin:directory' },
  },
  {
    path: '/admin/groups',
    name: 'admin-groups',
    component: () => import('@/views/admin/GroupsView.vue'),
    meta: { title: 'route.adminGroups', icon: 'UserFilled', permission: 'admin:group' },
  },
  {
    path: '/admin/roles',
    name: 'admin-roles',
    component: () => import('@/views/admin/RolesView.vue'),
    meta: { title: 'route.adminRoles', icon: 'Lock', permission: 'admin:role' },
  },
  {
    path: '/admin/audit-logs',
    name: 'admin-audit-logs',
    component: () => import('@/views/admin/AuditLogsView.vue'),
    meta: { title: 'route.adminAuditLogs', icon: 'Document', permission: 'admin:audit' },
  },
  {
    path: '/admin/indexing',
    name: 'admin-indexing',
    component: () => import('@/views/admin/IndexingView.vue'),
    meta: { title: 'route.adminIndexing', icon: 'Refresh', permission: 'admin:index' },
  },
  {
    path: '/admin/models',
    name: 'admin-models',
    component: () => import('@/views/admin/models/ModelsView.vue'),
    meta: { title: 'route.adminModels', icon: 'Cpu', permission: 'admin:model' },
  },
  {
    path: '/admin/retrieval',
    name: 'admin-retrieval',
    component: () => import('@/views/admin/RetrievalView.vue'),
    meta: { title: 'route.adminRetrieval', icon: 'Operation', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/eval-datasets',
    name: 'admin-eval-datasets',
    component: () => import('@/views/admin/evaluation/EvalDatasetsView.vue'),
    meta: { title: 'route.adminEvalDatasets', icon: 'Files', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/eval-runs',
    name: 'admin-eval-runs',
    component: () => import('@/views/admin/evaluation/EvalRunsView.vue'),
    meta: { title: 'route.adminEvalRuns', icon: 'TrendCharts', permission: 'admin:retrieval' },
  },
  {
    path: '/admin/open-api',
    name: 'admin-open-api',
    component: () => import('@/views/admin/openApi/ApiClientsView.vue'),
    meta: { title: 'route.adminOpenApi', icon: 'Connection', permission: 'admin:openapi' },
  },
]

export const CURATION_PERMISSIONS = ['gap:review', 'ko:edit', 'review:approve'] as const

const curationChildren: (RouteRecordRaw & MenuRoute)[] = [
  {
    path: '/curation/gaps',
    name: 'curation-gaps',
    component: () => import('@/views/curation/GapBoardView.vue'),
    meta: { title: 'route.curationGaps', icon: 'Warning', permission: 'gap:review' },
  },
  {
    path: '/curation/kos',
    name: 'curation-kos',
    component: () => import('@/views/curation/KoListView.vue'),
    meta: { title: 'route.curationKos', icon: 'Notebook', permission: CURATION_PERMISSIONS },
  },
  {
    path: '/curation/reviews',
    name: 'curation-reviews',
    component: () => import('@/views/curation/ReviewTasksView.vue'),
    meta: { title: 'route.curationReviews', icon: 'Finished', permission: 'review:approve' },
  },
]

export const menuRoutes: (RouteRecordRaw & MenuRoute)[] = [
  {
    path: '/assistant',
    name: 'assistant',
    component: () => import('@/views/assistant/AssistantView.vue'),
    meta: { title: 'route.assistant', icon: 'ChatDotRound', permission: 'chat:use' },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/knowledge/KnowledgeView.vue'),
    meta: { title: 'route.knowledge', icon: 'Collection', permission: 'kb:read' },
  },
  {
    path: '/search',
    name: 'search',
    component: () => import('@/views/search/SearchView.vue'),
    meta: { title: 'route.search', icon: 'Search', permission: 'search:use' },
  },
  {
    path: '/curation',
    name: 'curation',
    component: () => import('@/views/curation/CurationView.vue'),
    meta: { title: 'route.curation', icon: 'Opportunity', permission: CURATION_PERMISSIONS },
    children: curationChildren,
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('@/views/admin/AdminView.vue'),
    meta: { title: 'route.admin', icon: 'Setting', permission: ADMIN_PERMISSIONS },
    children: adminChildren,
  },
  {
    path: '/analytics',
    name: 'analytics',
    component: () => import('@/views/analytics/AnalyticsView.vue'),
    meta: { title: 'route.analytics', icon: 'DataAnalysis', permission: 'analytics:view' },
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
        meta: { title: 'route.knowledgeBase', permission: 'kb:read', activeMenu: '/knowledge' },
      },
      {
        path: '/knowledge/:kbId/documents/:docId',
        name: 'knowledge-document',
        component: () => import('@/views/knowledge/DocumentDetailView.vue'),
        props: true,
        meta: { title: 'route.knowledgeDocument', permission: 'kb:read', activeMenu: '/knowledge' },
      },
      {
        path: '/curation/gaps/:gapId',
        name: 'curation-gap',
        component: () => import('@/views/curation/GapWorkbenchView.vue'),
        props: true,
        meta: {
          title: 'route.curationGap',
          permission: 'gap:review',
          activeMenu: '/curation/gaps',
        },
      },
      {
        path: '/curation/kos/:koId',
        name: 'curation-ko',
        component: () => import('@/views/curation/KoEditorView.vue'),
        props: true,
        meta: {
          title: 'route.curationKo',
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
          title: 'route.adminEvalDataset',
          permission: 'admin:retrieval',
          activeMenu: '/admin/eval-datasets',
        },
      },
      {
        path: '/admin/eval-runs/compare',
        name: 'admin-eval-compare',
        component: () => import('@/views/admin/evaluation/EvalCompareView.vue'),
        meta: {
          title: 'route.adminEvalCompare',
          permission: 'admin:retrieval',
          activeMenu: '/admin/eval-runs',
        },
      },
      {
        path: '/admin/eval-runs/:runId',
        name: 'admin-eval-run',
        component: () => import('@/views/admin/evaluation/EvalRunDetailView.vue'),
        props: true,
        meta: {
          title: 'route.adminEvalRun',
          permission: 'admin:retrieval',
          activeMenu: '/admin/eval-runs',
        },
      },
      {
        path: '/admin/open-api/:clientId',
        name: 'admin-open-api-client',
        component: () => import('@/views/admin/openApi/ApiClientDetailView.vue'),
        props: true,
        meta: {
          title: 'route.adminOpenApiClient',
          permission: 'admin:openapi',
          activeMenu: '/admin/open-api',
        },
      },
      {
        path: '/admin/directory/runs/:runId',
        name: 'admin-directory-run',
        component: () => import('@/views/admin/directory/SyncRunDetailView.vue'),
        props: true,
        meta: {
          title: 'route.adminDirectoryRun',
          permission: 'admin:directory',
          activeMenu: '/admin/directory',
        },
      },
      {
        path: '/notifications',
        name: 'notifications',
        component: () => import('@/views/NotificationsView.vue'),
        meta: { title: 'route.notifications' },
      },
      {
        path: '/guide',
        name: 'guide',
        component: () => import('@/views/guide/GuideView.vue'),
        meta: { title: 'route.guide' },
      },
      {
        path: '/403',
        name: 'forbidden',
        component: () => import('@/views/ForbiddenView.vue'),
        meta: { title: 'route.forbidden' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]
