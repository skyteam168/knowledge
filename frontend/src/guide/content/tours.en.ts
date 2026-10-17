import { ADMIN_PERMISSIONS, CURATION_PERMISSIONS } from '@/router/routes'
import type { TourDef } from '../tours'

export const TOURS: TourDef[] = [
  {
    key: 'layout',
    version: 1,
    title: 'System tour',
    steps: [
      {
        title: 'Welcome to the Enterprise Knowledge Base',
        description:
          'This is where the company\'s policies, processes and know-how live. In the next minute we\'ll show you the main features. You can close the tour at any time from the top right, and replay it later from "Help".',
      },
      {
        target: 'menu-assistant',
        title: 'AI Assistant',
        description:
          'Ask in everyday language. The AI answers from the knowledge bases you can access and cites a source for every statement.',
        placement: 'right',
        permission: 'chat:use',
      },
      {
        target: 'menu-knowledge',
        title: 'Knowledge Bases',
        description:
          'Browse documents by knowledge base and open their details and source files. Colleagues with permission can create knowledge bases and upload documents.',
        placement: 'right',
        permission: 'kb:read',
      },
      {
        target: 'menu-search',
        title: 'Search',
        description:
          'Hybrid keyword and semantic retrieval, with filters for knowledge base, document type, tag and date added.',
        placement: 'right',
        permission: 'search:use',
      },
      {
        target: 'menu-curation',
        title: 'Knowledge Ops',
        description:
          "Work on knowledge gaps the AI couldn't answer, maintain knowledge objects, and review them for publishing.",
        placement: 'right',
        permission: CURATION_PERMISSIONS,
      },
      {
        target: 'menu-admin',
        title: 'Admin',
        description:
          'Back-office settings: departments and users, directory sync, roles and permissions, models, indexing and retrieval strategy.',
        placement: 'right',
        permission: ADMIN_PERMISSIONS,
      },
      {
        target: 'menu-analytics',
        title: 'Analytics',
        description:
          'Operational data such as question volume, top questions, document citations and model usage.',
        placement: 'right',
        permission: 'analytics:view',
      },
      {
        target: 'global-search',
        title: 'Global search',
        description:
          'Type keywords and press Enter on any page to search. Press Ctrl + K to jump straight to the box.',
        placement: 'bottom',
        permission: 'search:use',
      },
      {
        target: 'notifications',
        title: 'Notifications',
        description:
          'Updates on your knowledge requests, review tasks and document expiry reminders show up here.',
        placement: 'bottom',
      },
      {
        target: 'theme',
        title: 'Theme',
        description: 'Switch between light, dark and your system setting.',
        placement: 'bottom',
      },
      {
        target: 'help',
        title: 'Help',
        description:
          'Open the "User guide" for step-by-step instructions on every feature, or replay the tour for the current page.',
        placement: 'bottom-start',
      },
    ],
  },
  {
    key: 'assistant',
    version: 1,
    title: 'AI Assistant tour',
    routeName: 'assistant',
    permission: 'chat:use',
    steps: [
      {
        target: 'assistant-composer',
        title: 'Type your question',
        description:
          'Describe your question as you would to a colleague. Press Enter to send and Shift + Enter for a new line. The more specific the question, the more accurate the answer.',
        placement: 'top',
      },
      {
        target: 'assistant-scope',
        title: 'Limit the knowledge bases (optional)',
        description:
          'By default the assistant searches every knowledge base you can access. Tick specific knowledge bases here to search only those.',
        placement: 'top',
      },
      {
        title: 'Citations and source documents',
        description:
          'The blue numbers in an answer are citations. Hover over one to preview the source passage, or click "View source" or a source card below the answer to open the full document.',
      },
      {
        title: 'Feedback and knowledge requests',
        description:
          'Click "Helpful / Not helpful" below an answer to rate it. If the knowledge bases don\'t have the answer, click "Request knowledge" and the knowledge ops team will add the material and let you know.',
      },
      {
        target: 'assistant-new',
        title: 'New conversation',
        description:
          "Start a new conversation when you change topics, so earlier context doesn't get mixed in.",
        placement: 'right',
      },
      {
        target: 'assistant-history',
        title: 'Conversation history',
        description:
          'Your past conversations are saved here by date. You can search, rename or delete them.',
        placement: 'right',
      },
    ],
  },
  {
    key: 'knowledge',
    version: 1,
    title: 'Knowledge Bases tour',
    routeName: 'knowledge',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-search',
        title: 'Find a knowledge base',
        description: 'Filter the knowledge bases you can access by name or description.',
        placement: 'bottom',
      },
      {
        target: 'kb-create',
        title: 'New knowledge base',
        description:
          'Set up a dedicated knowledge base for a department or project, and choose its visibility and member permissions.',
        placement: 'bottom',
        permission: 'kb:create',
      },
      {
        target: 'kb-table',
        title: 'Open a knowledge base',
        description:
          'Click any row to open the knowledge base, where you can view its documents, upload new ones or adjust permissions.',
        placement: 'top',
      },
    ],
  },
  {
    key: 'kb-detail',
    version: 1,
    title: 'Knowledge base tour',
    routeName: 'knowledge-base',
    permission: 'kb:read',
    steps: [
      {
        target: 'kb-upload',
        title: 'Upload documents',
        description:
          'PDF, Word, Excel, PowerPoint, Markdown and more are supported. Uploaded files are parsed, split into chunks and indexed automatically, after which they can be found in search and cited by the AI Assistant.',
        placement: 'bottom',
      },
      {
        target: 'kb-acl',
        title: 'Permissions',
        description:
          'Grant access to departments, user groups or roles to decide who can view or edit this knowledge base.',
        placement: 'bottom',
      },
      {
        target: 'kb-docs',
        title: 'Document list',
        description:
          'The "Status" column shows processing progress. Documents still processing can\'t be found yet; for failed ones, check the reason and upload again. Click a title to see the document\'s details and versions.',
        placement: 'top',
      },
    ],
  },
  {
    key: 'search',
    version: 1,
    title: 'Search tour',
    routeName: 'search',
    permission: 'search:use',
    steps: [
      {
        target: 'search-input',
        title: 'Enter keywords or a question',
        description:
          'Type keywords or a document number, or just ask a question. Search matches on both keywords and meaning.',
        placement: 'bottom',
      },
      {
        target: 'search-filters',
        title: 'Filter the results',
        description:
          'Narrow things down by knowledge base, document type, tag or date added. The search reruns automatically when you change a filter.',
        placement: 'bottom',
      },
      {
        target: 'search-syntax',
        title: 'Advanced syntax',
        description:
          'You can also type filters straight into the search box, for example kb:HR-Policies type:pdf. Text in quotes is matched as an exact phrase.',
        placement: 'bottom',
      },
    ],
  },
]
