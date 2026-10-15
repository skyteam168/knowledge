import type { PermissionRequirement } from '@/utils/permission'
import { CURATION_PERMISSIONS, ADMIN_PERMISSIONS } from '@/router/routes'

export type TourPlacement = 'top' | 'bottom' | 'left' | 'right' | 'bottom-start' | 'right-start'

export interface TourStepDef {
  /** `data-guide` value of the highlighted element; omit for a centered card. */
  target?: string
  title: string
  description: string
  placement?: TourPlacement
  permission?: PermissionRequirement
}

export interface TourDef {
  key: string
  /** Bump to show the tour again to everyone after a significant UI change. */
  version: number
  title: string
  /** Route name whose first visit plays the tour; the layout tour has none. */
  routeName?: string
  permission?: PermissionRequirement
  steps: TourStepDef[]
}

export interface ResolvedStep {
  target?: string
  title: string
  description: string
  placement?: TourPlacement
}

export const LAYOUT_TOUR = 'layout'

export const TOURS: TourDef[] = [
  {
    key: LAYOUT_TOUR,
    version: 1,
    title: '系统导览',
    steps: [
      {
        title: '欢迎使用企业知识库',
        description:
          '这里汇聚了公司的制度、流程与经验文档。接下来用 1 分钟带你认识主要功能，随时可以点右上角关闭，之后也能在「帮助」里重新观看。',
      },
      {
        target: 'menu-assistant',
        title: 'AI 助手',
        description: '用日常语言提问，AI 会基于你有权访问的知识库作答，并逐句标注引用来源。',
        placement: 'right',
        permission: 'chat:use',
      },
      {
        target: 'menu-knowledge',
        title: '知识库',
        description: '按知识库浏览文档，查看文档详情与原文；有权限的同事可以新建知识库、上传文档。',
        placement: 'right',
        permission: 'kb:read',
      },
      {
        target: 'menu-search',
        title: '搜索',
        description: '关键词 + 语义混合检索，支持按知识库、文档类型、标签和入库时间筛选。',
        placement: 'right',
        permission: 'search:use',
      },
      {
        target: 'menu-curation',
        title: '知识运营',
        description: '处理 AI 答不上来的知识缺口，维护知识条目，并审核发布。',
        placement: 'right',
        permission: CURATION_PERMISSIONS,
      },
      {
        target: 'menu-admin',
        title: '管理',
        description: '部门与用户、组织同步、角色权限、模型、索引与检索策略等后台配置。',
        placement: 'right',
        permission: ADMIN_PERMISSIONS,
      },
      {
        target: 'menu-analytics',
        title: '分析',
        description: '查看问答量、热门问题、文档引用与模型用量等运营数据。',
        placement: 'right',
        permission: 'analytics:view',
      },
      {
        target: 'global-search',
        title: '全局搜索',
        description: '在任何页面输入关键词回车即可搜索，快捷键 Ctrl + K 直接聚焦。',
        placement: 'bottom',
        permission: 'search:use',
      },
      {
        target: 'notifications',
        title: '消息通知',
        description: '知识需求的处理结果、审核任务、文档到期提醒都会在这里通知你。',
        placement: 'bottom',
      },
      {
        target: 'theme',
        title: '主题',
        description: '在浅色、深色和跟随系统之间切换。',
        placement: 'bottom',
      },
      {
        target: 'help',
        title: '帮助',
        description: '随时打开「使用说明」查看每个功能的操作步骤，或重新播放当前页面的引导。',
        placement: 'bottom-start',
      },
    ],
  },
  {
    key: 'assistant',
    version: 1,
    title: 'AI 助手引导',
    routeName: 'assistant',
    permission: 'chat:use',
    steps: [
      {
        target: 'assistant-composer',
        title: '输入问题',
        description:
          '像问同事一样描述你的问题，按 Enter 发送，Shift + Enter 换行。问题越具体，答案越准确。',
        placement: 'top',
      },
      {
        target: 'assistant-scope',
        title: '限定知识库（可选）',
        description: '默认在你能访问的全部知识库中查找；只想查某几个知识库时在这里勾选。',
        placement: 'top',
      },
      {
        title: '查看引用与原文',
        description:
          '回答中的蓝色数字是引用来源：鼠标移上去可预览原文片段，点击「查看原文」或回答下方的来源卡片可打开完整原文。',
      },
      {
        title: '反馈与知识需求',
        description:
          '在回答下方点「有帮助 / 没帮助」反馈质量；如果知识库里没有答案，点「提交知识需求」，知识运营同事会补充资料并通知你。',
      },
      {
        target: 'assistant-new',
        title: '新建对话',
        description: '换一个话题时新建对话，避免上下文互相干扰。',
        placement: 'right',
      },
      {
        target: 'assistant-history',
        title: '历史会话',
        description: '之前的对话按时间保存在这里，可搜索、重命名或删除。',
        placement: 'right',
      },
    ],
  },
  {
    key: 'knowledge',
    version: 1,
    title: '知识库引导',
    routeName: 'knowledge',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-search',
        title: '查找知识库',
        description: '按名称或描述筛选你有权访问的知识库。',
        placement: 'bottom',
      },
      {
        target: 'kb-create',
        title: '新建知识库',
        description: '为部门或项目建立独立的知识库，并设置可见范围与成员权限。',
        placement: 'bottom',
        permission: 'kb:create',
      },
      {
        target: 'kb-table',
        title: '进入知识库',
        description: '点击任意一行进入知识库，查看其中的文档、上传新文档或调整权限。',
        placement: 'top',
      },
    ],
  },
  {
    key: 'kb-detail',
    version: 1,
    title: '知识库详情引导',
    routeName: 'knowledge-base',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-upload',
        title: '上传文档',
        description:
          '支持 PDF、Word、Excel、PPT、Markdown 等格式。上传后系统会自动解析、切分并建立索引，完成后即可被搜索和 AI 助手引用。',
        placement: 'bottom',
      },
      {
        target: 'kb-acl',
        title: '权限设置',
        description: '按部门、用户组或角色授权，决定谁可以查看或编辑这个知识库。',
        placement: 'bottom',
      },
      {
        target: 'kb-docs',
        title: '文档列表',
        description:
          '「状态」列显示文档处理进度：处理中的文档暂时搜不到，失败的文档可查看原因后重新上传。点击标题查看文档详情与版本。',
        placement: 'top',
      },
    ],
  },
  {
    key: 'search',
    version: 1,
    title: '搜索引导',
    routeName: 'search',
    permission: 'search:use',
    steps: [
      {
        target: 'search-input',
        title: '输入关键词或问题',
        description:
          '可以输入关键词、文档编号，也可以直接输入一个问题，系统会同时做关键词和语义匹配。',
        placement: 'bottom',
      },
      {
        target: 'search-filters',
        title: '筛选结果',
        description: '按知识库、文档类型、标签或入库时间缩小范围，修改后自动重新搜索。',
        placement: 'bottom',
      },
      {
        target: 'search-syntax',
        title: '高级语法',
        description:
          '也可以直接在搜索框里写筛选条件，例如 kb:人事制度 type:pdf，引号内为精确短语。',
        placement: 'bottom',
      },
    ],
  },
]

export function findTour(key: string): TourDef | undefined {
  return TOURS.find((t) => t.key === key)
}

export function tourForRoute(routeName: unknown): TourDef | undefined {
  return typeof routeName === 'string' ? TOURS.find((t) => t.routeName === routeName) : undefined
}

export function guideSelector(target: string): string {
  return `[data-guide="${target}"]`
}

/** Steps the user is allowed to see whose target is currently on the page. */
export function resolveSteps(
  tour: TourDef,
  can: (required: PermissionRequirement | undefined) => boolean,
  exists: (target: string) => boolean = (t) => document.querySelector(guideSelector(t)) !== null,
): ResolvedStep[] {
  return tour.steps
    .filter((s) => can(s.permission) && (!s.target || exists(s.target)))
    .map(({ target, title, description, placement }) => ({ target, title, description, placement }))
}
