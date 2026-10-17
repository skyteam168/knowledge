import type { LocaleModule } from '../index'

export default {
  'zh-CN': {
    filters: {
      action: '动作',
      actionPlaceholder: '如 user.update',
      resourceType: '资源类型',
      resourceTypePlaceholder: '如 user / role',
      resourceId: '资源 ID',
      actorId: '操作人 ID',
      time: '时间',
      start: '开始',
      end: '结束',
      query: '查询',
    },
    empty: '暂无审计记录',
    detail: {
      request: '请求',
      field: '字段',
      before: '变更前',
      after: '变更后',
      noDiff: '无字段变更',
    },
    columns: {
      time: '时间',
      actor: '操作人',
      action: '动作',
      resource: '资源',
    },
    system: '系统',
  },
  en: {
    filters: {
      action: 'Action',
      actionPlaceholder: 'e.g. user.update',
      resourceType: 'Resource type',
      resourceTypePlaceholder: 'e.g. user / role',
      resourceId: 'Resource ID',
      actorId: 'Actor ID',
      time: 'Time',
      start: 'Start',
      end: 'End',
      query: 'Search',
    },
    empty: 'No audit logs',
    detail: {
      request: 'Request',
      field: 'Field',
      before: 'Before',
      after: 'After',
      noDiff: 'No field changes',
    },
    columns: {
      time: 'Time',
      actor: 'Actor',
      action: 'Action',
      resource: 'Resource',
    },
    system: 'System',
  },
} satisfies LocaleModule
