<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ChatLineRound,
  CopyDocument,
  Delete,
  EditPen,
  Expand,
  Fold,
  MoreFilled,
  Plus,
  Position,
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import {
  askQuestion,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  requestKnowledge,
  sendFeedback,
  updateConversation,
} from '@/api/chat'
import { HttpError } from '@/api/http'
import { listKnowledgeBases } from '@/api/knowledge'
import type {
  ChatMessage,
  ChatStep,
  Citation,
  Conversation,
  FeedbackReason,
  KnowledgeBase,
} from '@/api/types'
import AnswerContent from '@/components/assistant/AnswerContent.vue'
import CitationDrawer from '@/components/assistant/CitationDrawer.vue'
import FeedbackDialog from '@/components/assistant/FeedbackDialog.vue'
import ThinkingSteps from '@/components/assistant/ThinkingSteps.vue'
import AppLogo from '@/components/layout/AppLogo.vue'
import { formatDateTime } from '@/utils/format'
import { hitLocation } from '@/utils/search'

/** `key` stays fixed for the row's lifetime; `id` changes from a draft id to the server id. */
type UiMessage = ChatMessage & { key: string }

const STICK_THRESHOLD = 80

const conversations = ref<Conversation[]>([])
const listLoading = ref(false)
const convKeyword = ref('')
const sidebarCollapsed = ref(false)
const activeId = ref<string | null>(null)
const messages = ref<UiMessage[]>([])
const detailLoading = ref(false)

const input = ref('')
const kbIds = ref<string[]>([])
const kbOptions = ref<KnowledgeBase[]>([])
const kbLoading = ref(false)

const streaming = ref(false)
let controller: AbortController | null = null
const scroller = ref<HTMLElement>()
const atBottom = ref(true)
const composer = ref<{ focus: () => void }>()

const active = computed(() => conversations.value.find((c) => c.id === activeId.value) ?? null)
const canSend = computed(() => !!input.value.trim() && !streaming.value)
const lastAssistant = computed(() =>
  [...messages.value].reverse().find((m) => m.role === 'assistant'),
)

// ---- conversations ---------------------------------------------------------------

async function loadConversations(): Promise<void> {
  listLoading.value = true
  try {
    conversations.value = (await listConversations({ page: 1, size: 100 })).items
  } finally {
    listLoading.value = false
  }
}

const groupedConversations = computed(() => {
  const keyword = convKeyword.value.trim().toLowerCase()
  const items = keyword
    ? conversations.value.filter((c) => c.title.toLowerCase().includes(keyword))
    : conversations.value
  const startOfToday = new Date()
  startOfToday.setHours(0, 0, 0, 0)
  const day = 86_400_000
  const groups: { label: string; items: Conversation[] }[] = [
    { label: '今天', items: [] },
    { label: '昨天', items: [] },
    { label: '近 7 天', items: [] },
    { label: '更早', items: [] },
  ]
  for (const conv of items) {
    const t = new Date(conv.updated_at).getTime()
    const idx =
      t >= startOfToday.getTime()
        ? 0
        : t >= startOfToday.getTime() - day
          ? 1
          : t >= startOfToday.getTime() - 6 * day
            ? 2
            : 3
    groups[idx].items.push(conv)
  }
  return groups.filter((g) => g.items.length)
})

function toUi(message: ChatMessage): UiMessage {
  return { ...message, steps: message.steps ?? [], key: message.id }
}

async function openConversation(id: string): Promise<void> {
  if (streaming.value || id === activeId.value) return
  activeId.value = id
  detailLoading.value = true
  try {
    const detail = await getConversation(id)
    messages.value = detail.messages.map(toUi)
    kbIds.value = [...detail.kb_ids]
    await ensureKbOptions(detail.kb_ids)
    scrollToBottom(true)
  } finally {
    detailLoading.value = false
  }
}

function newConversation(): void {
  if (streaming.value) return
  activeId.value = null
  messages.value = []
  void nextTick(() => composer.value?.focus())
}

async function renameConversation(conv: Conversation): Promise<void> {
  const { value } = await ElMessageBox.prompt('会话名称', '重命名', {
    inputValue: conv.title,
    inputValidator: (v) => (!!v.trim() && v.length <= 200) || '请输入 1-200 个字符',
  })
  const updated = await updateConversation(conv.id, { title: value.trim() })
  conv.title = updated.title
}

async function removeConversation(conv: Conversation): Promise<void> {
  await ElMessageBox.confirm(`确定删除会话「${conv.title}」？`, '删除会话', { type: 'warning' })
  await deleteConversation(conv.id)
  conversations.value = conversations.value.filter((c) => c.id !== conv.id)
  if (activeId.value === conv.id) newConversation()
}

function onConversationCommand(conv: Conversation, command: string): void {
  const action = command === 'rename' ? renameConversation : removeConversation
  // Dialog cancellation rejects; nothing to do then.
  action(conv).catch(() => undefined)
}

// ---- knowledge base scope ----------------------------------------------------------

async function loadKbs(keyword = ''): Promise<void> {
  kbLoading.value = true
  try {
    const page = await listKnowledgeBases({ page: 1, size: 50, keyword: keyword || undefined })
    const selected = kbOptions.value.filter((kb) => kbIds.value.includes(kb.id))
    const ids = new Set(page.items.map((kb) => kb.id))
    kbOptions.value = [...page.items, ...selected.filter((kb) => !ids.has(kb.id))]
  } finally {
    kbLoading.value = false
  }
}

async function ensureKbOptions(ids: string[]): Promise<void> {
  const known = new Set(kbOptions.value.map((kb) => kb.id))
  if (ids.some((id) => !known.has(id))) await loadKbs()
}

async function onScopeChange(): Promise<void> {
  const conv = active.value
  if (!conv || streaming.value) return
  const updated = await updateConversation(conv.id, { kb_ids: kbIds.value })
  conv.kb_ids = updated.kb_ids
}

const suggestions = computed(() => {
  const named = kbOptions.value.slice(0, 2).map((kb) => `「${kb.name}」里主要有哪些内容？`)
  return [...named, '帮我总结一下最新的制度变化', '有哪些需要注意的审批流程？'].slice(0, 4)
})

// ---- scrolling ---------------------------------------------------------------------

function onScroll(): void {
  const el = scroller.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD
}

/** Follows new content only while the reader is at the bottom, unless forced. */
function scrollToBottom(force = false, smooth = false): void {
  if (!force && !atBottom.value) return
  void nextTick(() => {
    const el = scroller.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    atBottom.value = true
  })
}

// ---- asking ------------------------------------------------------------------------

let draftSeq = 0

function draftMessage(role: ChatMessage['role'], content: string): UiMessage {
  const key = `local-${role}-${Date.now()}-${++draftSeq}`
  return {
    key,
    id: key,
    role,
    content,
    status: role === 'user' ? 'done' : 'streaming',
    intent: null,
    rewritten_query: null,
    grounding: null,
    citations: [],
    trace_id: null,
    error: null,
    created_at: new Date().toISOString(),
    feedback: null,
    knowledge_requested: false,
    steps: [],
  }
}

async function ensureConversation(): Promise<Conversation> {
  if (active.value) return active.value
  const conv = await createConversation({ kb_ids: kbIds.value })
  conversations.value.unshift(conv)
  activeId.value = conv.id
  return conv
}

function touch(conv: Conversation, title?: string): void {
  if (title) conv.title = title
  conv.updated_at = new Date().toISOString()
  conversations.value = [conv, ...conversations.value.filter((c) => c.id !== conv.id)]
}

function upsertStep(reply: UiMessage, step: ChatStep): void {
  const idx = reply.steps.findIndex((s) => s.step === step.step)
  if (idx >= 0) reply.steps.splice(idx, 1, step)
  else reply.steps.push(step)
}

async function send(text?: string): Promise<void> {
  const content = (text ?? input.value).trim()
  if (!content || streaming.value) return
  streaming.value = true
  let answer: UiMessage | null = null
  try {
    const conv = await ensureConversation()
    if (text === undefined) input.value = ''
    messages.value.push(draftMessage('user', content), draftMessage('assistant', ''))
    // Mutate through the reactive array so the UI follows the stream.
    const question = messages.value[messages.value.length - 2]
    const reply = (answer = messages.value[messages.value.length - 1])
    scrollToBottom(true, true)
    controller = new AbortController()
    await askQuestion(
      conv.id,
      { content, kb_ids: kbIds.value },
      {
        onMeta: (meta) => {
          question.id = meta.user_message_id
          reply.id = meta.message_id
          reply.trace_id = meta.trace_id
          conv.kb_ids = meta.kb_ids
          touch(conv, meta.title)
        },
        onStep: (step) => {
          upsertStep(reply, step)
          scrollToBottom()
        },
        onToken: (chunk) => {
          reply.content += chunk
          scrollToBottom()
        },
        onCitations: (citations) => {
          reply.citations = citations
        },
        onDone: (done) => {
          reply.content = done.answer
          reply.grounding = done.grounding
          reply.intent = done.intent
          reply.rewritten_query = done.rewritten_query
          reply.status = 'done'
          scrollToBottom()
        },
        onError: (err) => {
          reply.status = 'error'
          reply.error = err.message
          const suffix = err.trace_id ? `（trace: ${err.trace_id}）` : ''
          ElMessage.error(`${err.message}${suffix}`)
        },
      },
      controller.signal,
    )
    if (reply.status === 'streaming') {
      reply.status = 'error'
      reply.error = '回答中断，请重试'
    }
  } catch (err) {
    if (answer) {
      const aborted = err instanceof DOMException && err.name === 'AbortError'
      answer.status = 'error'
      answer.error = aborted ? '已停止生成' : '回答失败'
      for (const step of answer.steps) if (step.status === 'running') step.status = 'failed'
    }
    if (err instanceof HttpError) ElMessage.error(err.message)
  } finally {
    controller = null
    streaming.value = false
  }
}

function regenerate(message: UiMessage): void {
  const idx = messages.value.findIndex((m) => m.key === message.key)
  const question = messages.value
    .slice(0, idx)
    .reverse()
    .find((m) => m.role === 'user')
  if (question) void send(question.content)
}

function stop(): void {
  controller?.abort()
}

function onInputKeydown(event: Event | KeyboardEvent): void {
  if (!(event instanceof KeyboardEvent)) return
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void send()
  }
}

async function copyAnswer(message: UiMessage): Promise<void> {
  try {
    await navigator.clipboard.writeText(message.content)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

// ---- citations, feedback, knowledge requests ----------------------------------------

const drawer = ref(false)
const drawerMessage = ref<string | null>(null)
const drawerCitation = ref<Citation | null>(null)

function openCitation(message: UiMessage, n: number): void {
  const citation = message.citations.find((c) => c.n === n)
  if (!citation || message.status !== 'done') return
  drawerMessage.value = message.id
  drawerCitation.value = citation
  drawer.value = true
}

const feedbackDialog = ref(false)
const feedbackTarget = ref<UiMessage | null>(null)
const feedbackSaving = ref(false)

async function rateUp(message: UiMessage): Promise<void> {
  if (message.feedback?.rating === 'up') return
  message.feedback = await sendFeedback(message.id, { rating: 'up' })
  ElMessage.success('感谢反馈')
}

function rateDown(message: UiMessage): void {
  feedbackTarget.value = message
  feedbackDialog.value = true
}

async function submitFeedback(value: { reasons: FeedbackReason[]; comment: string }) {
  const message = feedbackTarget.value
  if (!message) return
  feedbackSaving.value = true
  try {
    message.feedback = await sendFeedback(message.id, {
      rating: 'down',
      reasons: value.reasons,
      comment: value.comment || null,
    })
    feedbackDialog.value = false
    ElMessage.success('感谢反馈，我们会持续改进')
  } finally {
    feedbackSaving.value = false
  }
}

async function submitKnowledgeRequest(message: UiMessage): Promise<void> {
  let description = ''
  try {
    const { value } = await ElMessageBox.prompt(
      '请描述你需要的资料，知识管理员会据此补充（可选）',
      '提交知识需求',
      { inputType: 'textarea', inputPlaceholder: '例如：需要最新的差旅报销标准文件' },
    )
    description = value?.trim() ?? ''
  } catch {
    return
  }
  await requestKnowledge(message.id, description)
  message.knowledge_requested = true
  ElMessage.success('已提交知识需求')
}

function needsKnowledge(message: UiMessage): boolean {
  return message.grounding === 'no_evidence' || message.grounding === 'low_grounding'
}

function citationLocation(c: Citation): string {
  return hitLocation(c)
}

// ---- lifecycle ---------------------------------------------------------------------

onMounted(async () => {
  try {
    await Promise.all([loadConversations(), loadKbs()])
    const first = conversations.value[0]
    if (first) await openConversation(first.id)
  } catch {
    // Already reported by the http interceptor.
  }
})

onBeforeUnmount(stop)
</script>

<template>
  <div class="assistant" :class="{ 'assistant--collapsed': sidebarCollapsed }">
    <aside class="side">
      <div class="side__top">
        <el-button
          type="primary"
          :icon="Plus"
          class="side__new"
          data-guide="assistant-new"
          @click="newConversation"
        >
          新建对话
        </el-button>
        <el-input
          v-model="convKeyword"
          :prefix-icon="Search"
          placeholder="搜索会话"
          clearable
          class="side__search"
        />
      </div>
      <el-scrollbar v-loading="listLoading" class="side__list" data-guide="assistant-history">
        <el-empty
          v-if="!groupedConversations.length"
          :image-size="56"
          :description="convKeyword ? '没有匹配的会话' : '暂无会话'"
        />
        <div v-for="group in groupedConversations" :key="group.label" class="side__group">
          <div class="side__group-label">{{ group.label }}</div>
          <div
            v-for="conv in group.items"
            :key="conv.id"
            class="conv"
            :class="{ active: conv.id === activeId }"
            role="button"
            tabindex="0"
            data-test="conversation"
            @click="openConversation(conv.id)"
            @keyup.enter="openConversation(conv.id)"
          >
            <el-icon class="conv__icon"><ChatLineRound /></el-icon>
            <span class="conv__title" :title="conv.title">{{ conv.title }}</span>
            <el-dropdown
              trigger="click"
              @command="(cmd: string) => onConversationCommand(conv, cmd)"
              @click.stop
            >
              <button type="button" class="conv__more" @click.stop>
                <el-icon><MoreFilled /></el-icon>
              </button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename" :icon="EditPen">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" :icon="Delete">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </el-scrollbar>
    </aside>

    <section class="chat">
      <header class="chat__header">
        <button
          type="button"
          class="icon-btn"
          :title="sidebarCollapsed ? '展开会话列表' : '收起会话列表'"
          @click="sidebarCollapsed = !sidebarCollapsed"
        >
          <el-icon><Expand v-if="sidebarCollapsed" /><Fold v-else /></el-icon>
        </button>
        <span class="chat__title">{{ active?.title ?? '新对话' }}</span>
        <span v-if="kbIds.length" class="chat__scope-tag">已限定 {{ kbIds.length }} 个知识库</span>
      </header>

      <div
        ref="scroller"
        v-loading="detailLoading"
        class="chat__scroll"
        data-test="chat-scroll"
        @scroll.passive="onScroll"
      >
        <div class="chat__column">
          <div v-if="!messages.length && !detailLoading" class="welcome">
            <AppLogo :size="56" collapsed />
            <h2 class="welcome__title">你好，我是知识库 AI 助手</h2>
            <p class="welcome__desc">
              回答只依据你有权访问的知识库资料，并逐句标注引用来源，可点击查看原文。
            </p>
            <div class="welcome__grid">
              <button
                v-for="q in suggestions"
                :key="q"
                type="button"
                class="welcome__card"
                @click="send(q)"
              >
                <span>{{ q }}</span>
                <el-icon><Position /></el-icon>
              </button>
            </div>
          </div>

          <div
            v-for="msg in messages"
            :key="msg.key"
            class="msg"
            :class="`msg--${msg.role}`"
            data-test="message"
          >
            <template v-if="msg.role === 'user'">
              <div class="msg__user">{{ msg.content }}</div>
            </template>

            <template v-else>
              <div class="msg__avatar"><AppLogo :size="28" collapsed /></div>
              <div class="msg__body">
                <ThinkingSteps :steps="msg.steps" :streaming="msg.status === 'streaming'" />

                <div v-if="msg.grounding === 'no_evidence'" class="notice notice--info">
                  <div class="notice__title">未找到可靠依据</div>
                  <div class="notice__text">{{ msg.content }}</div>
                </div>
                <template v-else>
                  <div
                    v-if="msg.status === 'streaming' && !msg.content && !msg.steps.length"
                    class="msg__pending"
                  >
                    <span /><span /><span />
                  </div>
                  <AnswerContent
                    v-else-if="msg.content"
                    :content="msg.content"
                    :citations="msg.citations"
                    :streaming="msg.status === 'streaming'"
                    @cite="(n) => openCitation(msg, n)"
                  />
                  <div v-if="msg.grounding === 'uncertain'" class="notice notice--warn">
                    相关资料有限，回答可能不完整，请结合引用原文核实
                  </div>
                  <div v-if="msg.grounding === 'low_grounding'" class="notice notice--warn">
                    该回答未能关联到可靠的引用来源，请谨慎参考
                  </div>
                </template>

                <div v-if="msg.status === 'error'" class="notice notice--error">
                  {{ msg.error || '回答失败，请重试' }}
                </div>

                <div v-if="msg.status === 'done' && msg.citations.length" class="sources">
                  <div class="sources__label">引用来源 · {{ msg.citations.length }}</div>
                  <div class="sources__list">
                    <button
                      v-for="c in msg.citations"
                      :key="c.n"
                      type="button"
                      class="source"
                      :title="c.quote"
                      @click="openCitation(msg, c.n)"
                    >
                      <span class="source__n">{{ c.n }}</span>
                      <span class="source__main">
                        <span class="source__title">
                          <el-tag v-if="c.is_ko" size="small" type="success" effect="plain">
                            知识条目
                          </el-tag>
                          {{ c.title }}
                        </span>
                        <span class="source__meta">
                          {{
                            [c.kb_name, c.heading_path.join(' › '), citationLocation(c)]
                              .filter(Boolean)
                              .join(' · ')
                          }}
                        </span>
                      </span>
                    </button>
                  </div>
                </div>

                <div v-if="msg.status !== 'streaming'" class="msg__actions">
                  <el-tooltip content="复制" placement="top">
                    <button
                      v-if="msg.content"
                      type="button"
                      class="icon-btn icon-btn--sm"
                      @click="copyAnswer(msg)"
                    >
                      <el-icon><CopyDocument /></el-icon>
                    </button>
                  </el-tooltip>
                  <el-tooltip
                    v-if="msg.key === lastAssistant?.key"
                    content="重新生成"
                    placement="top"
                  >
                    <button
                      type="button"
                      class="icon-btn icon-btn--sm"
                      :disabled="streaming"
                      data-test="regenerate"
                      @click="regenerate(msg)"
                    >
                      <el-icon><Refresh /></el-icon>
                    </button>
                  </el-tooltip>
                  <template v-if="msg.status === 'done'">
                    <span class="msg__sep" />
                    <button
                      type="button"
                      class="pill"
                      :class="{ 'pill--on': msg.feedback?.rating === 'up' }"
                      @click="rateUp(msg)"
                    >
                      有帮助
                    </button>
                    <button
                      type="button"
                      class="pill"
                      :class="{ 'pill--down': msg.feedback?.rating === 'down' }"
                      @click="rateDown(msg)"
                    >
                      没帮助
                    </button>
                    <template v-if="needsKnowledge(msg)">
                      <button
                        v-if="!msg.knowledge_requested"
                        type="button"
                        class="pill pill--primary"
                        @click="submitKnowledgeRequest(msg)"
                      >
                        提交知识需求
                      </button>
                      <span v-else class="msg__done-tag">已提交知识需求</span>
                    </template>
                  </template>
                  <span class="msg__time">{{ formatDateTime(msg.created_at) }}</span>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div class="chat__footer">
        <transition name="fade">
          <button
            v-if="!atBottom && messages.length"
            type="button"
            class="to-bottom"
            data-test="to-bottom"
            @click="scrollToBottom(true, true)"
          >
            <el-icon><ArrowDown /></el-icon>
            回到底部
          </button>
        </transition>
        <div
          class="composer"
          :class="{ 'composer--busy': streaming }"
          data-guide="assistant-composer"
        >
          <el-input
            ref="composer"
            v-model="input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 8 }"
            maxlength="4000"
            resize="none"
            placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
            class="composer__input"
            data-test="composer"
            @keydown="onInputKeydown"
          />
          <div class="composer__bar">
            <el-select
              v-model="kbIds"
              multiple
              filterable
              remote
              collapse-tags
              collapse-tags-tooltip
              clearable
              :remote-method="loadKbs"
              :loading="kbLoading"
              :disabled="streaming"
              placeholder="全部可访问的知识库"
              size="small"
              class="composer__scope"
              data-guide="assistant-scope"
              @change="onScopeChange"
            >
              <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
            </el-select>
            <span class="composer__count">{{ input.length }}/4000</span>
            <button
              v-if="streaming"
              type="button"
              class="send send--stop"
              title="停止生成"
              data-test="stop"
              @click="stop"
            >
              <span class="send__square" />
            </button>
            <button
              v-else
              type="button"
              class="send"
              :disabled="!canSend"
              title="发送"
              data-test="send"
              @click="send()"
            >
              <el-icon><Position /></el-icon>
            </button>
          </div>
        </div>
        <div class="chat__disclaimer">内容由 AI 基于知识库生成，请以引用原文为准</div>
      </div>
    </section>

    <CitationDrawer v-model="drawer" :message-id="drawerMessage" :citation="drawerCitation" />
    <FeedbackDialog
      v-model="feedbackDialog"
      :initial="feedbackTarget?.feedback ?? null"
      :submitting="feedbackSaving"
      @submit="submitFeedback"
    />
  </div>
</template>

<style scoped>
.assistant {
  --chat-col: 800px;
  display: flex;
  /* Fill the layout's scroll container exactly, so this page has one scroller (.chat__scroll). */
  height: calc(100% + 2 * var(--ekb-content-pad));
  min-height: 480px;
  margin: calc(-1 * var(--ekb-content-pad));
  background: var(--ekb-bg-panel);
  overflow: hidden;
}

/* ---- conversation list ---- */
.side {
  flex: none;
  display: flex;
  flex-direction: column;
  width: 260px;
  background: var(--ekb-bg-sider);
  border-right: 1px solid var(--ekb-border-soft);
  transition:
    width 0.2s ease,
    opacity 0.2s ease;
  overflow: hidden;
}
.assistant--collapsed .side {
  width: 0;
  opacity: 0;
  border-right: 0;
}
.side__top {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 12px 8px;
}
.side__new {
  width: 100%;
  height: 36px;
  border-radius: var(--ekb-radius);
}
.side__search {
  --el-input-bg-color: var(--ekb-bg-input);
  --el-input-border-color: transparent;
}
.side__list {
  flex: 1;
  min-height: 0;
  padding: 0 8px 12px;
}
.side__group-label {
  padding: 12px 8px 4px;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.conv {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 6px 0 10px;
  border-radius: var(--ekb-radius);
  color: var(--ekb-text-2);
  cursor: pointer;
  transition: background 0.15s;
}
.conv:hover {
  background: var(--ekb-bg-hover);
}
.conv.active {
  background: var(--ekb-primary-soft);
  color: var(--ekb-primary);
  font-weight: 500;
}
.conv__icon {
  flex: none;
  color: var(--ekb-text-3);
}
.conv.active .conv__icon {
  color: var(--ekb-primary);
}
.conv__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 14px;
}
.conv__more {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--ekb-text-3);
  cursor: pointer;
  visibility: hidden;
}
.conv__more:hover {
  background: var(--ekb-bg-fill-2);
}
.conv:hover .conv__more,
.conv.active .conv__more {
  visibility: visible;
}

/* ---- chat ---- */
.chat {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.chat__header {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 52px;
  padding: 0 16px;
  border-bottom: 1px solid var(--ekb-border-soft);
}
.chat__title {
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 15px;
  font-weight: 600;
  color: var(--ekb-text-1);
}
.chat__scope-tag {
  flex: none;
  padding: 1px 8px;
  font-size: 12px;
  color: var(--ekb-primary);
  background: var(--ekb-primary-soft);
  border-radius: 10px;
}
.chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-anchor: none;
  scrollbar-gutter: stable;
}
.chat__column {
  max-width: var(--chat-col);
  margin: 0 auto;
  padding: 24px 24px 16px;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: var(--ekb-radius-sm);
  background: transparent;
  color: var(--ekb-text-2);
  font-size: 16px;
  cursor: pointer;
}
.icon-btn:hover:not(:disabled) {
  background: var(--ekb-bg-hover);
  color: var(--ekb-text-1);
}
.icon-btn:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}
.icon-btn--sm {
  width: 28px;
  height: 28px;
  font-size: 14px;
}

/* ---- welcome ---- */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 9vh 0 24px;
  text-align: center;
}
.welcome__title {
  margin: 18px 0 8px;
  font-size: 24px;
  font-weight: 700;
  color: var(--ekb-text-1);
}
.welcome__desc {
  max-width: 480px;
  margin: 0 0 28px;
  color: var(--ekb-text-3);
  line-height: 1.7;
}
.welcome__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  width: 100%;
  max-width: 640px;
}
.welcome__card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  text-align: left;
  font-size: 14px;
  color: var(--ekb-text-2);
  background: var(--ekb-bg-panel);
  border: 1px solid var(--ekb-border);
  border-radius: var(--ekb-radius-lg);
  cursor: pointer;
  transition:
    border-color 0.15s,
    box-shadow 0.15s,
    color 0.15s;
}
.welcome__card:hover {
  color: var(--ekb-primary);
  border-color: var(--el-color-primary-light-5);
  box-shadow: var(--ekb-shadow);
}
.welcome__card .el-icon {
  flex: none;
  color: var(--ekb-text-3);
}

/* ---- messages ---- */
.msg {
  display: flex;
  gap: 12px;
  margin-bottom: 28px;
}
.msg--user {
  justify-content: flex-end;
}
.msg__user {
  max-width: 78%;
  padding: 10px 16px;
  font-size: 15px;
  line-height: 1.7;
  color: var(--ekb-text-1);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--ekb-bg-user-bubble);
  border-radius: 16px 16px 4px 16px;
}
.msg__avatar {
  flex: none;
  padding-top: 2px;
}
.msg__body {
  flex: 1;
  min-width: 0;
}
.msg__pending {
  display: inline-flex;
  gap: 5px;
  padding: 10px 0;
}
.msg__pending span {
  width: 7px;
  height: 7px;
  background: var(--el-color-primary-light-5);
  border-radius: 50%;
  animation: bounce 1.2s infinite ease-in-out;
}
.msg__pending span:nth-child(2) {
  animation-delay: 0.15s;
}
.msg__pending span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes bounce {
  0%,
  80%,
  100% {
    transform: scale(0.6);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
.msg__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  color: var(--ekb-text-3);
}
.msg__sep {
  width: 1px;
  height: 14px;
  margin: 0 6px;
  background: var(--ekb-border);
}
.msg__time {
  margin-left: auto;
  font-size: 12px;
  opacity: 0;
  transition: opacity 0.15s;
}
.msg:hover .msg__time {
  opacity: 1;
}
.msg__done-tag {
  font-size: 12px;
  color: var(--el-color-success);
}
.pill {
  height: 26px;
  padding: 0 10px;
  font-size: 12px;
  color: var(--ekb-text-2);
  background: transparent;
  border: 1px solid var(--ekb-border);
  border-radius: 13px;
  cursor: pointer;
}
.pill:hover {
  color: var(--ekb-primary);
  border-color: var(--el-color-primary-light-5);
}
.pill--on {
  color: var(--ekb-primary);
  background: var(--ekb-primary-soft);
  border-color: var(--el-color-primary-light-7);
}
.pill--down {
  color: var(--el-color-danger);
  background: var(--ekb-danger-bg);
  border-color: var(--ekb-danger-border);
}
.pill--primary {
  color: var(--ekb-primary);
  border-color: var(--el-color-primary-light-5);
}

.notice {
  margin-top: 10px;
  padding: 10px 14px;
  font-size: 13px;
  line-height: 1.6;
  border-radius: var(--ekb-radius);
}
.notice--info {
  color: var(--ekb-text-2);
  background: var(--ekb-bg-fill);
  border: 1px solid var(--ekb-border-soft);
}
.notice__title {
  margin-bottom: 4px;
  font-weight: 600;
  color: var(--ekb-text-1);
}
.notice__text {
  white-space: pre-wrap;
}
.notice--warn {
  color: var(--ekb-warning-text);
  background: var(--ekb-warning-bg);
}
.notice--error {
  color: var(--ekb-danger-text);
  background: var(--ekb-danger-bg);
}

/* ---- sources ---- */
.sources {
  margin-top: 14px;
}
.sources__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.sources__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 8px;
}
.source {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  text-align: left;
  background: var(--ekb-bg-subtle);
  border: 1px solid var(--ekb-border-soft);
  border-radius: var(--ekb-radius);
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.source:hover {
  background: var(--ekb-primary-softer);
  border-color: var(--el-color-primary-light-7);
}
.source__n {
  flex: none;
  width: 18px;
  height: 18px;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  color: var(--ekb-primary);
  background: var(--ekb-primary-soft);
  border-radius: 4px;
}
.source__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.source__title {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 13px;
  font-weight: 500;
  color: var(--ekb-text-1);
}
.source__meta {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  font-size: 12px;
  color: var(--ekb-text-3);
}

/* ---- composer ---- */
.chat__footer {
  position: relative;
  flex: none;
  width: 100%;
  max-width: calc(var(--chat-col) + 48px);
  margin: 0 auto;
  padding: 0 24px 12px;
}
.to-bottom {
  position: absolute;
  top: -48px;
  left: 50%;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 32px;
  padding: 0 14px;
  font-size: 13px;
  color: var(--ekb-text-2);
  background: var(--ekb-bg-overlay);
  border: 1px solid var(--ekb-border);
  border-radius: 16px;
  box-shadow: var(--ekb-shadow-lg);
  transform: translateX(-50%);
  cursor: pointer;
}
.to-bottom:hover {
  color: var(--ekb-primary);
}
.composer {
  padding: 10px 12px 8px;
  background: var(--ekb-bg-panel);
  border: 1px solid var(--ekb-border);
  border-radius: 16px;
  box-shadow: var(--ekb-shadow);
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}
.composer:focus-within {
  border-color: var(--el-color-primary-light-5);
  box-shadow: 0 4px 20px rgba(51, 112, 255, 0.12);
}
.composer__input :deep(.el-textarea__inner) {
  padding: 4px 4px;
  font-size: 15px;
  line-height: 1.6;
  box-shadow: none;
  background: transparent;
}
.composer__bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}
.composer__scope {
  width: 260px;
}
.composer__scope :deep(.el-select__wrapper) {
  background: var(--ekb-bg-fill);
  box-shadow: none;
  border-radius: 14px;
}
.composer__count {
  margin-left: auto;
  font-size: 12px;
  color: var(--ekb-text-3);
}
.send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  font-size: 16px;
  color: #fff;
  background: var(--ekb-gradient);
  border: 0;
  border-radius: 50%;
  cursor: pointer;
  transition:
    opacity 0.15s,
    transform 0.15s;
}
.send:hover:not(:disabled) {
  transform: translateY(-1px);
}
.send:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}
.send--stop {
  background: var(--ekb-text-1);
}
.send__square {
  width: 11px;
  height: 11px;
  background: var(--ekb-bg-panel);
  border-radius: 2px;
}
.chat__disclaimer {
  margin-top: 6px;
  font-size: 12px;
  text-align: center;
  color: var(--ekb-text-3);
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 900px) {
  .side {
    display: none;
  }
  .welcome__grid {
    grid-template-columns: 1fr;
  }
}
</style>
