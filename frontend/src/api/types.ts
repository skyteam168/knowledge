export interface ApiErrorBody {
  code: string
  message: string
  detail: unknown
  trace_id: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface PageParams {
  page?: number
  size?: number
}

export type DependencyState = 'up' | 'down'

export interface DependencyStatus {
  status: DependencyState
  required: boolean
  /** Omitted unless the request carries the metrics token. */
  latency_ms?: number
  error?: string | null
}

export interface ReadinessResponse {
  status: 'ready' | 'degraded' | 'not_ready'
  checks: Record<string, DependencyStatus>
}

export interface HealthResponse {
  status: 'ok'
  app: string
  env: string
}

// ---- identity (mirrors backend app/schemas/identity.py) --------------------

export interface Organization {
  id: string
  code: string
  name: string
  status: string
  created_at: string
}

export type DirectorySourceType = 'wecom' | 'dingtalk' | 'weaver' | 'excel'
/** 'local' = maintained on this platform; otherwise owned by a directory source. */
export type RecordSource = 'local' | 'keycloak' | DirectorySourceType

export interface Department {
  id: string
  parent_id: string | null
  name: string
  sort_order: number
  source: RecordSource
  external_id: string | null
  status: 'active' | 'archived'
  path_name: string | null
}

export interface DepartmentNode extends Department {
  children: DepartmentNode[]
}

export interface DepartmentCreate {
  name: string
  parent_id?: string | null
  sort_order?: number
}

export type DepartmentUpdate = Partial<DepartmentCreate>

export interface RoleBrief {
  id: string
  code: string
  name: string
}

export interface GroupBrief {
  id: string
  name: string
}

export interface UserDepartmentBrief {
  id: string
  name: string
  path_name: string
  is_primary: boolean
}

export interface UserIdentityBrief {
  provider: string
  external_id: string
}

export interface User {
  id: string
  username: string
  email: string | null
  display_name: string | null
  department_id: string | null
  employee_no: string | null
  mobile: string | null
  job_title: string | null
  source: RecordSource
  is_active: boolean
  keycloak_bound: boolean
  last_login_at: string | null
  created_at: string
  departments: UserDepartmentBrief[]
}

export interface UserDetail extends User {
  roles: RoleBrief[]
  groups: GroupBrief[]
  identities: UserIdentityBrief[]
}

export interface UserCreate {
  username: string
  email?: string | null
  display_name?: string | null
  department_id?: string | null
  department_ids?: string[]
  employee_no?: string | null
  mobile?: string | null
  job_title?: string | null
}

export interface UserUpdate {
  email?: string | null
  display_name?: string | null
  department_id?: string | null
  department_ids?: string[]
  employee_no?: string | null
  mobile?: string | null
  job_title?: string | null
  is_active?: boolean
}

export interface PasswordLoginOut {
  username: string
  created: boolean
  temporary_password: string
}

export interface UserQuery extends PageParams {
  keyword?: string
  department_id?: string
  include_sub_departments?: boolean
  group_id?: string
  is_active?: boolean
}

export interface Group {
  id: string
  name: string
  description: string | null
  source: 'local' | 'keycloak'
  member_count: number
}

export interface GroupCreate {
  name: string
  description?: string | null
}

export type GroupUpdate = Partial<GroupCreate>

export interface Permission {
  code: string
  name: string
}

export interface Role {
  id: string
  code: string
  name: string
  description: string | null
  is_system: boolean
  /** Granted automatically to users created by directory sync or first login. */
  is_default: boolean
  permissions: string[]
}

export interface RoleCreate {
  code: string
  name: string
  description?: string | null
}

export type RoleUpdate = Partial<Omit<RoleCreate, 'code'>> & { is_default?: boolean }

export interface RoleBulkAssign {
  action: 'grant' | 'revoke'
  department_ids: string[]
  group_ids: string[]
  include_inactive: boolean
  dry_run: boolean
}

export interface RoleBulkResult {
  matched: number
  changed: number
  unchanged: number
  skipped: number
  dry_run: boolean
}

export interface MeResponse {
  id: string
  username: string
  display_name: string | null
  email: string | null
  org: Organization
  department: Department | null
  roles: RoleBrief[]
  groups: GroupBrief[]
  permissions: string[]
  is_platform_admin: boolean
}

// ---- audit ------------------------------------------------------------------

export interface AuditDiffEntry {
  before: unknown
  after: unknown
}

export interface AuditLog {
  id: string
  actor_id: string | null
  actor_name: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  diff: Record<string, AuditDiffEntry> | null
  ip: string | null
  user_agent: string | null
  trace_id: string | null
  method: string | null
  path: string | null
  status_code: number | null
  created_at: string
}

// ---- knowledge (mirrors backend app/schemas/knowledge.py) ---------------------

export type KbVisibility = 'org' | 'restricted'
export type AclPermission = 'read' | 'edit' | 'manage'
export type PrincipalType = 'user' | 'group' | 'role' | 'dept'
export type DocumentStatus = 'uploaded' | 'parsing' | 'parsed' | 'indexing' | 'indexed' | 'failed'
export type ChunkType = 'text' | 'table' | 'title'

export interface AclEntry {
  principal_type: PrincipalType
  principal_id: string
  permission: AclPermission
}

export interface AclEntryOut extends AclEntry {
  principal_name: string | null
}

export interface KbAcl {
  visibility: KbVisibility
  entries: AclEntryOut[]
}

export interface KbAclUpdate {
  visibility: KbVisibility
  entries: AclEntry[]
}

export interface DocumentAcl {
  inherit: boolean
  kb_visibility: KbVisibility
  kb_entries: AclEntryOut[]
  entries: AclEntryOut[]
}

export interface DocumentAclUpdate {
  inherit: boolean
  entries: AclEntry[]
}

export interface KnowledgeBase {
  id: string
  name: string
  description: string | null
  visibility: KbVisibility
  created_by: string | null
  created_at: string
  updated_at: string
  document_count: number
  my_permission: AclPermission | null
}

export interface KnowledgeBaseCreate {
  name: string
  description?: string | null
  visibility?: KbVisibility
}

export interface KnowledgeBaseUpdate {
  name?: string
  description?: string | null
}

export interface KbDocument {
  id: string
  kb_id: string
  title: string
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  version: number
  status: DocumentStatus
  error_message: string | null
  tags: string[]
  metadata: Record<string, unknown>
  effective_from: string | null
  effective_to: string | null
  acl_inherit: boolean
  chunk_count: number | null
  parsed_at: string | null
  chunked_at: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  my_permission: AclPermission | null
}

export interface DocumentVersion {
  version: number
  filename: string
  mime_type: string
  size_bytes: number
  sha256: string
  created_by: string | null
  created_at: string
}

export interface DocumentDetail extends KbDocument {
  kb_name: string
  versions: DocumentVersion[]
}

export interface DocumentUpdate {
  title?: string
  tags?: string[]
  metadata?: Record<string, unknown>
  effective_from?: string | null
  effective_to?: string | null
}

export interface DocumentQuery extends PageParams {
  status?: DocumentStatus
  keyword?: string
}

export interface UploadInit {
  filename: string
  size_bytes: number
  mime_type?: string | null
  sha256: string
}

export interface UploadInitResult {
  duplicate: boolean
  document: KbDocument | null
  ticket: string | null
  upload_url: string | null
  method: string
  expires_in: number | null
}

export interface UploadResult {
  document: KbDocument
  duplicate: boolean
  new_version: boolean
}

export interface Chunk {
  id: string
  document_version: number
  parent_id: string | null
  level: number
  seq: number
  heading_path: string[]
  content: string
  token_count: number
  page_start: number | null
  page_end: number | null
  sheet_name: string | null
  slide_number: number | null
  chunk_type: ChunkType
}

export interface Preview {
  url: string
  filename: string
  mime_type: string
  expires_in: number
}

export interface PrincipalOption {
  type: PrincipalType
  id: string
  name: string
  description: string | null
}

export interface DirectoryDepartment {
  id: string
  name: string
  path_name: string | null
  children: DirectoryDepartment[]
}

export interface AuditQuery extends PageParams {
  actor_id?: string
  action?: string
  resource_type?: string
  resource_id?: string
  trace_id?: string
  start?: string
  end?: string
}

// ---- indexing -----------------------------------------------------------------

export type OutboxStatus = 'pending' | 'processing' | 'done' | 'dead'

export interface OutboxEvent {
  id: string
  aggregate_type: string
  aggregate_id: string
  event_type: string
  payload: Record<string, unknown>
  status: OutboxStatus
  retry_count: number
  last_error: string | null
  created_at: string
  processed_at: string | null
  next_attempt_at: string | null
  locked_until: string | null
}

export type OutboxStats = Record<OutboxStatus, number>

export interface OutboxQuery extends PageParams {
  status?: OutboxStatus
  event_type?: string
}

export interface RetryResult {
  count: number
}

export type GenerationStatus = 'building' | 'active' | 'retired' | 'failed'

export interface IndexGeneration {
  version: number
  qdrant_collection: string
  opensearch_index: string
  embedding_model: string
  embedding_dim: number
  status: GenerationStatus
  stats: Record<string, unknown>
  error: string | null
  created_at: string
  activated_at: string | null
  retired_at: string | null
}

export interface BackendDiff {
  count: number
  missing_count: number
  extra_count: number
  missing: string[]
  extra: string[]
}

export interface ConsistencyReport {
  kb_id: string
  generation: number
  checked_at: string
  consistent: boolean
  pg_count: number
  qdrant: BackendDiff
  opensearch: BackendDiff
  reindex_documents: string[]
  skipped_documents: number
}

export interface RepairQueued {
  queued: boolean
  kb_id: string
}

// ---- search / retrieval ----------------------------------------------------------------

export type SearchRoute = 'dense' | 'sparse'

export interface SearchQuery {
  q: string
  kb_ids?: string[]
  tags?: string[]
  doc_types?: string[]
  date_from?: string
  /** Exclusive upper bound. */
  date_to?: string
  top_k?: number
  profile_id?: string
  debug?: boolean
}

export interface SearchDocument {
  id: string
  title: string
  filename: string
  kb_id: string
  kb_name: string
  version: number
  doc_type: string
  tags: string[]
  updated_at: string
}

export interface StageScores {
  dense: number | null
  bm25: number | null
  rrf: number
  rerank: number | null
}

export interface StageRanks {
  dense: number | null
  bm25: number | null
  rrf: number
  rerank: number | null
}

export interface SearchHit {
  rank: number
  chunk_id: string
  content: string
  /** HTML-escaped, matched terms wrapped in <em>. */
  snippet: string
  highlights: string[]
  title_html: string
  heading_path: string[]
  chunk_type: ChunkType
  page_start: number | null
  page_end: number | null
  sheet_name: string | null
  slide_number: number | null
  /** A published knowledge object entry (document.id = KO id). */
  is_ko: boolean
  document: SearchDocument
  scores: StageScores
  ranks: StageRanks
}

export interface AppliedFilters {
  kbs: { id: string; name: string }[]
  unresolved_kbs: string[]
  tags: string[]
  doc_types: string[]
  date_from: string | null
  date_to: string | null
}

export interface SearchDebug {
  config: RetrievalConfig
  stages: Record<string, unknown>
  timings: Record<string, number>
}

export interface SearchResponse {
  query: string
  normalized_query: string
  exact_terms: string[]
  ignored_operators: string[]
  filters: AppliedFilters
  items: SearchHit[]
  total: number
  took_ms: number
  trace_id: string | null
  profile: { id: string | null; name: string }
  degraded: string[]
  cache_hit: boolean
  debug: SearchDebug | null
}

export interface SearchOptions {
  doc_types: string[]
  tags: string[]
  can_debug: boolean
}

export interface RetrievalConfig {
  dense: {
    enabled: boolean
    top_k: number
    query_instruction: string
    hnsw_ef: number | null
    score_threshold: number | null
    timeout_seconds: number
  }
  sparse: {
    enabled: boolean
    top_k: number
    field_boosts: Record<string, number>
    phrase_boost: number
    minimum_should_match: string | null
    fragment_size: number
    timeout_seconds: number
  }
  fusion: { k: number; weights: Partial<Record<SearchRoute, number>> }
  rerank: {
    enabled: boolean
    top_n: number
    batch_size: number
    concurrency: number
    timeout_seconds: number
    max_chars: number
  }
  cache: { embedding_ttl_seconds: number; result_ttl_seconds: number }
  top_k: number
}

export interface RetrievalProfile {
  id: string | null
  name: string
  description: string | null
  config: RetrievalConfig
  is_active: boolean
  builtin: boolean
  created_at: string | null
  updated_at: string | null
}

export interface RetrievalProfileCreate {
  name: string
  description?: string | null
  config?: RetrievalConfig
}

export type RetrievalProfileUpdate = Partial<RetrievalProfileCreate>

export interface RetrievalTraceSummary {
  id: string
  user_id: string | null
  query: string
  profile_name: string
  generation: number | null
  cache_hit: boolean
  degraded: string[]
  result_count: number
  total_ms: number
  truncated: boolean
  created_at: string
}

export interface RetrievalTrace extends RetrievalTraceSummary {
  normalized_query: string
  filters: Record<string, unknown>
  profile_id: string | null
  config: Record<string, unknown>
  principals_hash: string
  timings: Record<string, number>
  stages: Record<string, unknown>
}

export interface RetrievalTraceQuery extends PageParams {
  user_id?: string
  keyword?: string
  degraded_only?: boolean
}

// ---- chat (mirrors backend app/schemas/chat.py) -----------------------------

export type MessageRole = 'user' | 'assistant'
export type MessageStatus = 'streaming' | 'done' | 'error'
export type Grounding =
  'grounded' | 'uncertain' | 'low_grounding' | 'no_evidence' | 'chitchat' | 'out_of_scope'
export type FeedbackRating = 'up' | 'down'
export type FeedbackReason = 'inaccurate' | 'incomplete' | 'outdated' | 'not_found'

export interface Conversation {
  id: string
  title: string
  kb_ids: string[]
  created_at: string
  updated_at: string
}

export interface ConversationCreate {
  title?: string | null
  kb_ids?: string[]
}

export interface ConversationUpdate {
  title?: string | null
  kb_ids?: string[] | null
}

export interface Citation {
  n: number
  document_id: string
  chunk_id: string
  chunk_ids: string[]
  hit_chunk_ids: string[]
  title: string
  filename: string | null
  kb_id: string | null
  kb_name: string | null
  doc_version: number | null
  heading_path: string[]
  page_start: number | null
  page_end: number | null
  sheet_name: string | null
  slide_number: number | null
  quote: string
  score: number | null
  /** Cites a knowledge object: document_id = KO id, doc_version = its published version. */
  is_ko?: boolean
  ko_type?: KoType | null
}

export interface MessageFeedback {
  rating: FeedbackRating
  reasons: FeedbackReason[]
  comment: string | null
  updated_at: string
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  status: MessageStatus
  intent: string | null
  rewritten_query: string | null
  grounding: Grounding | null
  citations: Citation[]
  trace_id: string | null
  error: string | null
  created_at: string
  feedback: MessageFeedback | null
  knowledge_requested: boolean
  steps: ChatStep[]
}

export type ChatStepName = 'rewrite' | 'retrieve' | 'evidence' | 'generate'
export type ChatStepStatus = 'running' | 'done' | 'failed'

/** Pipeline progress for the "thinking" panel; no model reasoning, only stage + timings. */
export interface ChatStep {
  step: ChatStepName
  status: ChatStepStatus
  ms?: number
  detail?: Record<string, unknown>
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[]
}

export interface AskBody {
  content: string
  kb_ids?: string[] | null
}

export interface FeedbackBody {
  rating: FeedbackRating
  reasons?: FeedbackReason[]
  comment?: string | null
}

export interface KnowledgeGap {
  id: string
  gap_type: string
  status: string
  query: string
  rewritten_query: string | null
  kb_ids: string[]
  kb_id: string | null
  top_score: number | null
  description: string | null
  message_id: string | null
  created_at: string
}

export interface KoSourceRef {
  document_id: string
  title: string
  chunk_id: string | null
  heading_path: string[]
  quote: string | null
}

export interface KoCitation {
  id: string
  ko_type: KoType
  question: string
  variants: string[]
  answer: string
  sources: KoSourceRef[]
  effective_from: string | null
  effective_to: string | null
}

export interface CitationSource {
  n: number
  document: {
    id: string
    title: string
    filename: string
    kb_id: string
    kb_name: string
    version: number
  }
  outdated: boolean
  heading_path: string[]
  page_start: number | null
  page_end: number | null
  anchor_chunk_id: string
  quote: string
  segments: { chunk_id: string; content: string; highlight: boolean }[]
  is_ko?: boolean
  ko?: KoCitation | null
}

/** Server-sent events of POST /chat/conversations/{id}/messages. */
export interface ChatMetaEvent {
  conversation_id: string
  title: string
  kb_ids: string[]
  user_message_id: string
  message_id: string
  trace_id: string
}

export interface ChatDoneEvent {
  message_id: string
  conversation_id: string
  answer: string
  grounding: Grounding
  intent: string | null
  rewritten_query: string | null
  trace_id: string
  gap_id: string | null
}

export interface ChatErrorEvent {
  code: string
  message: string
  message_id: string | null
  trace_id: string | null
}

// ---- knowledge loop (mirrors backend app/schemas/curation.py) ----------------

export type GapType = 'no_evidence' | 'low_grounding' | 'negative_feedback' | 'user_request'
export type GapStatus = 'open' | 'in_review' | 'resolved' | 'rejected' | 'duplicate'
export type GapSort = 'frequency' | 'recent'
export type KoType = 'faq' | 'qa' | 'card' | 'policy_summary'
export type KoStatus = 'draft' | 'pending_review' | 'published' | 'deprecated'
export type KoOrigin = 'manual' | 'gap' | 'document'
export type KoVersionStatus =
  'pending_review' | 'published' | 'rejected' | 'withdrawn' | 'superseded' | 'deprecated'
export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'cancelled'
export type ConflictVerdict = 'conflict' | 'duplicate' | 'consistent' | 'unrelated' | 'unknown'

export interface UserRef {
  id: string
  name: string
}

export interface Gap {
  id: string
  gap_type: GapType
  status: GapStatus
  query: string
  rewritten_query: string | null
  description: string | null
  kb_id: string | null
  kb_name: string | null
  cluster_id: string | null
  occurrences: number
  cluster_occurrences: number | null
  cluster_size: number | null
  top_score: number | null
  assignee: UserRef | null
  user_id: string | null
  conversation_id: string | null
  message_id: string | null
  trace_id: string | null
  duplicate_of_id: string | null
  resolution: Record<string, unknown>
  resolved_at: string | null
  created_at: string
  last_seen_at: string
}

export interface GapCluster {
  id: string
  kb_id: string | null
  representative_query: string
  gap_count: number
  occurrences: number
  open_count: number
  sources: Record<string, number>
  last_seen_at: string
}

export interface GapStats {
  by_status: Record<string, number>
  by_source: Record<string, number>
  clusters_open: number
}

export interface GapConversationMessage {
  id: string
  role: MessageRole
  content: string
  grounding: Grounding | null
  citations: Record<string, unknown>[]
  created_at: string
  redacted: boolean
  is_gap_message: boolean
}

export interface GapKoRef {
  id: string
  title: string
  status: KoStatus
  published_version: number | null
}

export interface GapDetail extends Gap {
  conversation: GapConversationMessage[]
  qa_trace: Record<string, unknown> | null
  cluster: GapCluster | null
  similar: Gap[]
  knowledge_objects: GapKoRef[]
}

export interface GapQuery extends PageParams {
  status?: GapStatus[]
  gap_type?: GapType
  kb_id?: string
  cluster_id?: string
  assignee_id?: string
  keyword?: string
  sort?: GapSort
}

export interface GapPatch {
  assignee_id?: string | null
  kb_id?: string | null
}

export interface GapDraftBody {
  kb_id?: string | null
  ko_type?: KoType
  document_ids?: string[]
  notes?: string | null
}

export interface ClusterRunResult {
  processed: number
  clustered: number
  new_clusters: number
  folded: number
}

export interface KoSourceIn {
  document_id: string
  chunk_id?: string | null
  quote?: string | null
}

export interface KoSource {
  document_id: string
  chunk_id: string | null
  title: string
  heading_path: string[]
  quote: string | null
  doc_version: number | null
  available: boolean
}

export interface KoFields {
  title?: string | null
  question: string
  variants: string[]
  answer: string
  sources: KoSourceIn[]
  effective_from?: string | null
  effective_to?: string | null
  owner_id?: string | null
  ko_type: KoType
}

export interface KoCreate extends KoFields {
  kb_id: string
  gap_ids?: string[]
}

export type KoUpdate = KoFields

export interface Conflict {
  kind: 'ko' | 'document'
  id: string
  chunk_id: string | null
  title: string
  version: number | null
  score: number | null
  verdict: ConflictVerdict
  reason: string
  excerpt: string
}

export interface KnowledgeObject {
  id: string
  kb_id: string
  kb_name: string | null
  ko_type: KoType
  title: string
  question: string
  variants: string[]
  status: KoStatus
  version: number
  published_version: number | null
  origin: KoOrigin
  owner: UserRef | null
  effective_from: string | null
  effective_to: string | null
  conflict_count: number
  published_at: string | null
  created_at: string
  updated_at: string
}

export interface ReviewTask {
  id: string
  ko_id: string
  ko_title: string | null
  kb_id: string | null
  ko_version: number
  status: ReviewStatus
  submitted_by: UserRef | null
  note: string | null
  reviewer: UserRef | null
  comment: string | null
  decided_at: string | null
  conflicts: Conflict[]
  created_at: string
}

export interface KoDraftMaterial {
  n: number
  title: string
  quote: string
  document_id?: string
  chunk_id?: string | null
  heading_path?: string[]
}

export interface KoAiDraft {
  title?: string
  question?: string
  variants?: string[]
  answer?: string
  sources?: KoSourceIn[]
  citations?: number[]
  method?: 'llm' | 'fallback'
  error?: string | null
  materials?: KoDraftMaterial[]
  similar?: string[]
  gap_id?: string
  document_id?: string
}

export interface KnowledgeObjectDetail extends KnowledgeObject {
  answer: string
  sources: KoSource[]
  acl_inherit: boolean
  gap_ids: string[]
  ai_draft: KoAiDraft
  conflicts: Conflict[]
  conflicts_checked_at: string | null
  pending_review: ReviewTask | null
  reviews: ReviewTask[]
  can_edit: boolean
  can_review: boolean
}

export interface KoVersion {
  id: string
  ko_id: string
  version: number
  ko_type: KoType
  title: string
  question: string
  variants: string[]
  answer: string
  sources: Record<string, unknown>[]
  effective_from: string | null
  effective_to: string | null
  status: KoVersionStatus
  note: string | null
  created_by: UserRef | null
  created_at: string
  published_at: string | null
  published_by: UserRef | null
}

export interface KoQuery extends PageParams {
  kb_id?: string
  status?: KoStatus
  ko_type?: KoType
  owner_id?: string
  keyword?: string
}

export interface ReviewTaskQuery extends PageParams {
  status?: ReviewStatus | null
}

export interface Notification {
  id: string
  kind: string
  title: string
  body: string | null
  resource_type: string | null
  resource_id: string | null
  link: string | null
  read_at: string | null
  created_at: string
}

// ---- analytics -------------------------------------------------------------

export interface NamedRef {
  id: string
  name: string
}

export interface AnalyticsFilters {
  orgs: NamedRef[]
  kbs: NamedRef[]
  org_id: string
  timezone: string
}

export interface AnalyticsQuery {
  org_id?: string
  kb_id?: string
  date_from?: string
  date_to?: string
}

export interface UsageSummary {
  questions: number
  active_users_avg: number
  active_users_peak: number
  knowledge_questions: number
  answered: number
}

export interface QualitySummary {
  feedback_up: number
  feedback_down: number
  like_rate: number | null
  refusal_rate: number | null
  low_grounding_rate: number | null
  avg_citations: number | null
  error_rate: number | null
  gaps_new: number
  gaps_resolved: number
}

export interface DailyPoint {
  day: string
  active_users: number
  questions: number
  grounded: number
  uncertain: number
  low_grounding: number
  no_evidence: number
  chitchat: number
  out_of_scope: number
  errors: number
  citations: number
  feedback_up: number
  feedback_down: number
  gaps_new: number
  gaps_resolved: number
  like_rate: number | null
  refusal_rate: number | null
  low_grounding_rate: number | null
  avg_citations: number | null
}

export type LatencyStage = 'retrieval' | 'rerank' | 'first_token' | 'total'

export interface LatencyStat {
  stage: LatencyStage
  count: number
  p50: number | null
  p95: number | null
  avg: number | null
}

export interface LatencyDaily {
  day: string
  stages: LatencyStat[]
}

export interface KbHeat {
  kb_id: string
  kb_name: string
  questions: number
  active_users_peak: number
  citations: number
  feedback_down: number
  gaps_new: number
}

export interface TopQuestion {
  query: string
  count: number
  unanswered: number
}

export interface AnalyticsOverview {
  org_id: string
  kb_id: string | null
  date_from: string
  date_to: string
  usage: UsageSummary
  quality: QualitySummary
  daily: DailyPoint[]
  latency: LatencyStat[]
  latency_daily: LatencyDaily[]
  kb_heat: KbHeat[]
  top_questions: TopQuestion[]
  refreshed_at: string | null
}

export interface ContentDocument {
  id: string
  title: string
  filename: string
  kb_id: string
  kb_name: string
  status: DocumentStatus
  created_at: string
  updated_at: string
  effective_to: string | null
  last_cited: string | null
  error_message: string | null
}

export interface ContentKo {
  id: string
  title: string
  kb_id: string
  kb_name: string
  effective_to: string | null
}

export interface AnalyticsContent {
  org_id: string
  kb_id: string | null
  knowledge_bases: number
  documents: number
  chunks: number
  published_kos: number
  document_status: { status: DocumentStatus; count: number }[]
  index: {
    outbox_pending: number
    outbox_processing: number
    outbox_dead: number
    oldest_pending_seconds: number | null
    failed_documents: ContentDocument[]
  }
  zombie_days: number
  zombie_total: number
  zombie_documents: ContentDocument[]
  expiring_days: number
  expired_documents: number
  expiring_documents: ContentDocument[]
  expiring_kos: ContentKo[]
}

export interface AnalyticsRefreshResult {
  days: string[]
  rows: number
}

export type LlmUsageKind = 'chat' | 'embedding' | 'rerank'

export interface LlmUsageTotals {
  calls: number
  errors: number
  estimated_calls: number
  fallback_calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  avg_latency_ms: number | null
}

export interface LlmUsageSummary extends LlmUsageTotals {
  users: number
}

export interface LlmUsageDaily {
  day: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface LlmUsageModel extends LlmUsageTotals {
  kind: LlmUsageKind
  model: string
}

export interface LlmUsageFeature extends LlmUsageTotals {
  feature: string
}

export interface LlmUsageUser extends LlmUsageTotals {
  user_id: string
  username: string | null
  display_name: string | null
  department: string | null
  is_service: boolean
  assistant_tokens: number
}

export interface LlmUsage {
  org_id: string
  user_id: string | null
  date_from: string
  date_to: string
  summary: LlmUsageSummary
  daily: LlmUsageDaily[]
  by_model: LlmUsageModel[]
  by_feature: LlmUsageFeature[]
  users: LlmUsageUser[]
  users_total: number
  refreshed_at: string | null
}

export type ModelKind = 'chat' | 'embedding' | 'rerank'
export type ModelScene = 'chat' | 'chat_fallback' | 'embedding' | 'rerank'

export interface ModelProvider {
  id: string
  name: string
  base_url: string
  has_api_key: boolean
  api_key_hint: string | null
  enabled: boolean
  source: string
  model_count: number
  in_use: boolean
  last_synced_at: string | null
  created_at: string
}

export interface ModelProviderInput {
  name?: string
  base_url?: string
  api_key?: string | null
  clear_api_key?: boolean
  enabled?: boolean
}

export interface ModelSyncResult {
  listed: number
  added: number
  missing: string[]
}

export interface ModelItem {
  id: string
  provider_id: string
  provider_name: string
  provider_enabled: boolean
  name: string
  kind: ModelKind
  origin: string
  base_url: string | null
  path: string | null
  effective_base_url: string
  detected_dim: number | null
  scenes: ModelScene[]
  last_check_status: 'ok' | 'error' | null
  last_check_at: string | null
  last_check_latency_ms: number | null
  last_check_message: string | null
}

export interface ModelInput {
  provider_id?: string
  name?: string
  kind?: ModelKind
  base_url?: string | null
  path?: string | null
}

export interface ModelCheckResult {
  ok: boolean
  latency_ms: number
  first_token_ms: number | null
  message: string
  sample: string | null
  dim: number | null
  warning: string | null
  checked_at: string
}

export interface ModelSceneInfo {
  scene: ModelScene
  kind: ModelKind
  model: string | null
  base_url: string | null
  provider_name: string | null
  model_id: string | null
  source: 'page' | 'config' | 'index'
  editable: boolean
  dim: number | null
  note: string | null
  last_check_status: 'ok' | 'error' | null
  last_check_at: string | null
}

export interface ModelOverview {
  scenes: ModelSceneInfo[]
  refresh_seconds: number
}

export interface ModelRoutesInput {
  chat_model_id: string | null
  chat_fallback_model_id?: string | null
  force?: boolean
}

export interface ModelCheckFailure {
  scene: ModelScene
  model: string
  message: string
}

// ---- onboarding guides (mirrors backend app/schemas/guide.py) ---------------------

export type GuideStatus = 'completed' | 'skipped'

export interface GuideProgress {
  guide_key: string
  version: number
  status: GuideStatus
  updated_at: string
}

export interface LlmUsageQuery {
  org_id?: string
  user_id?: string
  date_from?: string
  date_to?: string
}

// ---- evaluation ------------------------------------------------------------

export type EvalCaseSource = 'manual' | 'feedback' | 'gap'
export type EvalImportSource = 'feedback' | 'gap'
export type EvalRunStatus = 'pending' | 'running' | 'done' | 'failed'
export type EvalMetrics = Record<string, number | null>

export interface EvalDataset {
  id: string
  name: string
  description: string | null
  case_count: number
  created_by: string | null
  created_at: string
  updated_at: string
}

export interface EvalDatasetCreate {
  name: string
  description?: string | null
}

export interface EvalCaseFields {
  question: string
  reference_answer: string | null
  expected_document_ids: string[]
  expected_chunk_ids: string[]
  kb_ids: string[]
  tags: string[]
}

export interface EvalCase extends EvalCaseFields {
  id: string
  dataset_id: string
  source: EvalCaseSource
  source_id: string | null
  created_at: string
  updated_at: string
}

export interface EvalCandidate {
  source: EvalImportSource
  source_id: string
  question: string
  reference_answer: string | null
  expected_document_ids: string[]
  expected_chunk_ids: string[]
  kb_ids: string[]
  created_at: string
  imported: boolean
}

export interface EvalCandidateQuery extends PageParams {
  source: EvalImportSource
  dataset_id?: string
  keyword?: string
}

export interface EvalImportResult {
  created: number
  skipped: number
}

export interface EvalRunCreate {
  dataset_id: string
  profile_id: string
  name?: string | null
  judge_enabled: boolean
}

export interface EvalRun {
  id: string
  dataset_id: string
  dataset_name: string
  name: string | null
  profile_id: string | null
  profile_name: string
  config: Record<string, unknown>
  environment: Record<string, unknown>
  judge_enabled: boolean
  status: EvalRunStatus
  case_count: number
  done_count: number
  metrics: EvalMetrics
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_by: string | null
  created_at: string
}

export interface EvalRetrievedItem {
  rank: number
  chunk_id: string
  document_id: string
  title: string
  score: number | null
  is_ko: boolean
  relevant: boolean
}

export interface EvalResult {
  id: string
  run_id: string
  case_id: string
  question: string
  reference_answer: string | null
  expected_document_ids: string[]
  retrieved: EvalRetrievedItem[]
  metrics: EvalMetrics
  answer: string | null
  citations: Record<string, unknown>[]
  grounding: Grounding | null
  judge: Record<string, unknown>
  latency_ms: number
  error: string | null
}

export interface EvalCompare {
  runs: EvalRun[]
  metric_keys: string[]
  config_diff: { key: string; values: Record<string, unknown> }[]
  cases: { case_id: string; question: string; metrics: Record<string, EvalMetrics> }[]
}

// ---- open platform (mirrors backend app/schemas/open_api.py) -------------------

export type ApiScope = 'retrieve' | 'chat' | 'mcp'
export type ApiPrincipalType = 'dept' | 'group' | 'role'
export type ApiClientStatus = 'active' | 'disabled'

export interface ApiPrincipalRef {
  type: ApiPrincipalType
  id: string
}

export interface ApiPrincipal extends ApiPrincipalRef {
  name: string | null
}

export interface ApiClientBody {
  name: string
  description?: string | null
  owner_department_id?: string | null
  contact?: string | null
  kb_ids: string[]
  principals: ApiPrincipalRef[]
  scopes: ApiScope[]
  rate_limit_per_minute?: number
  daily_quota?: number
  ip_allowlist?: string[]
  expires_at?: string | null
}

export interface ApiClientUpdate extends Partial<ApiClientBody> {
  status?: ApiClientStatus
  clear_expires_at?: boolean
}

export interface ApiClient {
  id: string
  name: string
  description: string | null
  owner_department_id: string | null
  owner_department_name: string | null
  contact: string | null
  status: ApiClientStatus
  service_user_id: string
  kbs: NamedRef[]
  principals: ApiPrincipal[]
  scopes: ApiScope[]
  rate_limit_per_minute: number
  effective_rate_per_minute: number
  daily_quota: number
  ip_allowlist: string[]
  expires_at: string | null
  last_used_at: string | null
  created_at: string
  updated_at: string
  active_keys: number
  calls_today: number
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  status: 'active' | 'revoked'
  expires_at: string | null
  last_used_at: string | null
  last_used_ip: string | null
  created_at: string
  revoked_at: string | null
}

export interface ApiKeyCreated extends ApiKey {
  secret: string
}

export interface ApiCallLog {
  id: string
  key_id: string | null
  endpoint: string
  status_code: number
  error_code: string | null
  latency_ms: number
  ip: string | null
  query: string | null
  kb_ids: string[]
  result_count: number
  document_ids: string[]
  trace_id: string | null
  created_at: string
}

export interface ApiUsage {
  days: { day: string; calls: number; errors: number; avg_latency_ms: number }[]
  total_calls: number
  total_errors: number
  by_endpoint: Record<string, number>
  by_status: Record<string, number>
}

export interface OpenApiOptions {
  kbs: NamedRef[]
  departments: NamedRef[]
  groups: NamedRef[]
  roles: NamedRef[]
  scopes: ApiScope[]
  default_rate_per_minute: number
  max_top_k: number
}

export interface OpenChunk {
  rank: number
  chunk_id: string
  document_id: string
  title: string
  kb_id: string
  kb_name: string
  heading_path: string[]
  content: string
  score: number | null
  page_start: number | null
  page_end: number | null
  is_ko: boolean
}

export interface OpenRetrieveResult {
  query: string
  kb_ids: string[]
  items: OpenChunk[]
  total: number
  trace_id: string | null
  took_ms: number
}

// ---- organization directory sync ------------------------------------------------

export type SyncMode = 'preview' | 'apply'
export type SyncStatus = 'running' | 'succeeded' | 'failed' | 'aborted'

export interface DirectorySource {
  id: string
  type: DirectorySourceType
  name: string
  is_primary: boolean
  enabled: boolean
  sync_interval_minutes: number
  config: Record<string, unknown>
  secrets_set: string[]
  login_supported: boolean
  login_configured: boolean
  last_sync_at: string | null
  last_status: SyncStatus | null
  last_run_id: string | null
  next_sync_at: string | null
  created_at: string
  updated_at: string
}

export interface DirectorySourceBody {
  type: DirectorySourceType
  name: string
  is_primary: boolean
  enabled: boolean
  sync_interval_minutes: number
  config: Record<string, unknown>
}

export type DirectorySourceUpdate = Partial<Omit<DirectorySourceBody, 'type'>>

export interface DirectoryTestResult {
  ok: boolean
  departments: number
  users: number
  active_users: number
  warnings: string[]
  error: string | null
  duration_ms: number
}

export interface SyncStats {
  departments?: Record<string, number>
  users?: Record<string, number>
  identities?: Record<string, number>
}

export interface SyncRun {
  id: string
  source_id: string
  mode: SyncMode
  status: SyncStatus
  forced: boolean
  stats: {
    stats?: SyncStats
    warnings?: string[]
    aborted?: boolean
    abort_reason?: string | null
    error_detail?: unknown
  }
  error: string | null
  triggered_by: string | null
  started_at: string
  finished_at: string | null
  duration_ms: number
}

export interface SyncChange {
  action: string
  changes?: string[]
  name?: string | null
  path?: string
  username?: string | null
  employee_no?: string | null
  title?: string | null
  match?: string | null
  external_id?: string | null
  before?: string | null
  mobile?: string | null
  email?: string | null
}

export interface SyncRunDetail extends SyncRun {
  changes: Record<string, SyncChange[]>
}
