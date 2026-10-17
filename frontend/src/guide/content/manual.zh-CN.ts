import { ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { ManualFaq, ManualSection } from '../manual'

export const MANUAL_SECTIONS: ManualSection[] = [
  {
    id: 'start',
    title: '快速开始',
    icon: 'Promotion',
    summary: '三步上手：登录、提问、查看出处。',
    tourKey: 'layout',
    topics: [
      {
        title: '第一次使用',
        steps: [
          {
            title: '登录系统',
            detail:
              '使用企业账号密码登录，或在登录页选择「企业微信」「钉钉」扫码登录。登录后看到的菜单与内容由你的部门、用户组和角色决定。',
          },
          {
            title: '认识界面',
            detail:
              '左侧是功能菜单，顶部有全局搜索、帮助、主题切换、消息通知和个人菜单。点击「帮助 → 重新播放本页引导」可随时重看引导。',
          },
          {
            title: '问第一个问题',
            detail:
              '打开「AI 助手」，输入一个工作中的问题（例如「出差住宿报销标准是多少」），按 Enter 发送。',
            permission: 'chat:use',
          },
          {
            title: '核对出处',
            detail:
              '回答里的蓝色数字是引用来源，鼠标移上去预览原文片段，点击「查看原文」打开完整文档。请以原文为准。',
            permission: 'chat:use',
          },
        ],
      },
    ],
  },
  {
    id: 'assistant',
    title: 'AI 助手',
    icon: 'ChatDotRound',
    summary: '用日常语言提问，答案只来自你有权访问的资料，并逐句标注出处。',
    permission: 'chat:use',
    route: '/assistant',
    tourKey: 'assistant',
    topics: [
      {
        title: '提问',
        steps: [
          {
            title: '输入问题',
            detail:
              '在底部输入框描述问题，Enter 发送、Shift + Enter 换行。问题里带上对象、场景和时间（如「2026 年新员工试用期考核流程」）效果更好。',
          },
          {
            title: '追问',
            detail: '同一对话中可以继续追问，AI 会结合上文理解，例如「那外包人员呢？」。',
          },
          {
            title: '停止与重新生成',
            detail: '回答过程中可点击方形按钮停止；对最后一条回答不满意，可点击「重新生成」。',
          },
        ],
      },
      {
        title: '限定知识库',
        steps: [
          {
            title: '选择范围',
            detail:
              '默认在全部可访问的知识库中查找。点击输入框下方的「全部可访问的知识库」可勾选一个或多个知识库，只在这些范围内回答。',
          },
          {
            title: '清除范围',
            detail: '点击选择框右侧的清除图标即恢复为全部知识库。',
          },
        ],
      },
      {
        title: '查看引用与原文',
        steps: [
          {
            title: '预览片段',
            detail: '鼠标移到回答中的蓝色数字上，会弹出引用的原文片段。',
          },
          {
            title: '打开原文',
            detail:
              '点击弹窗中的「点击查看原文」，或回答下方「引用来源」中的卡片，右侧会打开原文并定位到引用位置。',
          },
          {
            title: '没有可靠依据时',
            detail:
              '若提示「未找到可靠依据」或「未能关联到可靠的引用来源」，说明知识库中缺少相关资料，请谨慎参考。',
          },
        ],
      },
      {
        title: '反馈与知识需求',
        steps: [
          {
            title: '评价回答',
            detail:
              '点击「有帮助」直接记录；点击「没帮助」可选择原因并补充说明，帮助我们持续改进。',
          },
          {
            title: '提交知识需求',
            detail:
              '找不到答案时点击「提交知识需求」，知识运营同事会补充资料，处理完成后你会在「消息通知」中收到提醒。',
          },
        ],
      },
      {
        title: '管理会话',
        steps: [
          {
            title: '新建对话',
            detail: '换话题时点击左上角「新建对话」，避免不同问题的上下文互相干扰。',
          },
          {
            title: '查找、重命名、删除',
            detail: '左侧列表按时间分组保存历史会话，可搜索；点击会话右侧「…」可重命名或删除。',
          },
        ],
      },
    ],
  },
  {
    id: 'knowledge',
    title: '知识库',
    icon: 'Collection',
    summary: '按知识库组织和管理文档，权限精确到部门、用户组和角色。',
    permission: 'kb:read',
    route: '/knowledge',
    tourKey: 'knowledge',
    topics: [
      {
        title: '浏览文档',
        steps: [
          {
            title: '找到知识库',
            detail: '在「知识库」页按名称或描述筛选，列表只显示你有权访问的知识库。',
          },
          {
            title: '查看文档',
            detail:
              '点击知识库进入详情，可按标题、状态筛选文档；点击文档标题查看内容、分块与历史版本。',
          },
        ],
      },
      {
        title: '新建知识库',
        permission: 'kb:create',
        steps: [
          {
            title: '创建',
            detail: '点击「新建知识库」，填写名称、描述，选择可见范围（组织内可读 / 仅授权成员）。',
          },
          {
            title: '授权',
            detail: '进入知识库后点击「权限设置」，按部门、用户组或角色授予查看、编辑或管理权限。',
          },
        ],
      },
      {
        title: '上传与维护文档',
        permission: 'doc:upload',
        steps: [
          {
            title: '上传',
            detail:
              '在知识库详情页点击「上传文档」，拖拽或选择文件（可多选）。支持 PDF、Word（.docx / .doc）、Excel、PPT（.pptx）、TXT、Markdown、HTML；内容相同的文件会自动去重。',
          },
          {
            title: '等待处理',
            detail:
              '上传后系统自动解析、切分并建立索引，「状态」列会显示进度；处理完成后文档即可被搜索和 AI 助手引用。',
          },
          {
            title: '处理失败',
            detail:
              '状态为失败时，鼠标移上去可查看原因（如文件加密、扫描件无文字），修正后重新上传即可。',
          },
          {
            title: '更新版本',
            detail: '同名文档再次上传会生成新版本，旧版本保留在文档详情的版本记录中。',
          },
        ],
      },
    ],
  },
  {
    id: 'search',
    title: '搜索',
    icon: 'Search',
    summary: '关键词与语义混合检索，快速定位原文。',
    permission: 'search:use',
    route: '/search',
    tourKey: 'search',
    topics: [
      {
        title: '基本搜索',
        steps: [
          {
            title: '输入内容',
            detail:
              '在顶部全局搜索框（Ctrl + K）或「搜索」页输入关键词、文档编号或一句完整的问题，按 Enter 搜索。',
          },
          {
            title: '查看结果',
            detail: '结果按相关度排序，高亮显示命中内容，点击标题打开文档详情。',
          },
        ],
      },
      {
        title: '筛选与高级语法',
        steps: [
          {
            title: '筛选',
            detail:
              '按知识库、文档类型、标签、入库时间筛选，修改后自动重新搜索；点击「清除筛选」恢复。',
          },
          {
            title: '行内语法',
            detail:
              '直接在搜索框写条件：kb:知识库名、tag:标签、type:pdf、date:2026-03、after:2026-01-01；用英文引号包住的内容按精确短语匹配。',
          },
        ],
      },
    ],
  },
  {
    id: 'curation',
    title: '知识运营',
    icon: 'Opportunity',
    summary: '把 AI 答不上来的问题变成新知识，并经过审核后发布。',
    permission: CURATION_PERMISSIONS,
    route: '/curation/gaps',
    topics: [
      {
        title: '处理知识缺口',
        permission: 'gap:review',
        steps: [
          {
            title: '查看缺口',
            detail:
              '「知识缺口」汇总了用户提交的知识需求和低质量回答，相似问题会自动聚类，可按频次或最近时间排序。',
          },
          {
            title: '处理',
            detail:
              '打开缺口进入工作台，可「AI 生成知识条目」「关联已有文档」「标记为重复」或「驳回」；缺口解决后提问人会收到通知。',
          },
        ],
      },
      {
        title: '编写知识条目',
        permission: 'ko:edit',
        steps: [
          {
            title: '新建或编辑',
            detail: '在「知识条目」中编写问答、流程等结构化知识，并关联原始文档作为依据。',
          },
          {
            title: '提交审核',
            detail:
              '编辑完成后点击「提交审核」，审核通过即发布并更新索引，之后可被搜索和 AI 助手引用。',
          },
        ],
      },
      {
        title: '审核发布',
        permission: 'review:approve',
        steps: [
          {
            title: '审核',
            detail:
              '在「发布审核」打开待审核的条目，留意冲突检测提示，选择「审核通过并发布」或「驳回」，可填写审核意见。',
          },
        ],
      },
    ],
  },
  {
    id: 'admin',
    title: '管理后台',
    icon: 'Setting',
    summary: '组织、权限、模型与检索等系统配置。',
    permission: ADMIN_PERMISSIONS,
    topics: [
      {
        title: '组织与账号',
        permission: ['admin:dept', 'admin:user', 'admin:directory'],
        steps: [
          {
            title: '组织同步',
            detail:
              '在「组织同步」接入企业微信、钉钉、泛微或 Excel 模板，先「预览」核对变更，再「应用」同步部门与人员；可设置定时同步。',
            permission: 'admin:directory',
          },
          {
            title: '部门与用户',
            detail:
              '「部门管理」「用户管理」可查看组织架构、调整人员部门与角色；来自同步源的字段为只读，需在源系统修改。',
            permission: ['admin:dept', 'admin:user'],
          },
        ],
      },
      {
        title: '权限',
        permission: ['admin:group', 'admin:role'],
        steps: [
          {
            title: '用户组',
            detail: '「用户组」用于跨部门的项目或虚拟团队，可在知识库权限中按组授权。',
            permission: 'admin:group',
          },
          {
            title: '角色权限',
            detail:
              '「角色权限」定义每个角色可使用的功能，可批量为用户分配角色；管理类权限不会被自动授予。',
            permission: 'admin:role',
          },
        ],
      },
      {
        title: '模型与检索',
        permission: ['admin:model', 'admin:index', 'admin:retrieval'],
        steps: [
          {
            title: '模型管理',
            detail:
              '在「模型管理」配置模型提供方、同步与检测模型，切换对话 / 备用对话模型后立即生效；向量与重排模型仅供查看和检测。',
            permission: 'admin:model',
          },
          {
            title: '索引同步',
            detail: '「索引同步」查看文档索引任务与失败重试，必要时从数据库全量重建检索索引。',
            permission: 'admin:index',
          },
          {
            title: '检索策略与评测',
            detail:
              '「检索策略」调整召回与重排参数，「评测集」「离线评测」用标准问题集对比不同策略的效果后再上线。',
            permission: 'admin:retrieval',
          },
        ],
      },
      {
        title: '审计与开放平台',
        permission: ['admin:audit', 'admin:openapi'],
        steps: [
          {
            title: '审计日志',
            detail:
              '所有写操作都会记录审计日志，可按动作、资源类型、资源 ID、操作人和时间查询，并查看变更前后对比。',
            permission: 'admin:audit',
          },
          {
            title: '开放平台',
            detail:
              '为外部系统或 Agent 创建接入应用与 API Key，限定可访问的知识库、调用频率和 IP。',
            permission: 'admin:openapi',
          },
        ],
      },
    ],
  },
  {
    id: 'analytics',
    title: '分析',
    icon: 'DataAnalysis',
    summary: '了解知识库的使用情况与问答质量。',
    permission: 'analytics:view',
    route: '/analytics',
    topics: [
      {
        title: '查看数据',
        steps: [
          {
            title: '使用概览',
            detail:
              '「使用量」查看提问数、日活与趋势，「质量」「性能」查看回答质量与各阶段耗时，可按日期与知识库筛选。',
          },
          {
            title: '热门问题与内容',
            detail:
              '「热门问题」列出被问得最多的问题及未答次数，「内容」页查看失败文档与引用情况，优先完善高频内容。',
          },
          {
            title: '模型用量',
            detail: '查看各功能、各用户的模型 token 消耗。',
            permission: 'analytics:usage',
          },
        ],
      },
    ],
  },
]

export const MANUAL_FAQ: ManualFaq[] = [
  {
    question: '为什么我搜不到某份文档？',
    answer:
      '可能原因：你没有该知识库或文档的访问权限；文档仍在处理中或处理失败。请联系知识库管理员确认。',
  },
  {
    question: 'AI 的回答可靠吗？',
    answer:
      'AI 只根据你有权访问的资料作答，并标注出处。涉及制度、金额、时间等关键信息时，请点击引用核对原文。',
    permission: 'chat:use',
  },
  {
    question: '我的提问会被别人看到吗？',
    answer:
      '会话列表仅本人可见，其他用户看不到。为保障质量，系统会记录问答日志，具备相应管理权限的人员可用于排查问题和统计分析。',
    permission: 'chat:use',
  },
  {
    question: '上传后多久可以搜到？',
    answer: '一般几十秒到几分钟，取决于文件大小和数量，可在知识库详情的「状态」列查看进度。',
    permission: 'doc:upload',
  },
  {
    question: '没有某个菜单或按钮怎么办？',
    answer: '菜单和按钮按你的角色权限显示，如需开通请联系系统管理员。',
  },
]
