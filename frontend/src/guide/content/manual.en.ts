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
    title: 'Quick start',
    icon: 'Promotion',
    summary: 'Sign in, learn the layout, and find the right features for your role.',
    tourKey: 'layout',
    topics: [
      {
        title: 'Your first visit',
        steps: [
          {
            title: 'Sign in',
            detail:
              'Open the site URL and use your company account and password, or choose WeCom / DingTalk and scan the QR code. If you see “forbidden”, your account has no role yet—ask an administrator.',
          },
          {
            title: 'Get to know the layout',
            detail:
              'The left sidebar lists features you are allowed to use. The header has global search (Ctrl/Cmd+K), readiness status, Help, theme, language, notifications, and your account menu. The center is the work area; tabs above switch open pages.',
          },
          {
            title: 'Help and tours',
            detail:
              'Help → User guide opens this manual (sections are filtered by your permissions). “Replay tour for this page” restarts the current page tour; “Restart all tours” starts from the layout tour. Prefer the tour first, then the matching chapter here.',
          },
        ],
      },
      {
        title: 'By role',
        steps: [
          {
            title: 'Employee (find answers)',
            detail:
              'Typical path: ① Knowledge Q&A Expert to ask and check citations; ② Search or header search for source text; ③ Knowledge bases to browse allowed docs; ④ My favorites for shortcuts. Upload, ACL, and ops menus are usually hidden.',
          },
          {
            title: 'Knowledge ops (fill gaps, review)',
            detail:
              'Typical path: ① Knowledge gaps for unanswered needs; ② Knowledge objects with similar questions and relations, then submit; ③ Publish review so content is indexed. Read the Concept layer chapter first for terms vs graph. You may also upload or edit documents.',
            permission: CURATION_PERMISSIONS,
          },
          {
            title: 'Admin / platform',
            detail:
              'Org: departments, users, directory sync, groups, roles, audit. Concept side: Terminology and Structured data (see Concept layer + Admin chapters). Platform (Admin → Platform engineering): indexing, models, retrieval, evaluation, Open API. Also AI Admin Assistant. Backup/alerts/virus scan: ops docs.',
            permission: ADMIN_PERMISSIONS,
          },
        ],
      },
      {
        title: 'Ask in three steps',
        permission: 'chat:use',
        steps: [
          {
            title: 'Open Q&A',
            detail: 'Click “Knowledge Q&A Expert” in the sidebar.',
          },
          {
            title: 'Type a question',
            detail:
              'In the bottom box, name the object, scenario, and time (e.g. “2026 new-hire probation review process”), then press Enter (Shift+Enter for a new line).',
          },
          {
            title: 'Check sources',
            detail:
              'Blue numbers in the answer are citations. Hover to preview; open “View source” for the document. For policy, money, or dates, trust the original document.',
          },
        ],
      },
    ],
  },
  {
    id: 'assistant',
    title: 'Knowledge Q&A Expert',
    icon: 'ChatDotRound',
    summary: 'Ask in plain language; answers come only from content you can access, with citations.',
    permission: 'chat:use',
    route: '/assistant',
    tourKey: 'assistant',
    topics: [
      {
        title: 'Ask and follow up',
        steps: [
          {
            title: 'Send a question',
            detail:
              'Type in the bottom box and press Enter. Use the square stop button to abort; use “Regenerate” if the last reply is unsatisfactory.',
          },
          {
            title: 'Follow-up',
            detail:
              'Ask follow-ups in the same chat (e.g. “What about contractors?”). Start “New chat” when changing topics so context does not mix.',
          },
          {
            title: 'Tables and images',
            detail:
              'Answers may include tables (switchable to charts), diagrams, highlighted code, or material images. Controlled documents may disable copy—read on screen only.',
          },
        ],
      },
      {
        title: 'Limit knowledge bases',
        steps: [
          {
            title: 'Pick a scope',
            detail:
              'By default all accessible bases are searched. Click “All accessible knowledge bases” under the input and tick one or more bases.',
          },
          {
            title: 'Clear scope',
            detail: 'Use the clear icon on the selector to restore all accessible bases.',
          },
        ],
      },
      {
        title: 'Citations and sources',
        steps: [
          {
            title: 'Preview a snippet',
            detail: 'Hover a blue citation number to see the quoted fragment.',
          },
          {
            title: 'Open the document',
            detail:
              'Choose “View source” in the popover or a card under “Sources”. The drawer opens the document near the quote; page images load on demand.',
          },
          {
            title: 'When evidence is weak',
            detail:
              'If the system says it found no reliable basis, do not treat the reply as policy. Use “Submit knowledge request” so ops can add content.',
          },
        ],
      },
      {
        title: 'Related concepts',
        steps: [
          {
            title: 'What you see',
            detail:
              'After an answer, a collapsible “Related concepts” block may appear when terminology or linked knowledge was hit. Each item can show the canonical name, type, aliases, equipment/external ids, and related knowledge-object titles—so you can match slang to the standard name.',
          },
          {
            title: 'How to use it',
            detail:
              'Expand and check whether aliases and ids match what you meant. Related knowledge hints at other standard Q&As. The block is read-only for employees. If concepts are wrong or missing, submit a knowledge request or “Not helpful” so ops can fix Terminology, Structured data, or Knowledge objects.',
          },
        ],
      },
      {
        title: 'Feedback and knowledge requests',
        steps: [
          {
            title: 'Rate the answer',
            detail: 'Click “Helpful” to record; “Not helpful” lets you pick a reason and add notes.',
          },
          {
            title: 'Submit a knowledge request',
            detail:
              'When nothing answers your need, submit a request. After ops handles it, you get a message under the header bell.',
          },
        ],
      },
      {
        title: 'Manage chats',
        steps: [
          {
            title: 'New chat',
            detail: 'Use “New chat” at the top left for a blank session.',
          },
          {
            title: 'Find, rename, delete',
            detail:
              'The left list is grouped by time and searchable. Use “…” on a chat to rename or delete. Only you see your chat list.',
          },
        ],
      },
    ],
  },
  {
    id: 'knowledge',
    title: 'Knowledge bases',
    icon: 'Collection',
    summary: 'Organize documents: upload, online edit, ACL, versions, and batch jobs.',
    permission: 'kb:read',
    route: '/knowledge',
    tourKey: 'knowledge',
    topics: [
      {
        title: 'Browse documents',
        steps: [
          {
            title: 'Find a base',
            detail:
              'Open “Knowledge bases” and filter by name or description. You only see bases you can access; click a name to open it.',
          },
          {
            title: 'Open a document',
            detail:
              'On the detail page filter by title, status, or tags; open a document for body text, chunks, version history, and comments.',
          },
        ],
      },
      {
        title: 'Create a knowledge base',
        permission: 'kb:create',
        steps: [
          {
            title: 'Create',
            detail:
              'Click “New knowledge base”, enter name and description, and choose visibility: org-readable or members only.',
          },
          {
            title: 'Controlled template (optional)',
            detail:
              'If a “Controlled” template is offered, it turns on watermark, copy-protect, download requires edit, and members-only visibility—for policies and sensitive files.',
          },
          {
            title: 'Grant access',
            detail:
              'Open “Permissions” and grant view / edit / manage to departments (with children), groups, roles, or users. Changes apply immediately.',
          },
        ],
      },
      {
        title: 'Allow and deny ACL',
        permission: 'kb:create',
        steps: [
          {
            title: 'Allow grants',
            detail:
              'Add principals and levels in Permissions. Org-visible bases can still use finer document ACL.',
          },
          {
            title: 'Deny list',
            detail:
              'With deny effect, a denied user or department cannot see the resource even if other allows exist (deny-wins). KB managers can still enter to fix ACL. Cache invalidates after changes; Q&A rechecks permissions.',
          },
        ],
      },
      {
        title: 'Upload and maintain documents',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Upload',
            detail:
              'On the base detail page click “Upload”, drag or pick files (multi-select). PDF, Word (.docx/.doc), Excel, PPT (.pptx), TXT, Markdown, HTML, and more are supported; identical content is deduplicated.',
          },
          {
            title: 'Wait for processing',
            detail:
              'Files are parsed, chunked, and indexed. Watch the Status column (parsing / indexing / ready / failed). Ready means searchable and citable—usually seconds to a few minutes.',
          },
          {
            title: 'Failures',
            detail:
              'Hover a failed status for the reason (encryption, empty scan, unsupported type). Fix and re-upload, or use “Reprocess” on the document.',
          },
          {
            title: 'New versions',
            detail:
              'Uploading the same name creates a new version; older ones stay under version history on the document page.',
          },
        ],
      },
      {
        title: 'Online edit and collaboration',
        permission: 'doc:upload',
        steps: [
          {
            title: 'New online document',
            detail:
              'Choose “New document” (or equivalent), write in the Markdown editor, and save. Saving starts the same parse and index pipeline.',
          },
          {
            title: 'Edit an existing document',
            detail: 'With edit rights, open “Edit” on the document page and save a new version.',
          },
          {
            title: 'Owner, review, comments',
            detail:
              'Assign an owner and review cadence; comment on the detail page. Due reviews notify the right people (per configuration).',
          },
          {
            title: 'Favorite',
            detail: 'Star a document on its detail page; open it later from “My favorites”.',
          },
        ],
      },
      {
        title: 'Batch reprocess and missing page images',
        permission: 'doc:upload',
        steps: [
          {
            title: 'Batch reprocess',
            detail:
              'Select multiple documents and run “Reprocess” (or batch actions) after failures or rule changes. Avoid hammering items already parsing.',
          },
          {
            title: 'Missing page images filter',
            detail:
              'If the list offers a “missing page images” filter, use it to find docs that should have page/slide rasters but failed, then re-run processing.',
          },
        ],
      },
    ],
  },
  {
    id: 'search',
    title: 'Search',
    icon: 'Search',
    summary: 'Hybrid keyword and semantic search to open the source document.',
    permission: 'search:use',
    route: '/search',
    tourKey: 'search',
    topics: [
      {
        title: 'Basic search',
        steps: [
          {
            title: 'Enter a query',
            detail:
              'Use the header search box (Ctrl/Cmd+K) or the Search page. Enter keywords, a doc id, or a full question, then press Enter. Only permitted content is returned.',
          },
          {
            title: 'Read results',
            detail:
              'Results are ranked with highlights; open a title for the document. If empty, change terms, clear filters, or check access.',
          },
        ],
      },
      {
        title: 'Filters and inline syntax',
        steps: [
          {
            title: 'Filters',
            detail:
              'Filter by knowledge base, type, tags, and ingest time; search refreshes automatically. “Clear filters” resets.',
          },
          {
            title: 'Inline syntax',
            detail:
              'In the box: kb:name, tag:label, type:pdf, date:2026-03, after:2026-01-01; quoted text matches an exact phrase.',
          },
        ],
      },
    ],
  },
  {
    id: 'favorites',
    title: 'My favorites',
    icon: 'Star',
    summary: 'Star documents and knowledge objects; browse recent items.',
    permission: 'kb:read',
    route: '/favorites',
    topics: [
      {
        title: 'Favorites and recent',
        steps: [
          {
            title: 'Open the page',
            detail: 'Click “My favorites”. Use the Favorites and Recently viewed tabs.',
          },
          {
            title: 'Open an item',
            detail: 'Click a title to open the document or knowledge object.',
          },
          {
            title: 'Unfavorite',
            detail:
              'Toggle the star again in the list or on the detail page. Recent items are recorded automatically.',
          },
        ],
      },
    ],
  },
  {
    id: 'notifications',
    title: 'Notifications',
    icon: 'Bell',
    summary: 'In-app alerts such as completed knowledge requests.',
    route: '/notifications',
    topics: [
      {
        title: 'Read notifications',
        steps: [
          {
            title: 'Entry points',
            detail:
              'Click the header bell or “Notifications” in the account menu. The badge is the unread count.',
          },
          {
            title: 'Open and mark read',
            detail:
              'Open an item for details; it is marked read. Common types: knowledge request completed, review reminders.',
          },
          {
            title: 'Empty list',
            detail:
              'No rows means nothing pending. After you submit a knowledge request, wait until ops finishes before a push appears.',
          },
        ],
      },
    ],
  },
  {
    id: 'concepts',
    title: 'Concept layer (terms · entities · graph · ontology)',
    icon: 'Connection',
    summary:
      'Align canonical names, relations, and equipment ids so search and Q&A hit better—no SPARQL or graph DB.',
    permission: [
      'chat:use',
      'gap:review',
      'ko:edit',
      'review:approve',
      'admin:retrieval',
    ],
    topics: [
      {
        title: 'Why it exists',
        steps: [
          {
            title: 'Problem it solves',
            detail:
              'The same thing has slang, codes, and spoken names; docs also cite equipment and work-order ids. The concept layer keeps canonical names + aliases + types, knowledge-object relations, and external-id mappings so retrieval can expand terms, Q&A can attach related concepts, and hits on knowledge objects can multi-hop along relations.',
          },
          {
            title: 'Three building blocks',
            detail:
              '① Terminology = entity dictionary (canonical name, type, aliases); ② Knowledge objects (KOs) and KO relations = reviewed standard knowledge and “graph” edges; ③ Structured data = ERP/MES id mirrors mapped to terms or KOs. Documents remain the source text; the concept layer aligns wording and links—it does not replace uploads.',
          },
          {
            title: 'What employees see',
            detail:
              'The collapsible “Related concepts” block after Q&A (canonical name, aliases, equipment/ids, related KOs). Site search has no concept cards but benefits from alias expansion; KO hits show a Knowledge object badge. Maintenance lives under Admin and Knowledge ops, not the employee menu.',
            permission: 'chat:use',
          },
        ],
      },
      {
        title: 'Glossary',
        steps: [
          {
            title: 'Entity / term',
            detail:
              'An “entity” here is mainly a terminology row: canonical name, business type (device, process, defect, policy, IT term, …), aliases, and enabled state. Ingest may tag chunks with entity_ids so Q&A can expand related passages in the same document.',
          },
          {
            title: 'Graph (KO relations)',
            detail:
              'Not Neo4j: edges between knowledge objects (relatedTo, partOf, dependsOn, causes, mitigates, appliesTo, …). When graph recall is on, a KO hit pulls neighbors for fusion. Ops edit relations in the KO editor; Terminology “Relation preview” shows ~1-hop terms / structured / KOs around a term.',
          },
          {
            title: 'Ontology (OWL)',
            detail:
              'The ontology is the contract of allowed classes and relations (TBox) in ontology/enterprise.ttl (open in Protégé). Runtime instances (ABox) stay in PostgreSQL via Terminology, KO, and Structured pages. The in-app Ontology dialog is read-only—no web OWL editor and no SPARQL. Enum changes need engineering to sync code and TTL.',
            permission: 'admin:retrieval',
          },
        ],
      },
      {
        title: 'Suggested maintenance order',
        permission: ['admin:retrieval', 'ko:edit', 'gap:review'],
        steps: [
          {
            title: 'Dictionary → knowledge → links',
            detail:
              '① Create terms and aliases, then Sync synonyms; ② Capture standard Q&A as knowledge objects with relations; ③ Map external ids in Structured data to terms/KOs. Finally ask real questions and check Related concepts.',
          },
        ],
      },
    ],
  },
  {
    id: 'curation',
    title: 'Knowledge operations',
    icon: 'Opportunity',
    summary: 'Gaps → knowledge objects → publish review; turn misses into searchable knowledge.',
    permission: CURATION_PERMISSIONS,
    route: '/curation/gaps',
    topics: [
      {
        title: 'What knowledge gaps are',
        permission: 'gap:review',
        steps: [
          {
            title: 'Purpose',
            detail:
              'Collect “no evidence / weak evidence / Not helpful / knowledge request” cases, cluster them, and let ops add documents or knowledge objects so the same miss does not repeat.',
          },
          {
            title: 'How employees create gaps',
            detail:
              'In Knowledge Q&A Expert: click Not helpful with a reason, or Submit knowledge request when evidence is missing. Employees do not see the ops board; they get a notification when handled.',
          },
        ],
      },
      {
        title: 'Gap board',
        permission: 'gap:review',
        steps: [
          {
            title: 'Open and read stats',
            detail:
              'Knowledge ops → Knowledge gaps. Top cards show open, in progress, unresolved clusters; click source-type cards to filter (no evidence, weak evidence, negative feedback, user request).',
          },
          {
            title: 'Filter the list',
            detail:
              'On the Gaps tab filter by status, source, knowledge base, and keyword; sort by frequency or recency; optionally “Assigned to me” → Search.',
          },
          {
            title: 'Cluster',
            detail:
              'Click Cluster now to merge similar questions. The Clusters tab shows representative questions, counts, and source mix; open a row to return to the list with that cluster filter.',
          },
          {
            title: 'Open the workbench',
            detail: 'Click a row to assign and resolve the gap.',
          },
        ],
      },
      {
        title: 'Gap workbench',
        permission: 'gap:review',
        steps: [
          {
            title: 'Read context',
            detail:
              'Review rewritten and original questions, hit counts, recall scores, and chat excerpts; expand the QA Trace (JSON steps) when debugging.',
          },
          {
            title: 'Assign',
            detail:
              'Set owner, knowledge base, priority, and due date → Save, or Assign to me so the team can claim hot gaps.',
          },
          {
            title: 'Draft a knowledge object',
            detail:
              'With ko:edit: pick KB, KO type, optional reference docs and notes → Generate KO draft. You land in the KO editor (AI may fall back to an empty draft).',
            permission: 'ko:edit',
          },
          {
            title: 'Other resolutions',
            detail:
              'Link existing document: materials already cover it. Mark duplicate: pick a sibling gap. Reject: decline the request. Reopen if needed. Askers are notified when applicable.',
          },
        ],
      },
      {
        title: 'What knowledge objects (KOs) are',
        permission: ['ko:edit', 'gap:review', 'review:approve'],
        steps: [
          {
            title: 'Purpose',
            detail:
              'Turn “canonical question + similar phrasings + structured answer + document sources” into a reviewable, indexed item. Published KOs are first-class search hits (often boosted) and nodes for graph recall—better as standard answers than buried prose.',
          },
          {
            title: 'Pick a type',
            detail:
              'Common types: FAQ, Q&A, card, policy summary, device, process, defect, policy, IT term, …. Choose by business meaning; ontology soft-checks may warn on odd relation pairs without hard-blocking.',
          },
        ],
      },
      {
        title: 'Write a knowledge object',
        permission: 'ko:edit',
        steps: [
          {
            title: 'Create',
            detail:
              'Knowledge ops → Knowledge objects → New (KB, type, canonical question), or Generate FAQs from a document, or draft from a gap workbench.',
          },
          {
            title: 'Fill the body',
            detail:
              'Edit title, type, canonical question, similar questions (one per line), and answer (Markdown preview). Cover spoken variants in similar questions so rewrite can match.',
          },
          {
            title: 'Sources',
            detail:
              'Attach source documents with the picker and jump to verify. Key claims in the answer should be grounded before publish.',
          },
          {
            title: 'Relations (graph edges)',
            detail:
              'Add the peer KO id and a relation type: related / part of / depends on / causes / mitigates / applies to. These edges feed multi-hop recall—wrong ids pollute expansion. Paste UUIDs when no search picker is available; run conflict check before submit.',
          },
          {
            title: 'Owner and validity',
            detail: 'Set validity window and owner; optionally Adopt an AI draft, then edit by hand.',
          },
          {
            title: 'Save and submit',
            detail:
              'Save as draft → optional Conflict check → Submit for review with a note. Authors can Withdraw while pending.',
          },
        ],
      },
      {
        title: 'Publish review and retire',
        permission: 'review:approve',
        steps: [
          {
            title: 'Review queue',
            detail:
              'Knowledge ops → Publish review; switch pending / approved / rejected; open a row in the KO editor.',
          },
          {
            title: 'Approve or reject',
            detail:
              'Check question, answer, sources, and relations; confirm again if conflict warnings appear. Approve and publish, or reject with comments. After publish, search shows a KO badge and Q&A can cite it once indexed.',
          },
          {
            title: 'Retire',
            detail:
              'Published items can be taken offline with a reason so they stop being formal citeable knowledge (see on-page status).',
          },
        ],
      },
    ],
  },
  {
    id: 'admin',
    title: 'Administration',
    icon: 'Setting',
    summary: 'Organization, accounts, permissions, audit, terminology, and structured data.',
    permission: ADMIN_PERMISSIONS,
    topics: [
      {
        title: 'Directory sync',
        permission: 'admin:directory',
        steps: [
          {
            title: 'Configure a source',
            detail:
              'Open Directory sync, create or edit a source (WeCom / DingTalk / Weaver / Excel, etc.), fill secrets and field mappings, then save.',
          },
          {
            title: 'Preview then apply',
            detail:
              'Always Preview adds/updates/disables for departments and users first; Apply only after the diff looks right. Never skip preview in production.',
          },
          {
            title: 'Schedule and history',
            detail:
              'Set a sync interval if needed. Open a run in history for details; fix config from the error and retry.',
          },
        ],
      },
      {
        title: 'Departments and users',
        permission: ['admin:dept', 'admin:user'],
        steps: [
          {
            title: 'Departments',
            detail:
              'Departments maintains the tree: create, rename, move. Synced fields are often read-only—change them upstream, then sync.',
            permission: 'admin:dept',
          },
          {
            title: 'Users',
            detail:
              'Users shows accounts, department membership, roles, and groups; enable/disable and password login depend on the page. Master data for synced users comes from the source system.',
            permission: 'admin:user',
          },
        ],
      },
      {
        title: 'Groups and roles',
        permission: ['admin:group', 'admin:role'],
        steps: [
          {
            title: 'Groups',
            detail:
              'Groups build cross-department teams. After adding members, grant KB access by group.',
            permission: 'admin:group',
          },
          {
            title: 'Roles',
            detail:
              'Roles toggles feature permissions (chat:use, kb:create, admin:*, …). Assign roles in bulk. Admin permissions are never granted silently; users may need a refresh or re-login for menus.',
            permission: 'admin:role',
          },
        ],
      },
      {
        title: 'Audit log',
        permission: 'admin:audit',
        steps: [
          {
            title: 'Query',
            detail:
              'Open Audit log and filter by action, resource type/id, actor, and time. Open a row for before/after diffs.',
          },
        ],
      },
      {
        title: 'Terminology (entity dictionary)',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Purpose',
            detail:
              'Maintain canonical name + type + aliases. Q&A rewrite and site search expand queries by alias (e.g. canonical “access control list”, alias “ACL”). Enabled terms can also sync into OpenSearch synonyms for the BM25 path.',
          },
          {
            title: 'Open and filter',
            detail:
              'Admin → Terminology. Filter by canonical keyword, type (device / process / defect / policy clause / IT term / other), and status (enabled/disabled), then search.',
          },
          {
            title: 'Create a term',
            detail:
              'New term: canonical name, type, status, description; optionally paste aliases (comma or newlines) → Save. Keep names unique and aliases complete.',
          },
          {
            title: 'Maintain aliases',
            detail:
              'In the Aliases column type and Add; click × on a tag to remove. The edit dialog usually changes name/type/description/status—aliases are edited in the grid.',
          },
          {
            title: 'Sync synonyms',
            detail:
              'After editing enabled terms, click Sync synonyms to write OpenSearch and hot-reload. Disabled terms are skipped. Skipping sync leaves index synonyms stale.',
          },
          {
            title: 'Relation preview and ontology',
            detail:
              'Row action Relation preview opens a force graph: blue=term, green=structured, yellow=KO (~1 hop). Ontology is a read-only OWL contract summary (TTL in the repo; instances in this DB).',
          },
        ],
      },
      {
        title: 'Structured data (id mirrors)',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Purpose',
            detail:
              'Mirror ERP/MES/QMS objects (equipment, work orders, spare parts, or generic domain rows) and map external_id to terms or KOs. Q&A “Related concepts” equipment/ids and the resolve API depend on this. Sync updates mirrors only—it does not auto-create terms or KOs.',
          },
          {
            title: 'Domains and sources',
            detail:
              'Admin → Structured data. Pick a domain on the left (equipment often has device/WO/spare tabs; others use generic records). Create sources or domains from the top bar.',
          },
          {
            title: 'Manual rows and search',
            detail:
              'Filter by source and keyword. On non-equipment domains, New record fills external id, object type, title, etc. Click a row to open the mapping panel below.',
          },
          {
            title: 'Map to term / KO',
            detail:
              'Enter a terminology id or KO id → Add mapping. Correct mappings feed aliases, ids, and related knowledge in Q&A. You usually paste UUIDs copied from Terminology or KO lists.',
          },
          {
            title: 'Sync a source',
            detail:
              'If the source has a csv/rest connector in meta (often set by ops—no full connector editor in UI), select it and Sync; the scheduler may also pull on an interval. See docs/ops/structured-connectors.md.',
          },
          {
            title: 'Id resolve (debug)',
            detail:
              'Bottom Resolve form: object_type, external_id, … → Resolve and inspect JSON. For mapping QA, not for employees.',
          },
        ],
      },
    ],
  },
  {
    id: 'admin-agent',
    title: 'AI Admin Assistant',
    icon: 'MagicStick',
    summary: 'Run guarded admin tasks in natural language: understand → clarify → plan → approve → execute.',
    permission: ADMIN_AGENT_PERMISSIONS,
    route: '/admin/agent',
    topics: [
      {
        title: 'Start a task',
        steps: [
          {
            title: 'Open the assistant',
            detail: 'Admin → AI Admin Assistant. Example chips fill common prompts.',
          },
          {
            title: 'Describe the intent',
            detail:
              'State the goal in one sentence (e.g. “Enable password login for Zhang San”). The model only fills intent and slots; code owns write steps.',
          },
          {
            title: 'Clarify required fields',
            detail:
              'Missing names or groups trigger questions or candidate lists. Tasks outside your permissions stop here.',
          },
        ],
      },
      {
        title: 'Approve and execute',
        steps: [
          {
            title: 'Review the plan',
            detail:
              'After clarify, a fixed step preview appears (resolve names, validate, candidates). Confirm each target.',
          },
          {
            title: 'Risk and approval',
            detail:
              'High-risk steps need an acknowledge checkbox. Approval lasts about 30 minutes, once, for the requester only. Timeout means start over.',
          },
          {
            title: 'Execute and report',
            detail:
              'On approve, steps run with rollback on failure and a final report. History can replay events. Temporary passwords are redacted.',
          },
          {
            title: 'What it will not do',
            detail:
              'It will not delete departments/roles/users, change model or retrieval config, or issue API keys. Use the dedicated admin pages for those.',
          },
        ],
      },
    ],
  },
  {
    id: 'platform',
    title: 'Platform engineering',
    icon: 'Cpu',
    summary: 'Indexing, models, retrieval, evaluation, and Open API (Admin → Platform engineering).',
    permission: PLATFORM_PERMISSIONS,
    topics: [
      {
        title: 'Indexing',
        permission: 'admin:index',
        steps: [
          {
            title: 'Inspect jobs',
            detail:
              'Open Indexing to see the document index queue, failures, and retries. Growing backlog: check worker / outbox health first.',
          },
          {
            title: 'Retry and rebuild',
            detail:
              'Retry failed jobs from the UI. Full rebuild from the database is heavy—run off-peak and do not submit twice while in progress.',
          },
        ],
      },
      {
        title: 'Models',
        permission: 'admin:model',
        steps: [
          {
            title: 'Inspect and probe',
            detail:
              'Models lists chat, embedding, and rerank endpoints. Run health checks for connectivity and latency.',
          },
          {
            title: 'Switch chat models',
            detail:
              'Changing primary / fallback chat usually applies immediately. Embedding/rerank are often view/probe only; changing embedding dimensions needs the migration ops guide—do not only rename the model.',
          },
        ],
      },
      {
        title: 'Retrieval strategy',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Tune parameters',
            detail:
              'Retrieval configures recall, fusion, and rerank. Note current values, then compare with offline eval before rolling out.',
          },
          {
            title: 'Trace samples',
            detail: 'Use on-page tracing/samples to inspect recall and scores when debugging.',
          },
        ],
      },
      {
        title: 'Datasets and offline eval',
        permission: 'admin:retrieval',
        steps: [
          {
            title: 'Maintain datasets',
            detail:
              'Eval datasets: create or import gold questions; edit expected docs/answer points in the detail page.',
          },
          {
            title: 'Run evaluation',
            detail:
              'Offline eval: pick a dataset and strategy, start a run, then open the detail for pass rate and failures.',
          },
          {
            title: 'Compare strategies',
            detail:
              'Select 2–4 completed runs in the list and open compare to decide whether to adopt a new strategy.',
          },
        ],
      },
      {
        title: 'Open API',
        permission: 'admin:openapi',
        steps: [
          {
            title: 'Create an app',
            detail:
              'Open API → New app: name it, bind principals (dept/group/role), and tick allowed knowledge bases. The app only sees that intersection—no admin bypass.',
          },
          {
            title: 'Issue an API key',
            detail:
              'On the app detail, create a key, copy it once, and store it safely. Configure per-minute rate limits and IP allowlists.',
          },
          {
            title: 'Integrate and logs',
            detail:
              'Use the Integration guide tab for REST/MCP; preview retrieval within scope; use call logs for 401/403/429. Rotate leaked keys and disable old ones.',
          },
        ],
      },
    ],
  },
  {
    id: 'analytics',
    title: 'Analytics',
    icon: 'DataAnalysis',
    summary: 'Use metrics to decide what knowledge to add next and whether the system is healthy.',
    permission: 'analytics:view',
    route: '/analytics',
    topics: [
      {
        title: 'Read the dashboards',
        steps: [
          {
            title: 'Usage',
            detail:
              'Questions, DAU, and trends; filter by date and knowledge base to see who uses what.',
          },
          {
            title: 'Quality and performance',
            detail:
              'Quality covers satisfaction, refusals, and misses; Performance covers time-to-first-token and stage latency. When quality drops, start with gaps and frequent unanswered questions.',
          },
          {
            title: 'Hot questions and content',
            detail:
              'Hot questions list frequency and unanswered counts; Content shows failed docs and citations. Prioritize high-frequency misses for new docs or KOs.',
          },
          {
            title: 'Model usage',
            detail: 'Token use by feature and user for cost and quota planning.',
            permission: 'analytics:usage',
          },
        ],
      },
    ],
  },
]

export const MANUAL_FAQ: ManualFaq[] = [
  {
    question: 'Why can I not find a document in search?',
    answer:
      'Common causes: ① no access to the base or document (including a deny hit); ② still parsing/indexing; ③ processing failed. Check Status on the base detail page or ask the base admin.',
  },
  {
    question: 'Can I trust the AI answer?',
    answer:
      'Answers use only content you may access and cite sources; weak evidence leads to refusal or uncertainty. For policy, money, or dates, open the citation and verify the original.',
    permission: 'chat:use',
  },
  {
    question: 'Can others see my questions?',
    answer:
      'Your chat list is private. The system keeps QA logs for quality; staff with the right admin rights may use them for support and analytics—not other users’ chat lists.',
    permission: 'chat:use',
  },
  {
    question: 'How soon after upload is a file searchable?',
    answer:
      'Usually seconds to a few minutes depending on size and queue. Watch Status on the base detail page; if it stalls, ask an admin to check Indexing.',
    permission: 'doc:upload',
  },
  {
    question: 'Why is a menu or button missing?',
    answer:
      'Menus follow role feature permissions; document actions also need KB/document ACL. Ask an admin to assign a role, or a base admin to grant access.',
  },
  {
    question: 'I revoked access—why can they still ask about it?',
    answer:
      'ACL changes invalidate search cache and Q&A rechecks during generation. If it persists, check other group/dept grants or whether KB manage bypasses a document deny.',
    permission: ADMIN_PERMISSIONS,
  },
  {
    question: 'Indexing backlog or many failures?',
    answer:
      'Open Indexing for error detail; confirm worker, outbox-dispatcher, OpenSearch, and Qdrant are healthy. Reprocess single docs or retry batches; full rebuild only when needed, off-peak.',
    permission: 'admin:index',
  },
  {
    question: 'Open API returns 401 / 403 / 429?',
    answer:
      '401: bad or disabled key; 403: IP not allowed or no KB access; 429: rate limit. Check key, allowed bases, IP, and limits on the app detail page, and read call logs.',
    permission: 'admin:openapi',
  },
  {
    question: 'Directory preview shows a huge disable count—safe to apply?',
    answer:
      'First verify source filters were not misconfigured. Sync has a safety ratio for disables; fix upstream data before applying to avoid mass account disablement.',
    permission: 'admin:directory',
  },
  {
    question: 'Where do “Related concepts” come from? What if they are wrong?',
    answer:
      'From terminology hits, structured id mappings, and linked knowledge objects. If missing or mismatched: add aliases and Sync synonyms; map the right external_id in Structured data; publish or relate the missing KOs.',
    permission: 'chat:use',
  },
  {
    question: 'I added KO relations—does search change?',
    answer:
      'Published KOs are indexed and may be boosted. Relations feed a third multi-hop path when graph recall is enabled in retrieval strategy; unpublished or retired KOs do not. Validate with offline eval / graph-gate.',
    permission: ['ko:edit', 'admin:retrieval'],
  },
  {
    question: 'Do I edit the OWL ontology in the web UI?',
    answer:
      'No. Ontology is read-only in the app. The class/relation contract lives in ontology/enterprise.ttl; instances are edited in Terminology, KO, and Structured pages. Enum changes need engineering plus TTL validation—no SPARQL here.',
    permission: 'admin:retrieval',
  },
]
