import { ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { ManualFaq, ManualSection } from '../manual'

export const MANUAL_SECTIONS: ManualSection[] = [
  {
    id: 'start',
    title: 'Quick start',
    icon: 'Promotion',
    summary: 'Get going in three steps: sign in, ask a question, check the sources.',
    tourKey: 'layout',
    topics: [
      {
        title: 'Your first visit',
        steps: [
          {
            title: 'Sign in',
            detail:
              'Sign in with your company account and password, or choose WeCom or DingTalk on the sign-in page and scan the QR code. The menus and content you see depend on your department, user groups and roles.',
          },
          {
            title: 'Get to know the layout',
            detail:
              'The menu is on the left. The header holds global search, Help, the theme switcher, Notifications and your account menu. Choose "Help → Replay tour for this page" at any time to watch the tour again.',
          },
          {
            title: 'Ask your first question',
            detail:
              'Open "AI Assistant", type a question from your daily work (for example, "What is the hotel allowance for business trips?") and press Enter to send it.',
            permission: 'chat:use',
          },
          {
            title: 'Check the sources',
            detail:
              'The blue numbers in an answer are citations. Hover over one to preview the source passage, or click "View source" to open the full document. The source document always takes precedence.',
            permission: 'chat:use',
          },
        ],
      },
    ],
  },
  {
    id: 'assistant',
    title: 'AI Assistant',
    icon: 'ChatDotRound',
    summary:
      'Ask in everyday language. Answers come only from content you have access to, with a citation for every statement.',
    permission: 'chat:use',
    route: '/assistant',
    tourKey: 'assistant',
    topics: [
      {
        title: 'Asking questions',
        steps: [
          {
            title: 'Type your question',
            detail:
              'Describe your question in the box at the bottom. Press Enter to send and Shift + Enter for a new line. Mentioning who, what situation and when (such as "the 2026 probation review process for new hires") gives better results.',
          },
          {
            title: 'Follow-up questions',
            detail:
              'Keep asking in the same conversation and the AI will take the earlier messages into account, for example "What about contractors?".',
          },
          {
            title: 'Stop and regenerate',
            detail:
              'Click the square button to stop an answer while it is being written. Not happy with the latest answer? Click "Regenerate".',
          },
        ],
      },
      {
        title: 'Limiting the knowledge bases',
        steps: [
          {
            title: 'Choose a scope',
            detail:
              'By default the assistant searches every knowledge base you can access. Click "All accessible knowledge bases" below the input box to pick one or more knowledge bases and answer from those only.',
          },
          {
            title: 'Clear the scope',
            detail:
              'Click the clear icon on the right of the selector to go back to all knowledge bases.',
          },
        ],
      },
      {
        title: 'Citations and source documents',
        steps: [
          {
            title: 'Preview a passage',
            detail:
              'Hover over a blue number in the answer to see the cited passage from the source document.',
          },
          {
            title: 'Open the source',
            detail:
              'Click "View source" in the popup, or a card under "Sources" below the answer. The document opens on the right, scrolled to the cited passage.',
          },
          {
            title: 'When there is no reliable source',
            detail:
              'If you see "No reliable source found" or "Could not link the answer to a reliable citation", the knowledge bases lack material on the topic. Treat the answer with caution.',
          },
        ],
      },
      {
        title: 'Feedback and knowledge requests',
        steps: [
          {
            title: 'Rate the answer',
            detail:
              'Click "Helpful" to record it right away. Click "Not helpful" to choose a reason and add details, so we can keep improving.',
          },
          {
            title: 'Request missing knowledge',
            detail:
              'Can\'t find the answer? Click "Request knowledge". The knowledge ops team will add the material, and you\'ll get a message in "Notifications" when it\'s done.',
          },
        ],
      },
      {
        title: 'Managing conversations',
        steps: [
          {
            title: 'Start a new conversation',
            detail:
              'When you change topics, click "New conversation" in the top left so earlier context doesn\'t mix with your new question.',
          },
          {
            title: 'Find, rename or delete',
            detail:
              'Past conversations are listed on the left, grouped by date, and can be searched. Click "…" next to a conversation to rename or delete it.',
          },
        ],
      },
    ],
  },
  {
    id: 'knowledge',
    title: 'Knowledge Bases',
    icon: 'Collection',
    summary:
      'Organize and manage documents in knowledge bases, with permissions down to departments, user groups and roles.',
    permission: 'kb:read',
    route: '/knowledge',
    tourKey: 'knowledge',
    topics: [
      {
        title: 'Browsing documents',
        steps: [
          {
            title: 'Find a knowledge base',
            detail:
              'On the "Knowledge Bases" page, filter by name or description. The list only shows knowledge bases you have access to.',
          },
          {
            title: 'View documents',
            detail:
              'Click a knowledge base to open it and filter its documents by title or status. Click a document title to see its content, chunks and version history.',
          },
        ],
      },
      {
        title: 'Creating a knowledge base',
        permission: 'kb:create',
        steps: [
          {
            title: 'Create',
            detail:
              'Click "New knowledge base", enter a name and description, and choose who can see it (readable across the organization, or authorized members only).',
          },
          {
            title: 'Grant access',
            detail:
              'Inside the knowledge base, click "Permissions" to grant Read, Edit or Manage permission to departments, user groups or roles.',
          },
        ],
      },
      {
        title: 'Uploading and maintaining documents',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Upload',
            detail:
              'On the knowledge base page, click "Upload documents" and drag in or select files (several at once is fine). PDF, Word (.docx / .doc), Excel, PowerPoint (.pptx), TXT, Markdown and HTML are supported; identical files are de-duplicated automatically.',
          },
          {
            title: 'Wait for processing',
            detail:
              'After upload, documents are parsed, split into chunks and indexed automatically, with progress shown in the "Status" column. Once processing finishes, the document can be found in search and cited by the AI Assistant.',
          },
          {
            title: 'If processing fails',
            detail:
              'When the status shows a failure, hover over it to see why (for example, the file is encrypted or is a scan with no text). Fix the file and upload it again.',
          },
          {
            title: 'Update a version',
            detail:
              'Uploading a document with the same name creates a new version. Earlier versions are kept in the version history on the document page.',
          },
        ],
      },
    ],
  },
  {
    id: 'search',
    title: 'Search',
    icon: 'Search',
    summary: 'Hybrid keyword and semantic retrieval to find the source text fast.',
    permission: 'search:use',
    route: '/search',
    tourKey: 'search',
    topics: [
      {
        title: 'Basic search',
        steps: [
          {
            title: 'Enter your query',
            detail:
              'In the global search box in the header (Ctrl + K) or on the "Search" page, type keywords, a document number or a full question, then press Enter.',
          },
          {
            title: 'Review the results',
            detail:
              'Results are sorted by relevance with matching text highlighted. Click a title to open the document.',
          },
        ],
      },
      {
        title: 'Filters and advanced syntax',
        steps: [
          {
            title: 'Filter',
            detail:
              'Filter by knowledge base, document type, tag or date added; the search reruns automatically when you change a filter. Click "Clear filters" to reset.',
          },
          {
            title: 'Inline syntax',
            detail:
              'Write conditions straight into the search box: kb:<knowledge base name>, tag:<tag>, type:pdf, date:2026-03, after:2026-01-01. Text wrapped in straight double quotes is matched as an exact phrase.',
          },
        ],
      },
    ],
  },
  {
    id: 'curation',
    title: 'Knowledge Ops',
    icon: 'Opportunity',
    summary:
      "Turn questions the AI couldn't answer into new knowledge, and publish it after review.",
    permission: CURATION_PERMISSIONS,
    route: '/curation/gaps',
    topics: [
      {
        title: 'Handling knowledge gaps',
        permission: 'gap:review',
        steps: [
          {
            title: 'Review the gaps',
            detail:
              '"Knowledge Gaps" collects knowledge requests from users and low-quality answers. Similar questions are clustered automatically, and you can sort by frequency or most recent.',
          },
          {
            title: 'Resolve',
            detail:
              'Open a gap to go to its workbench, where you can "Generate knowledge object with AI", "Link existing documents", "Mark as duplicate" or "Reject". Whoever asked is notified once the gap is resolved.',
          },
        ],
      },
      {
        title: 'Writing knowledge objects',
        permission: 'ko:edit',
        steps: [
          {
            title: 'Create or edit',
            detail:
              'In "Knowledge Objects", write structured knowledge such as Q&As and procedures, and link the original documents as supporting evidence.',
          },
          {
            title: 'Submit for review',
            detail:
              'When you\'re done, click "Submit for review". Once approved, the knowledge object is published and indexed, and can then be found in search and cited by the AI Assistant.',
          },
        ],
      },
      {
        title: 'Publish review',
        permission: 'review:approve',
        steps: [
          {
            title: 'Review',
            detail:
              'In "Publish Reviews", open a pending knowledge object, check any conflict warnings, then choose "Approve and publish" or "Reject". You can add review comments.',
          },
        ],
      },
    ],
  },
  {
    id: 'admin',
    title: 'Admin',
    icon: 'Setting',
    summary: 'System settings for the organization, permissions, models and retrieval.',
    permission: ADMIN_PERMISSIONS,
    topics: [
      {
        title: 'Organization and accounts',
        permission: ['admin:dept', 'admin:user', 'admin:directory'],
        steps: [
          {
            title: 'Directory sync',
            detail:
              'In "Directory Sync", connect WeCom, DingTalk, Weaver or an Excel template. "Preview" the changes first, then "Apply" them to sync departments and people. Scheduled syncs can also be set up.',
            permission: 'admin:directory',
          },
          {
            title: 'Departments and users',
            detail:
              '"Departments" and "Users" show the org chart and let you change people\'s departments and roles. Fields that come from a sync source are read-only and must be changed in the source system.',
            permission: ['admin:dept', 'admin:user'],
          },
        ],
      },
      {
        title: 'Permissions',
        permission: ['admin:group', 'admin:role'],
        steps: [
          {
            title: 'User groups',
            detail:
              '"User Groups" are for cross-department projects or virtual teams, and can be granted access in knowledge base permissions.',
            permission: 'admin:group',
          },
          {
            title: 'Roles and permissions',
            detail:
              '"Roles & Permissions" defines which features each role can use, and lets you assign roles to users in bulk. Admin permissions are never granted automatically.',
            permission: 'admin:role',
          },
        ],
      },
      {
        title: 'Models and retrieval',
        permission: ['admin:model', 'admin:index', 'admin:retrieval'],
        steps: [
          {
            title: 'Models',
            detail:
              'In "Models", configure model providers and sync and test models. Switching the chat or fallback chat model takes effect immediately; embedding and rerank models can only be viewed and tested.',
            permission: 'admin:model',
          },
          {
            title: 'Index sync',
            detail:
              '"Index Sync" shows document indexing jobs and lets you retry failures. When needed, rebuild the full retrieval index from the database.',
            permission: 'admin:index',
          },
          {
            title: 'Retrieval strategy and evaluation',
            detail:
              '"Retrieval Strategy" tunes recall and rerank parameters. Use "Eval Datasets" and "Offline Evaluation" to compare strategies on a standard question set before rolling one out.',
            permission: 'admin:retrieval',
          },
        ],
      },
      {
        title: 'Audit and open platform',
        permission: ['admin:audit', 'admin:openapi'],
        steps: [
          {
            title: 'Audit logs',
            detail:
              'Every write operation is recorded in the audit logs. Search by action, resource type, resource ID, operator and time, and compare values before and after each change.',
            permission: 'admin:audit',
          },
          {
            title: 'Open platform',
            detail:
              'Create API clients and API keys for external systems or agents, and limit which knowledge bases they can access, how often they can call and from which IPs.',
            permission: 'admin:openapi',
          },
        ],
      },
    ],
  },
  {
    id: 'analytics',
    title: 'Analytics',
    icon: 'DataAnalysis',
    summary: 'See how the knowledge bases are used and how good the answers are.',
    permission: 'analytics:view',
    route: '/analytics',
    topics: [
      {
        title: 'Viewing the data',
        steps: [
          {
            title: 'Usage overview',
            detail:
              '"Usage" shows question counts, daily active users and trends. "Quality" and "Performance" show answer quality and the time spent in each stage. Filter by date and knowledge base.',
          },
          {
            title: 'Top questions and content',
            detail:
              '"Top questions" lists the most-asked questions and how often they went unanswered. The "Content" page shows failed documents and citation stats, so you can improve high-demand content first.',
          },
          {
            title: 'Model usage',
            detail: 'See model token consumption by feature and by user.',
            permission: 'analytics:usage',
          },
        ],
      },
    ],
  },
]

export const MANUAL_FAQ: ManualFaq[] = [
  {
    question: "Why can't I find a document in search?",
    answer:
      "You may not have access to its knowledge base or to the document itself, or the document may still be processing or have failed to process. Check with the knowledge base's administrator.",
  },
  {
    question: 'Can I trust the AI answers?',
    answer:
      'The AI answers only from content you have access to and cites its sources. For key details such as policies, amounts and dates, click the citations and check the source documents.',
    permission: 'chat:use',
  },
  {
    question: 'Can other people see my questions?',
    answer:
      'Your conversation list is visible only to you. To maintain quality, the system keeps Q&A logs, which staff with the relevant admin permissions may use for troubleshooting and analytics.',
    permission: 'chat:use',
  },
  {
    question: 'How soon can I find a document after uploading it?',
    answer:
      'Usually anywhere from under a minute to a few minutes, depending on file size and count. Check progress in the "Status" column on the knowledge base page.',
    permission: 'doc:upload',
  },
  {
    question: "What if I don't see a menu or button?",
    answer:
      'Menus and buttons are shown according to your role permissions. Contact your system administrator to request access.',
  },
]
