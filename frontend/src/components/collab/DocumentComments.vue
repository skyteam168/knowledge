<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createComment,
  deleteComment,
  listComments,
  resolveComment,
  updateComment,
} from '@/api/collab'
import { searchPrincipals } from '@/api/knowledge'
import { HttpError } from '@/api/http'
import type { DocComment, PrincipalOption } from '@/api/types'
import { formatDateTime } from '@/utils/format'

/** Comments of one document: threads (one reply level), @mentions, resolve / reopen. */
const props = defineProps<{ docId: string; focus?: string | null }>()
const emit = defineEmits<{ count: [open: number] }>()
const { t } = useI18n()

type Filter = 'open' | 'resolved' | 'all'
const FILTERS: Filter[] = ['open', 'resolved', 'all']
const threads = ref<DocComment[]>([])
const loading = ref(false)
const filter = ref<Filter>('open')
const box = ref<HTMLElement>()

const shown = computed(() =>
  threads.value.filter((c) =>
    filter.value === 'all' ? true : filter.value === 'open' ? !c.resolved_at : !!c.resolved_at,
  ),
)

async function load(): Promise<void> {
  loading.value = true
  try {
    threads.value = await listComments(props.docId)
    emit('count', threads.value.filter((c) => !c.resolved_at && !c.deleted).length)
  } finally {
    loading.value = false
  }
}

// ---- composer (new comment or reply) ------------------------------------------------

const people = ref<PrincipalOption[]>([])
const searching = ref(false)

async function searchPeople(keyword: string): Promise<void> {
  searching.value = true
  try {
    people.value = await searchPrincipals('user', keyword || undefined)
  } finally {
    searching.value = false
  }
}

const draft = reactive({ body: '', mentions: [] as string[], posting: false })
const reply = reactive({ to: null as DocComment | null, body: '', posting: false })

async function post(body: string, parentId: string | null, mentions: string[]): Promise<boolean> {
  try {
    await createComment(props.docId, { body, parent_id: parentId, mentions })
  } catch (err) {
    if (err instanceof HttpError && err.code === 'MENTION_NO_ACCESS') {
      const users = (err.detail as { users?: string[] } | null)?.users ?? []
      ElMessage.error(t('collab.comment.mentionNoAccess', { users: users.join('、') }))
    } else {
      ElMessage.error(err instanceof Error ? err.message : String(err))
    }
    return false
  }
  ElMessage.success(t('collab.comment.posted'))
  await load()
  return true
}

async function submit(): Promise<void> {
  if (!draft.body.trim()) return
  draft.posting = true
  try {
    if (await post(draft.body, null, draft.mentions)) {
      draft.body = ''
      draft.mentions = []
      filter.value = 'open'
    }
  } finally {
    draft.posting = false
  }
}

function startReply(comment: DocComment): void {
  reply.to = comment
  reply.body = ''
}

async function submitReply(): Promise<void> {
  if (!reply.to || !reply.body.trim()) return
  reply.posting = true
  try {
    if (await post(reply.body, reply.to.id, [])) reply.to = null
  } finally {
    reply.posting = false
  }
}

// ---- edit / delete / resolve ----------------------------------------------------------

const editing = reactive({ id: null as string | null, body: '' })

function startEdit(comment: DocComment): void {
  editing.id = comment.id
  editing.body = comment.body
}

async function saveEdit(): Promise<void> {
  if (!editing.id || !editing.body.trim()) return
  await updateComment(editing.id, editing.body)
  editing.id = null
  await load()
}

async function remove(comment: DocComment): Promise<void> {
  await ElMessageBox.confirm(t('collab.comment.deleteConfirm'), t('common.tip'), {
    type: 'warning',
  })
  await deleteComment(comment.id)
  await load()
}

async function toggleResolved(comment: DocComment): Promise<void> {
  await resolveComment(comment.id, !comment.resolved_at)
  await load()
}

watch(
  () => props.docId,
  async () => {
    filter.value = props.focus ? 'all' : 'open'
    await load()
    if (!props.focus) return
    await nextTick()
    box.value
      ?.querySelector<HTMLElement>(`[data-comment="${props.focus}"]`)
      ?.scrollIntoView({ block: 'center' })
  },
  { immediate: true },
)
</script>

<template>
  <div ref="box" v-loading="loading" class="comments" data-test="doc-comments">
    <div class="composer">
      <el-input
        v-model="draft.body"
        type="textarea"
        :rows="3"
        maxlength="2000"
        show-word-limit
        :placeholder="t('collab.comment.placeholder')"
        data-test="comment-body"
      />
      <div class="composer__bar">
        <el-select
          v-model="draft.mentions"
          multiple
          filterable
          remote
          :remote-method="searchPeople"
          :loading="searching"
          :placeholder="t('collab.comment.mentionPlaceholder')"
          class="composer__mention"
          data-test="comment-mentions"
        >
          <template #prefix>@</template>
          <el-option v-for="p in people" :key="p.id" :label="p.name" :value="p.id">
            <span>{{ p.name }}</span>
            <span v-if="p.description" class="sub">{{ p.description }}</span>
          </el-option>
        </el-select>
        <el-button
          type="primary"
          :loading="draft.posting"
          :disabled="!draft.body.trim()"
          data-test="comment-submit"
          @click="submit"
          >{{ t('collab.comment.submit') }}</el-button
        >
      </div>
    </div>

    <el-radio-group v-model="filter" size="small" class="filter">
      <el-radio-button v-for="f in FILTERS" :key="f" :value="f">{{
        t(`collab.comment.filter.${f}`)
      }}</el-radio-button>
    </el-radio-group>

    <el-empty v-if="!shown.length" :description="t('collab.comment.empty')" :image-size="60" />

    <article
      v-for="c in shown"
      :key="c.id"
      class="thread"
      :class="{ 'thread--resolved': !!c.resolved_at, 'thread--focus': c.id === focus }"
      :data-comment="c.id"
    >
      <template v-for="item in [c, ...c.replies]" :key="item.id">
        <div class="item" :class="{ 'item--reply': !!item.parent_id }" :data-comment="item.id">
          <div class="item__head">
            <span class="author">{{ item.author_name }}</span>
            <span class="meta">{{ formatDateTime(item.created_at) }}</span>
            <el-tag v-if="!item.parent_id" size="small" effect="plain" type="info">{{
              t('collab.comment.version', { n: item.document_version })
            }}</el-tag>
            <span v-if="item.edited" class="meta">· {{ t('collab.comment.edited') }}</span>
            <el-tag
              v-if="!item.parent_id && item.resolved_at"
              size="small"
              type="success"
              data-test="comment-resolved"
              >{{
                item.resolved_by_name
                  ? t('collab.comment.resolvedBy', { name: item.resolved_by_name })
                  : t('collab.comment.resolved')
              }}</el-tag
            >
          </div>
          <div v-if="item.deleted" class="body body--deleted">
            {{ t('collab.comment.deleted') }}
          </div>
          <template v-else-if="editing.id === item.id">
            <el-input v-model="editing.body" type="textarea" :rows="3" maxlength="2000" />
            <div class="actions">
              <el-button size="small" type="primary" @click="saveEdit">{{
                t('collab.comment.save')
              }}</el-button>
              <el-button size="small" @click="editing.id = null">{{
                t('collab.comment.cancel')
              }}</el-button>
            </div>
          </template>
          <template v-else>
            <div class="body">
              <span v-for="m in item.mentions" :key="m.id" class="mention">@{{ m.name }}</span>
              {{ item.body }}
            </div>
            <div class="actions">
              <el-button v-if="!item.parent_id" link size="small" @click="startReply(item)">{{
                t('collab.comment.reply')
              }}</el-button>
              <el-button
                v-if="item.can_resolve"
                link
                size="small"
                type="success"
                data-test="comment-resolve"
                @click="toggleResolved(item)"
                >{{
                  item.resolved_at ? t('collab.comment.reopen') : t('collab.comment.resolve')
                }}</el-button
              >
              <el-button v-if="item.can_edit" link size="small" @click="startEdit(item)">{{
                t('collab.comment.edit')
              }}</el-button>
              <el-button
                v-if="item.can_delete"
                link
                size="small"
                type="danger"
                @click="remove(item)"
                >{{ t('collab.comment.delete') }}</el-button
              >
            </div>
          </template>
        </div>
      </template>
      <div v-if="reply.to?.id === c.id" class="reply-box">
        <el-input
          v-model="reply.body"
          type="textarea"
          :rows="2"
          maxlength="2000"
          :placeholder="t('collab.comment.replyPlaceholder', { name: c.author_name })"
          data-test="reply-body"
        />
        <div class="actions">
          <el-button
            size="small"
            type="primary"
            :loading="reply.posting"
            :disabled="!reply.body.trim()"
            data-test="reply-submit"
            @click="submitReply"
            >{{ t('collab.comment.reply') }}</el-button
          >
          <el-button size="small" @click="reply.to = null">{{
            t('collab.comment.cancel')
          }}</el-button>
        </div>
      </div>
    </article>
  </div>
</template>

<style scoped>
.comments {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.composer__bar {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.composer__mention {
  flex: 1;
}
.filter {
  align-self: flex-start;
}
.thread {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
}
.thread--resolved {
  background: var(--el-fill-color-lighter);
}
.thread--focus {
  border-color: var(--el-color-primary);
}
.item + .item {
  margin-top: 10px;
}
.item--reply {
  margin-left: 20px;
  padding-left: 10px;
  border-left: 2px solid var(--el-border-color-lighter);
}
.item__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.author {
  font-weight: 600;
  font-size: 13px;
}
.meta,
.sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.sub {
  margin-left: 8px;
}
.body {
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.7;
}
.body--deleted {
  color: var(--el-text-color-placeholder);
  font-style: italic;
}
.mention {
  color: var(--el-color-primary);
  margin-right: 4px;
}
.actions {
  margin-top: 4px;
}
.reply-box {
  margin: 10px 0 0 20px;
}
</style>
