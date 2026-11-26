import { ADMIN_AGENT_PERMISSIONS, ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { ManualFaq, ManualSection } from '../manual'

/** Platform-engineering menus (sidebar subgroup under Admin). */
const PLATFORM_PERMISSIONS = [
  'admin:index',
  'admin:model',
  'admin:retrieval',
  'admin:openapi',
] as const

export const MANUAL_SECTIONS: ManualSection[] = [
  {
    id: 'start',
    title: '快速开始',
    icon: 'Promotion',
    summary: '登录、认识界面，并按角色找到自己该用的功能。',
    tourKey: 'layout',
    topics: [
      {
        title: '第一次使用',
        steps: [
          {
            title: '登录系统',
            detail:
              '打开系统地址后进入登录页。使用企业账号密码登录，或点击「企业微信」「钉钉」扫码。登录成功后进入首页；若提示无权访问，说明账号尚未分配角色，请联系管理员。',
          },
          {
            title: '认识界面',
            detail:
              '左侧是功能菜单（只显示你有权限的项）；顶部有全局搜索（Ctrl/Cmd+K）、系统就绪状态、帮助、主题、语言、消息铃铛和个人菜单；中间是工作区，上方标签栏可切换已打开的页面。',
          },
          {
            title: '帮助与引导',
            detail:
              '顶部「帮助 → 使用说明」打开本手册（按你的权限过滤章节）。「重新播放本页引导」只重播当前页；「重新开始全部引导」从布局导览重新开始。遇到不会操作的页面，先看引导再查本手册对应章节。',
          },
        ],
      },
      {
        title: '按角色怎么用',
        steps: [
          {
            title: '普通员工（查资料、提问）',
            detail:
              '日常路径：①「知识库问答专家」提问并核对引用；②「搜索」或顶栏搜索找原文；③「知识库」浏览有权文档；④「我的收藏」回看常用资料。上传、权限、运营菜单通常看不到。',
          },
          {
            title: '知识运营（补知识、审核）',
            detail:
              '日常路径：①「知识缺口」处理答不上来的问题；②「知识条目」编写标准问答、相似问法与条目关系并提交；③「发布审核」通过后进入索引。可先读本手册「概念层」弄清术语/图谱分工。也可在知识库上传或在线编辑文档。',
            permission: CURATION_PERMISSIONS,
          },
          {
            title: '管理员 / 平台工程',
            detail:
              '组织侧：部门、用户、组织同步、用户组、角色、审计（「管理」）。概念侧：术语表、结构化数据、Ontology Studio、跨系统身份、规则与动作（「企业本体管理」）。平台侧（管理 → 平台工程）：索引、模型、检索策略、评测、开放平台。也可用「AI 管理助手」。备份/告警/病毒扫描见运维文档。',
            permission: ADMIN_PERMISSIONS,
          },
        ],
      },
      {
        title: '三步上手提问',
        permission: 'chat:use',
        steps: [
          {
            title: '打开问答',
            detail: '左侧点「知识库问答专家」。',
          },
          {
            title: '输入问题',
            detail:
              '在底部输入框写清对象、场景与时间（例如「2026 年新员工试用期考核流程」），按 Enter 发送（Shift+Enter 换行）。',
          },
          {
            title: '核对出处',
            detail:
              '回答中的蓝色数字是引用。鼠标悬停预览片段，点「查看原文」打开文档。制度、金额、日期等关键信息必须以原文为准。',
          },
        ],
      },
    ],
  },
  {
    id: 'assistant',
    title: '知识库问答专家',
    icon: 'ChatDotRound',
    summary: '用日常语言提问；答案只来自你有权访问的资料，并标注出处。',
    permission: 'chat:use',
    route: '/assistant',
    tourKey: 'assistant',
    topics: [
      {
        title: '提问与追问',
        steps: [
          {
            title: '输入并发送',
            detail:
              '底部输入框描述问题后 Enter 发送。过程中可点方形停止按钮中止；对最后一条回答不满意可点「重新生成」。',
          },
          {
            title: '追问',
            detail:
              '同一对话内可继续追问（如「那外包人员呢？」），系统会结合上文理解。换话题请「新建对话」，避免上下文串题。',
          },
          {
            title: '回答中的表格与图',
            detail:
              '答案可能含表格（可切柱图）、流程图、代码高亮或资料附图。受控文档相关内容前端可能禁止复制，只能在页面内阅读。',
          },
        ],
      },
      {
        title: '限定知识库',
        steps: [
          {
            title: '选择范围',
            detail:
              '默认在全部可访问知识库中查找。点输入框下方「全部可访问的知识库」，勾选一个或多个库，只在这些范围内回答。',
          },
          {
            title: '清除范围',
            detail: '点选择框右侧清除图标，恢复为全部可访问知识库。',
          },
        ],
      },
      {
        title: '查看引用与原文',
        steps: [
          {
            title: '预览片段',
            detail: '鼠标移到回答中的蓝色数字上，弹出引用的原文片段。',
          },
          {
            title: '打开原文',
            detail:
              '点弹窗「点击查看原文」，或下方「引用来源」卡片，右侧打开原文并尽量定位到引用位置。页图可按需加载预览。',
          },
          {
            title: '没有可靠依据时',
            detail:
              '若提示「未找到可靠依据」或未能关联引用，说明库中缺少可用资料，请勿当制度依据；可点「提交知识需求」交给运营补充。',
          },
        ],
      },
      {
        title: '相关概念（概念层）',
        steps: [
          {
            title: '看什么',
            detail:
              '回答结束后，若资料命中企业术语或关联知识，答案下方会出现可折叠的「相关概念」。每项可含：规范名、类型、别名、设备/外部编号、关联知识条目标题。用于对照「你们口头怎么叫」和「系统标准叫什么」。',
          },
          {
            title: '怎么用',
            detail:
              '展开核对别名与编号是否就是你问的对象；关联知识可提示还有哪些标准问答相关。区域只读，普通员工不能从这里改术语。若概念不对或缺漏，把问题通过「提交知识需求」或差评交给运营，由管理员在「术语表 / 结构化数据 / 知识条目」中补齐。',
          },
        ],
      },
      {
        title: '反馈与知识需求',
        steps: [
          {
            title: '评价回答',
            detail: '点「有帮助」直接记录；点「没帮助」可选题因并补充说明，用于改进质量。',
          },
          {
            title: '提交知识需求',
            detail:
              '找不到答案时点「提交知识需求」。运营处理后你会在顶部铃铛「消息通知」收到提醒。',
          },
        ],
      },
      {
        title: '管理会话',
        steps: [
          {
            title: '新建对话',
            detail: '左上角「新建对话」开启空白会话。',
          },
          {
            title: '查找、重命名、删除',
            detail:
              '左侧列表按时间分组；可用搜索框过滤。点会话右侧「…」可重命名或删除。会话列表仅本人可见。',
          },
        ],
      },
    ],
  },
  {
    id: 'knowledge',
    title: '知识库',
    icon: 'Collection',
    summary: '按库管理文档：上传、在线编辑、权限、版本与批量处理。',
    permission: 'kb:read',
    route: '/knowledge',
    tourKey: 'knowledge',
    topics: [
      {
        title: '浏览文档',
        steps: [
          {
            title: '找到知识库',
            detail:
              '打开「知识库」，按名称或描述筛选。列表只显示你有权访问的库；点库名进入详情。',
          },
          {
            title: '查看文档',
            detail:
              '详情页可按标题、状态、标签筛选；点文档标题打开详情，可看正文、分块、版本历史与评论。',
          },
        ],
      },
      {
        title: '新建知识库',
        permission: 'kb:create',
        steps: [
          {
            title: '创建',
            detail:
              '点「新建知识库」，填写名称与描述，选择可见范围：「组织内可读」或「仅授权成员」。',
          },
          {
            title: '受控库模板（可选）',
            detail:
              '若提供「受控库」模板，勾选后默认开启水印、禁复制、下载需编辑权、仅授权成员可见，适合制度/敏感资料。',
          },
          {
            title: '授权',
            detail:
              '进入库后点「权限设置」，按部门（含下级）、用户组、角色或用户授予查看 / 编辑 / 管理。保存后立即生效。',
          },
        ],
      },
      {
        title: '权限与拒绝名单',
        permission: 'kb:create',
        steps: [
          {
            title: '允许授权',
            detail:
              '在权限设置中添加主体并选择级别。组织可见库中，仍可用更细粒度 ACL 控制文档。',
          },
          {
            title: '拒绝名单（DENY）',
            detail:
              '若启用「拒绝」效果：对某用户/部门设拒绝后，即使组织可见或其它允许规则存在，该主体也看不到（deny-wins）。知识库「管理」权限者仍可进库修复 ACL。改完权限后检索缓存会失效，问答也会按最新权限过滤。',
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
              '在库详情点「上传文档」，拖拽或选择文件（可多选）。支持 PDF、Word（.docx/.doc）、Excel、PPT（.pptx）、TXT、Markdown、HTML 等；内容相同会按校验去重。',
          },
          {
            title: '等待处理',
            detail:
              '上传后自动解析、切分、建索引。「状态」列显示进度（解析中 / 索引中 / 就绪 / 失败）。就绪后即可搜索与问答引用。一般几十秒到数分钟。',
          },
          {
            title: '处理失败',
            detail:
              '状态为失败时，悬停查看原因（加密、扫描件无字、格式不支持等）。修正后重新上传，或对单篇点「重新处理」。',
          },
          {
            title: '更新版本',
            detail: '同名再上传会生成新版本；旧版本保留在文档详情的版本记录中，可查看对比。',
          },
        ],
      },
      {
        title: '在线编辑与协作',
        permission: 'doc:upload',
        steps: [
          {
            title: '新建在线文档',
            detail:
              '在库详情选「新建文档」（或等价入口），进入 Markdown 编辑器，写好后保存。保存成功后同样进入解析与索引流程。',
          },
          {
            title: '编辑已有文档',
            detail: '在有编辑权的文档详情点「编辑」，修改后保存为新版本。',
          },
          {
            title: '负责人、复核与评论',
            detail:
              '可为文档指定负责人与定期复核；详情页可发表评论。到期复核会通过通知等方式提醒相关人员（以系统配置为准）。',
          },
          {
            title: '收藏',
            detail: '在文档详情点收藏星标，之后在「我的收藏」中快速打开。',
          },
        ],
      },
      {
        title: '批量重新处理与缺页图',
        permission: 'doc:upload',
        steps: [
          {
            title: '批量重新处理',
            detail:
              '在库详情勾选多篇文档，点「重新处理」（或批量操作），用于解析失败重试或规则变更后重跑。处理中的文档请勿重复猛点。',
          },
          {
            title: '缺页图筛选',
            detail:
              '若列表提供「缺页图」筛选：可找出应有页/幻灯片附图但缺失或出错的文档，便于补跑页图相关处理。',
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
              '在顶部全局搜索框（Ctrl/Cmd+K）或「搜索」页输入关键词、文档编号或一句完整问题，Enter 搜索。只会返回你有权看的内容。',
          },
          {
            title: '查看结果',
            detail: '结果按相关度排序并高亮命中；点标题打开文档详情。无结果时换词、放宽筛选或确认是否有权限。',
          },
        ],
      },
      {
        title: '筛选与高级语法',
        steps: [
          {
            title: '筛选',
            detail:
              '按知识库、文档类型、标签、入库时间筛选，修改后自动重搜；「清除筛选」恢复默认。',
          },
          {
            title: '行内语法',
            detail:
              '在搜索框直接写：kb:知识库名、tag:标签、type:pdf、date:2026-03、after:2026-01-01；英文引号包裹表示精确短语。',
          },
        ],
      },
    ],
  },
  {
    id: 'favorites',
    title: '我的收藏',
    icon: 'Star',
    summary: '收藏文档与知识条目，并查看最近浏览。',
    permission: 'kb:read',
    route: '/favorites',
    topics: [
      {
        title: '使用收藏与最近',
        steps: [
          {
            title: '打开页面',
            detail: '左侧点「我的收藏」。上方有「收藏」「最近浏览」两个标签。',
          },
          {
            title: '打开条目',
            detail: '点列表中的标题跳转到对应文档或知识条目详情。',
          },
          {
            title: '取消收藏',
            detail: '在收藏列表或文档/条目详情再次点星标即可取消；最近浏览由系统自动记录，无需手动添加。',
          },
        ],
      },
    ],
  },
  {
    id: 'notifications',
    title: '消息通知',
    icon: 'Bell',
    summary: '接收知识需求处理结果等站内提醒。',
    route: '/notifications',
    topics: [
      {
        title: '查看通知',
        steps: [
          {
            title: '入口',
            detail:
              '点顶部铃铛图标，或个人菜单中的「消息通知」。角标数字表示未读条数。',
          },
          {
            title: '阅读与已读',
            detail:
              '在列表中点开通知查看详情；系统会标记已读。常见类型包括：你提交的知识需求已被处理、复核提醒等。',
          },
          {
            title: '没有消息',
            detail: '列表为空表示暂无通知。提交知识需求后请稍候，运营处理完成后才会推送。',
          },
        ],
      },
    ],
  },
  {
    id: 'concepts',
    title: '概念层（术语 · 实体 · 图谱 · 本体）',
    icon: 'Connection',
    summary:
      '弄清「规范叫什么、彼此什么关系、和设备编号如何对齐」，提升搜索与问答命中；不提供 SPARQL / 图数据库。',
    permission: [
      'chat:use',
      'gap:review',
      'ko:edit',
      'review:approve',
      'admin:retrieval',
    ],
    topics: [
      {
        title: '用来干什么',
        steps: [
          {
            title: '要解决的问题',
            detail:
              '同一事物常有多种叫法（简称、代号、口语），文档里又夹着设备编号、工单号。概念层把「标准名 + 别名 + 类型」和「知识条目之间的关系」「外部编号映射」管起来，让检索能扩词、问答能挂上相关概念，并在命中知识条目后沿关系多跳找关联答案。',
          },
          {
            title: '三块积木怎么分工',
            detail:
              '①术语表 = 实体词典（规范名、类型、别名）；②知识条目（KO）及条目关系 = 可审核的标准知识与「图谱」边；③结构化数据 = ERP/MES 等编号在本库的镜像，并映射到术语或 KO。文档仍是正文来源；概念层负责对齐说法与关联，不替代上传文档。',
          },
          {
            title: '员工侧能看到什么',
            detail:
              '问答结束后的「相关概念」折叠区（规范名、别名、设备/编号、关联知识）。站内搜索不单独展示概念卡，但会受益于别名扩展；命中的知识条目会带「知识条目」标签。维护入口在管理端与知识运营，不在员工菜单。',
            permission: 'chat:use',
          },
        ],
      },
      {
        title: '名词对照',
        steps: [
          {
            title: '实体 / 术语',
            detail:
              '「实体」在本系统里主要指术语表中的一条：有规范名、业务类型（设备、工序、缺陷、制度、IT 术语等）、别名列表、启用状态。入库切块还会尽量打上相关 entity_ids，便于问答扩展同文档相关段落。',
          },
          {
            title: '图谱（KO 关系）',
            detail:
              '这里的「图谱」不是 Neo4j，而是知识条目之间的关系边（相关、属于、依赖、导致、缓解、适用于等）。检索开启图召回时，命中 KO 后会沿关系多跳取邻居再融合。运营在 KO 编辑器里维护关系；术语表「关系预览」可看术语周围 1 跳的术语 / 结构化 / KO。',
          },
          {
            title: '本体（OWL）',
            detail:
              '本体是「允许有哪些类、哪些关系」的说明书（TBox），仓库文件 ontology/enterprise.ttl，可用 Protégé 打开。真正业务实例（ABox）仍在 PostgreSQL，由术语表、KO、结构化页面维护。网页「本体说明」只读摘要；不能在网页里改 OWL，也不提供 SPARQL。改类型枚举需研发同步代码与 TTL。',
            permission: 'admin:retrieval',
          },
        ],
      },
      {
        title: '推荐维护顺序',
        permission: ['admin:retrieval', 'ko:edit', 'gap:review'],
        steps: [
          {
            title: '先词典，再知识，再挂接',
            detail:
              '①在「术语表」建规范名与别名并「同步同义词」；②用文档或「知识条目」沉淀标准问答，并填写条目关系；③在「结构化数据」把外部编号映射到术语/KO。最后用真实问题在问答里看「相关概念」是否对得上。',
          },
        ],
      },
    ],
  },
  {
    id: 'curation',
    title: '知识运营',
    icon: 'Opportunity',
    summary: '知识缺口 → 知识条目 → 发布审核；把答不上来的问题变成可检索知识。',
    permission: CURATION_PERMISSIONS,
    route: '/curation/gaps',
    topics: [
      {
        title: '知识缺口是什么',
        permission: 'gap:review',
        steps: [
          {
            title: '目的',
            detail:
              '自动汇聚「没依据 / 依据不足 / 用户点没帮助 / 用户提交知识需求」等问题，聚类后交给运营补文档或写知识条目，避免同类问题反复答不上来。',
          },
          {
            title: '员工如何产生缺口',
            detail:
              '在「知识库问答专家」：点「没帮助」并选题因；或在无可靠依据时点「提交知识需求」。员工看不到后台缺口列表，处理完成后会收到消息通知。',
          },
        ],
      },
      {
        title: '缺口看板',
        permission: 'gap:review',
        steps: [
          {
            title: '打开与读统计',
            detail:
              '左侧「知识运营 → 知识缺口」。顶部卡片显示待处理、处理中、未解决聚类等；可点来源类型卡片筛选（无依据、依据不足、差评、用户求助）。',
          },
          {
            title: '筛列表',
            detail:
              '在「缺口列表」页签按状态、来源、知识库、关键词筛选；排序选「频次」优先处理高频，或「最近」处理新问题；可勾「只看我负责的」→ 查询。',
          },
          {
            title: '聚类',
            detail:
              '点「立即聚类」让后台把相似问题归并。「相似问题聚类」页签可看代表问、问题数与来源分布；点行可回到列表并带上该聚类过滤。',
          },
          {
            title: '进入工作台',
            detail: '点某一行进入缺口工作台，再做分派与结案动作。',
          },
        ],
      },
      {
        title: '缺口工作台',
        permission: 'gap:review',
        steps: [
          {
            title: '读清上下文',
            detail:
              '主区查看改写后问题与原问、出现次数、召回分数、会话摘录；需要排障时可展开问答 Trace（逐步 JSON）。',
          },
          {
            title: '分派',
            detail:
              '右侧填写负责人、归属知识库、优先级、处理时限 →「保存」，或「分配给我」。方便团队认领高频缺口。',
          },
          {
            title: '生成知识条目草稿',
            detail:
              '若你有编辑知识条目权限：选知识库、KO 类型、可选参考文档与备注 →「生成知识条目草稿」。成功后跳转 KO 编辑器（AI 失败时可能降级为空白草稿，需人工撰写）。',
            permission: 'ko:edit',
          },
          {
            title: '其它结案动作',
            detail:
              '「关联已有文档」：说明资料已存在（记处理说明，不自动关单逻辑以页面为准）。「标为重复」：选同类缺口。「驳回」：不采纳该需求。已结案可「重新打开」。处理结果会通知原提问人（适用场景）。',
          },
        ],
      },
      {
        title: '知识条目（KO）是什么',
        permission: ['ko:edit', 'gap:review', 'review:approve'],
        steps: [
          {
            title: '目的',
            detail:
              '把「标准问题 + 相似问法 + 结构化答案 + 文档依据」做成可审核、可检索的条目。已发布 KO 单独进索引，检索时可加权，并可作为图召回的节点；比散落在长文档里的表述更适合当标准答案。',
          },
          {
            title: '类型怎么选',
            detail:
              '界面常见类型：FAQ / 问答 / 知识卡片 / 制度摘要 / 设备 / 工艺流程 / 缺陷 / 制度策略 / IT 术语等。按内容业务属性选择，便于筛选与本体软约束提示（关系类型配对警告默认不硬拦）。',
          },
        ],
      },
      {
        title: '编写知识条目',
        permission: 'ko:edit',
        steps: [
          {
            title: '新建入口',
            detail:
              '「知识运营 → 知识条目」→「新建知识条目」（选库与类型、填标准问题）。或「从文档生成 FAQ」选文档与条数批量出草稿。也可从缺口工作台生成。',
          },
          {
            title: '填写正文',
            detail:
              '编辑：标题、类型、标准问题、相似问法（多行）、答案（支持 Markdown 预览）。相似问法写全口语变体，有利于问答改写命中。',
          },
          {
            title: '引用来源',
            detail:
              '用文档选取器关联作为依据的原文，并可跳转核对。发布前应保证答案每句关键信息能在依据中找到。',
          },
          {
            title: '条目关系（图谱边）',
            detail:
              '在「条目关系」中填写对端知识条目 ID，并选关系类型：相关 / 属于 / 依赖 / 导致 / 缓解 / 适用于。这是多跳图召回的边；填错 ID 会导致扩召回跑偏，保存前用冲突检测与预览核对。当前需粘贴 UUID（无搜索选择器时）。',
          },
          {
            title: '负责人与时效',
            detail: '可设生效起止与负责人；侧栏可用「AI 草稿」生成后「采纳」，再人工改准。',
          },
          {
            title: '保存与提交审核',
            detail:
              '「保存」留在草稿 → 可选「冲突检测」→「提交审核」并填备注。提交人可在待审状态「撤回」。',
          },
        ],
      },
      {
        title: '审核发布与下线',
        permission: 'review:approve',
        steps: [
          {
            title: '待审队列',
            detail:
              '「知识运营 → 发布审核」按待审 / 已通过 / 已驳回等切换；点行进入 KO 编辑器审阅。',
          },
          {
            title: '通过或驳回',
            detail:
              '核对标准问、答案、依据与关系；有冲突警告时会二次确认。选通过并发布，或驳回并写意见。通过后出现线上版本号，索引更新后搜索带「知识条目」标签，问答可引用。',
          },
          {
            title: '下线',
            detail: '已发布条目可「下线」并填写原因，停止作为正式可引用知识（以页面状态为准）。',
          },
        ],
      },
    ],
  },
  {
    id: 'admin',
    title: '管理后台',
    icon: 'Setting',
    summary: '组织、账号、权限、审计、术语、结构化数据与 Ontology Studio。',
    permission: ADMIN_PERMISSIONS,
    topics: [
      {
        title: '组织同步',
        permission: 'admin:directory',
        steps: [
          {
            title: '配置同步源',
            detail:
              '打开「组织同步」，新建或编辑来源（企业微信 / 钉钉 / 泛微 / Excel 等），按表单填写密钥与映射字段，保存。',
          },
          {
            title: '预览再应用',
            detail:
              '先点「预览」查看将新增/变更/停用的部门与人员；核对无误后再「应用」。切勿跳过预览直接应用到生产。',
          },
          {
            title: '定时与历史',
            detail:
              '可设置同步间隔。在运行历史中点开某次同步查看明细；失败时按错误信息修配置后重试。',
          },
        ],
      },
      {
        title: '部门与用户',
        permission: ['admin:dept', 'admin:user'],
        steps: [
          {
            title: '部门管理',
            detail:
              '「部门管理」维护部门树：新建、改名、移动。同步源托管的字段多为只读，应在源系统修改后再同步。',
            permission: 'admin:dept',
          },
          {
            title: '用户管理',
            detail:
              '「用户管理」查看账号、调整部门归属、分配角色与用户组；可开通/停用与密码登录（以页面能力为准）。同步用户的主数据以源系统为准。',
            permission: 'admin:user',
          },
        ],
      },
      {
        title: '用户组与角色',
        permission: ['admin:group', 'admin:role'],
        steps: [
          {
            title: '用户组',
            detail:
              '「用户组」建跨部门项目组或虚拟团队，添加成员后，可在知识库权限里按组授权。',
            permission: 'admin:group',
          },
          {
            title: '角色权限',
            detail:
              '「角色权限」勾选功能权限（如 chat:use、kb:create、admin:*）。批量为用户分配角色。管理类权限不会被默默自动授予；改完后用户重新登录或刷新后菜单更新。',
            permission: 'admin:role',
          },
        ],
      },
      {
        title: '审计日志',
        permission: 'admin:audit',
        steps: [
          {
            title: '查询',
            detail:
              '打开「审计日志」，按动作、资源类型、资源 ID、操作人、时间筛选。点开条目可看变更前后对比，用于追责与排障。',
          },
        ],
      },
      {
        title: '术语表（实体词典）',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '目的',
            detail:
              '维护「规范名 + 类型 + 别名」。问答改写与站内搜索会按别名扩展检索词（例如规范名「访问控制列表」、别名「ACL」）。启用术语还可同步到 OpenSearch 同义词，加强关键词一路命中。',
          },
          {
            title: '打开与筛选',
            detail:
              '「企业本体管理 → 术语表」。按规范名关键词、类型（设备 / 工序·流程 / 缺陷 / 制度条款 / IT 术语 / 其他）、状态（启用/停用）筛选后搜索。',
          },
          {
            title: '新建术语',
            detail:
              '点「新建术语」：填规范名、类型、状态、说明；创建时可批量填别名（逗号或换行）→ 保存。规范名应唯一、口语别名尽量写全。',
          },
          {
            title: '维护别名',
            detail:
              '在表格「别名」列输入后点「添加」；点标签 × 删除。编辑弹窗一般改规范名/类型/说明/状态，别名以表格维护为准。',
          },
          {
            title: '同步同义词',
            detail:
              '改完启用术语后点顶部「同步同义词」，写入 OpenSearch 并热加载。停用术语不参与同步。不同步则索引侧同义词仍是旧的。',
          },
          {
            title: '关系预览与本体说明',
            detail:
              '行操作「关系预览」打开力导向图：蓝=术语、绿=结构化镜像、黄=知识条目（约 1 跳），用于核对挂接。「本体说明」只读查看 OWL 合约摘要（类与关系定义在仓库 TTL，实例在本库）。',
          },
        ],
      },
      {
        title: '结构化数据（编号镜像）',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '目的',
            detail:
              '把 ERP/MES/QMS 等对象（设备、工单、备件或通用业务域记录）镜像到本库，并把 external_id 映射到术语或知识条目。问答「相关概念」里的设备/编号、编号解析接口都依赖这里。同步只更新镜像表，不会自动创建术语或 KO。',
          },
          {
            title: '域与数据源',
            detail:
              '打开「企业本体管理 → 结构化数据」。左侧选业务域：设备域通常有设备/工单/备件页签；其它域为通用记录表。顶栏「新建数据源」可选连接器：MySQL、PostgreSQL、SQL Server、MongoDB、CSV、REST，或无连接器（手工）。密码请填环境变量名（如 MES_MYSQL_PASSWORD），勿写入库。',
          },
          {
            title: '手工录入与搜索',
            detail:
              '选数据源、关键词搜索列表。非设备域可用「新建记录」填写外部编号、对象类型、标题等。点某一行打开下方映射区。',
          },
          {
            title: '映射到术语 / KO',
            detail:
              '在映射区输入术语 ID 或知识条目 ID →「添加映射」。映射正确后，问答相关概念才能带出别名、编号与关联知识。当前多为粘贴 UUID，请先从术语表/KO 列表复制 ID。',
          },
          {
            title: '同步数据源',
            detail:
              '筛选中选中带连接器的数据源 →「同步数据源」拉取到本地镜像；也可在 meta 配置 sync_interval_minutes 由调度周期同步。参数说明见 docs/ops/structured-connectors.md。',
          },
          {
            title: '编号解析（联调）',
            detail:
              '页底「编号解析」：填 object_type、external_id 等 →「解析」，查看 JSON 是否解析到术语/KO。用于验收映射，不是员工功能。',
          },
        ],
      },
      {
        title: 'Ontology Studio（组织语义）',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '目的',
            detail:
              '把 MES/业务库的表或集合映射为「业务实体 + 属性」草稿，审核后发布；Agent / 开放平台只读已发布版本。打开「企业本体管理 → Ontology Studio」。',
          },
          {
            title: '连接数据库导入 Schema',
            detail:
              '点「连接数据库」：选引擎 MySQL / PostgreSQL / SQL Server / MongoDB → 手动填写主机端口库名（及 Schema/认证库）或复用已有结构化数据源 →「读取表列表」勾选表/集合 → 读结构预览 →「导入到草稿」。MongoDB 无固定表结构，字段由样本文档推断。密码优先用环境变量（MES_*_PASSWORD）。',
          },
          {
            title: '建议、批准与发布',
            detail:
              '草稿中可「生成建议」改中文显示名/类型，再「批准」或「批准全部草稿」；至少批准一个实体后「发布」。发布后该组织生效语义模型切换，Agent 只见本版本。若需恢复历史版，在左侧选中已归档/非生效已发布版本，点「回滚为此版本」。',
          },
          {
            title: '语义证据与计算口径',
            detail:
              '选中实体后可在「语义证据」挂 KO/文档/chunk ID 与备注；发布后 Agent 经 describe_ontology 只读摘要（无越权正文）。属性可填安全计算口径（如 a+b），get_object 可返回派生值。',
          },
        ],
      },
      {
        title: '跨系统身份',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Canonical 与 Identifier',
            detail:
              '打开「企业本体管理 → 跨系统身份」：创建 Canonical、挂各系统 Identifier、在「冲突」页签查看多系统 ID 指向不同实体的情况。冲突不可静默覆盖。',
          },
        ],
      },
      {
        title: '规则与动作',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '维护规则与 ActionType',
            detail:
              '打开「企业本体管理 → 规则与动作」：按优先级配置 ontology 规则（allow/deny/require_confirm）与动作类型（风险、系统、输入 schema）。禁用动作后 Open/MCP list_actions 不可见。',
          },
        ],
      },
    ],
  },
  {
    id: 'admin-agent',
    title: 'AI 管理助手',
    icon: 'MagicStick',
    summary: '用自然语言发起受控的管理任务：理解 → 澄清 → 计划 → 审批 → 执行。',
    permission: ADMIN_AGENT_PERMISSIONS,
    route: '/admin/agent',
    topics: [
      {
        title: '发起任务',
        steps: [
          {
            title: '打开助手',
            detail: '「管理 → AI 管理助手」。可用页面上的示例问题 chips 快速填入。',
          },
          {
            title: '描述意图',
            detail:
              '用一句话说清要做什么（如「给张三开通密码登录」「把李四加到某某用户组」）。系统只理解意图与槽位，不会让模型自行决定写操作步骤。',
          },
          {
            title: '澄清必填信息',
            detail:
              '若缺人名、组名等必填项，助手会提问或给出候选列表，请补全后再继续。你没有权限的任务会在此被拦住。',
          },
        ],
      },
      {
        title: '审批与执行',
        steps: [
          {
            title: '查看计划',
            detail:
              '澄清通过后展示固定顺序的步骤预览（解析名称、校验、候选歧义）。请逐条确认对象是否正确。',
          },
          {
            title: '风险确认与审批',
            detail:
              '高风险操作需勾选知晓风险；审批窗口约 30 分钟、单次有效、仅发起人可批。超时需重新发起。',
          },
          {
            title: '执行与报告',
            detail:
              '批准后系统按步骤执行，任一步失败则整体回滚，并给出报告。过程事件可在历史中回放。临时密码等敏感信息会脱敏展示。',
          },
          {
            title: '助手不会做的事',
            detail:
              '不会删除部门/角色/用户、不会改模型或检索策略配置、不会签发 API Key 等高风险动作；这些请在对应管理页人工操作。',
          },
        ],
      },
    ],
  },
  {
    id: 'platform',
    title: '平台工程',
    icon: 'Cpu',
    summary: '索引、模型、检索策略、评测与开放平台（管理侧栏「平台工程」分组）。',
    permission: PLATFORM_PERMISSIONS,
    topics: [
      {
        title: '索引同步',
        permission: 'admin:index',
        steps: [
          {
            title: '查看任务',
            detail:
              '打开「索引同步」，查看文档入索引队列、失败与重试。积压变多时先查 worker / outbox 是否健康。',
          },
          {
            title: '失败重试与重建',
            detail:
              '对失败任务按页面提示重试。必要时执行从数据库全量重建检索索引（耗时长，选低峰期）。重建期间以页面状态为准，勿重复提交。',
          },
        ],
      },
      {
        title: '模型管理',
        permission: 'admin:model',
        steps: [
          {
            title: '查看与检测',
            detail:
              '「模型管理」列出对话、向量、重排等端点。可做健康检测，确认连通与延迟。',
          },
          {
            title: '切换对话模型',
            detail:
              '切换主对话 / 备用对话模型后一般立即生效。向量与重排模型多供查看与检测；更换 embedding 维数需按运维文档做迁移，勿只改名称。',
          },
        ],
      },
      {
        title: '检索策略',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '调整参数',
            detail:
              '「检索策略」配置召回、融合、重排等参数。改前记下当前值，改后用评测对比再全量上线。',
          },
          {
            title: '追踪样例',
            detail: '可用页面提供的追踪/样例能力观察某次检索的召回与分数，辅助排障。',
          },
        ],
      },
      {
        title: '评测集与离线评测',
        permission: 'admin:retrieval',
        steps: [
          {
            title: '维护评测集',
            detail:
              '「评测集」新建或导入标准问题；进入详情编辑每道题的期望文档/答案要点。',
          },
          {
            title: '跑评测',
            detail:
              '「离线评测」选择评测集与策略配置，创建运行。完成后打开详情看通过率与失败题。',
          },
          {
            title: '策略对比',
            detail:
              '在评测任务列表勾选 2～4 个已完成任务，进入对比页查看指标差异，再决定是否采用新策略。',
          },
        ],
      },
      {
        title: '开放平台',
        permission: 'admin:openapi',
        steps: [
          {
            title: '创建接入应用',
            detail:
              '「开放平台」点新建，填写名称，绑定可扮演的部门/用户组/角色，并勾选授权知识库。应用只能访问这些库的交集内容，无超管旁路。',
          },
          {
            title: '签发 API Key',
            detail:
              '进入应用详情创建 Key，复制后妥善保存（通常只显示一次）。可配置每分钟限流与 IP 白名单。',
          },
          {
            title: '联调与日志',
            detail:
              '详情内「接入指南」查看 REST / MCP 用法；用检索预览验证权限范围；在调用日志排查 401/403/429。轮换泄露的 Key 并禁用旧 Key。',
          },
        ],
      },
    ],
  },
  {
    id: 'analytics',
    title: '分析',
    icon: 'DataAnalysis',
    summary: '用数据决定先补哪些知识、系统是否健康。',
    permission: 'analytics:view',
    route: '/analytics',
    topics: [
      {
        title: '查看数据',
        steps: [
          {
            title: '使用量',
            detail:
              '查看提问数、日活与趋势；按日期、知识库筛选，了解谁在用、用在哪。',
          },
          {
            title: '质量与性能',
            detail:
              '「质量」看满意度、拒答与未命中；「性能」看首字与各阶段耗时。质量变差时优先查知识缺口与高频未答问题。',
          },
          {
            title: '热门问题与内容',
            detail:
              '「热门问题」列出高频提问与未答次数；「内容」看失败文档与引用情况。优先为高频未答补文档或 KO。',
          },
          {
            title: '模型用量',
            detail: '按功能与用户查看 token 消耗，用于成本与额度规划。',
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
      '常见原因：①没有该库或文档的访问权限（含被拒绝名单命中）；②文档仍在解析/索引中；③处理失败。请在知识库详情看状态，或联系库管理员确认权限。',
  },
  {
    question: 'AI 的回答可靠吗？',
    answer:
      '系统只根据你有权访问的资料作答并标注出处；证据不足会拒答或提示不确定。涉及制度、金额、时间等，请点击引用核对原文后再执行。',
    permission: 'chat:use',
  },
  {
    question: '我的提问会被别人看到吗？',
    answer:
      '会话列表仅本人可见。为保障质量，系统会记录问答日志；具备相应管理权限的人员可用于排障与统计，不会出现在其他同事的会话列表里。',
    permission: 'chat:use',
  },
  {
    question: '上传后多久可以搜到？',
    answer:
      '一般几十秒到几分钟，取决于文件大小与队列。在知识库详情「状态」列查看；长时间停在解析/索引可让管理员查「索引同步」。',
    permission: 'doc:upload',
  },
  {
    question: '没有某个菜单或按钮怎么办？',
    answer:
      '菜单和按钮按角色功能权限显示；文档级操作还受知识库/文档 ACL 约束。如需开通，请联系管理员在「角色权限」中分配，或请库管理员给你授权。',
  },
  {
    question: '刚收回某人的权限，为什么还能问到？',
    answer:
      '权限变更后检索缓存会失效，问答在生成过程中也会复核。若仍异常，确认是否给了其它组/部门的间接授权，或是否知识库「管理」权限豁免了文档拒绝规则。',
    permission: ADMIN_PERMISSIONS,
  },
  {
    question: '索引一直积压或大量失败怎么办？',
    answer:
      '打开「索引同步」查看失败原因；确认 worker、outbox-dispatcher、OpenSearch/Qdrant 健康。可对单文档「重新处理」或批量重试；全量重建仅在确认需要时于低峰执行。',
    permission: 'admin:index',
  },
  {
    question: '开放平台调用返回 401 / 403 / 429？',
    answer:
      '401：Key 错误或已禁用；403：IP 不在白名单或无权访问该库；429：触发限流。在应用详情核对 Key、授权库、IP 与限流配置，并查看调用日志。',
    permission: 'admin:openapi',
  },
  {
    question: '组织同步预览显示大量停用，可以应用吗？',
    answer:
      '先核对源系统是否误配过滤条件。系统对停用比例有安全阈值，异常偏高时应修正源数据后再同步，避免误停大量账号。',
    permission: 'admin:directory',
  },
  {
    question: '问答里的「相关概念」从哪来？不对怎么办？',
    answer:
      '来自术语命中、结构化编号映射与关联知识条目。若缺漏或张冠李戴：在术语表补别名并同步同义词；在结构化数据把正确 external_id 映射到术语/KO；在知识条目补关系或发布缺失的标准问答。',
    permission: 'chat:use',
  },
  {
    question: '知识条目写了关系，搜索有变化吗？',
    answer:
      '已发布 KO 本身会进索引并可加权。条目关系在检索策略开启图召回时，作为第三路多跳邻居参与融合；未发布或已下线的条目不参与。可在离线评测 / graph-gate 验证多跳收益。',
    permission: ['ko:edit', 'admin:retrieval'],
  },
  {
    question: '本体（OWL）要在网页里改吗？',
    answer:
      '不用。网页「本体说明」只读。类与关系合约在 ontology/enterprise.ttl；实例在术语表、KO、结构化页维护。改枚举需研发改代码并校验 TTL，本系统不上 SPARQL。',
    permission: 'admin:retrieval',
  },
]
