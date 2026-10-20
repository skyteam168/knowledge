"""Document comments: one level of replies, @mentions, resolve / reopen.

Anyone who can read a document may read and write its comments. Mentioned colleagues must be
able to read the document too, so a mention never leaks its title to someone without access.
"""

from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationAppError
from app.models import Document, DocumentComment, KnowledgeBase
from app.models.base import utcnow
from app.repositories.collab_repo import CommentRepository
from app.repositories.knowledge_repo import DocumentRepository, KnowledgeBaseRepository
from app.repositories.user_repo import UserRepository
from app.schemas.collab import CommentCreate, CommentOut, CommentUpdate, MentionOut
from app.services.audit_service import snapshot
from app.services.authz import AclPermission
from app.services.authz.acting import current_user_of
from app.services.context import BaseService
from app.services.curation.notifications import NotificationKind, notify
from app.services.knowledge.access import RESOURCE_DOCUMENT, KnowledgeAccess
from app.services.knowledge.review import review_recipient

DELETED_BODY = ""
PREVIEW_CHARS = 200


def _link(doc: Document, comment_id: str) -> str:
    return f"/knowledge/{doc.kb_id}/documents/{doc.id}?tab=comments&comment={comment_id}"


class CommentService(BaseService):
    @property
    def access(self) -> KnowledgeAccess:
        return KnowledgeAccess(self.session)

    @property
    def repo(self) -> CommentRepository:
        return CommentRepository(self.session)

    async def _doc(
        self, document_id: str, required: AclPermission = AclPermission.READ
    ) -> tuple[Document, KnowledgeBase, AclPermission]:
        doc = await DocumentRepository(self.session).get(self.org_id, document_id)
        kb = (
            await KnowledgeBaseRepository(self.session).get(self.org_id, doc.kb_id) if doc else None
        )
        if doc is None or kb is None:
            raise NotFoundError("Document not found")
        perm = await self.access.require_document(self.ctx.user, doc, kb, required)
        return doc, kb, perm

    async def _comment(
        self, comment_id: str
    ) -> tuple[DocumentComment, Document, KnowledgeBase, AclPermission]:
        comment = await self.repo.get(self.org_id, comment_id)
        if comment is None or comment.deleted_at is not None:
            raise NotFoundError("Comment not found")
        doc, kb, perm = await self._doc(comment.document_id)
        return comment, doc, kb, perm

    def _may_resolve(self, comment: DocumentComment, doc: Document, perm: AclPermission) -> bool:
        uid = self.ctx.user.id
        return (
            comment.author_id == uid
            or review_recipient(doc) == uid
            or perm.level >= AclPermission.EDIT.level
        )

    async def _render(
        self, rows: list[DocumentComment], doc: Document, perm: AclPermission
    ) -> list[CommentOut]:
        """One output per row, in order (no threading)."""
        ids = {r.author_id for r in rows} | {r.resolved_by for r in rows if r.resolved_by}
        ids |= {m for r in rows for m in r.mentions}
        users = await UserRepository(self.session).list_by_ids(
            self.org_id, sorted(i for i in ids if i)
        )
        names = {u.id: u.display_name or u.username for u in users}
        uid = self.ctx.user.id
        manage = perm.level >= AclPermission.MANAGE.level

        def out(r: DocumentComment) -> CommentOut:
            deleted = r.deleted_at is not None
            return CommentOut(
                id=r.id,
                parent_id=r.parent_id,
                author_id=r.author_id,
                author_name=names.get(r.author_id, r.author_id),
                body=DELETED_BODY if deleted else r.body,
                mentions=(
                    [] if deleted else [MentionOut(id=m, name=names.get(m, m)) for m in r.mentions]
                ),
                document_version=r.document_version,
                created_at=r.created_at,
                edited=r.edited_at is not None,
                resolved_at=r.resolved_at,
                resolved_by_name=names.get(r.resolved_by) if r.resolved_by else None,
                deleted=deleted,
                can_edit=not deleted and r.author_id == uid,
                can_delete=not deleted and (r.author_id == uid or manage),
                can_resolve=(
                    not deleted and r.parent_id is None and self._may_resolve(r, doc, perm)
                ),
            )

        return [out(r) for r in rows]

    async def _one(self, row: DocumentComment, doc: Document, perm: AclPermission) -> CommentOut:
        return (await self._render([row], doc, perm))[0]

    async def threads(self, document_id: str) -> list[CommentOut]:
        """Top-level comments (oldest first) with their replies."""
        doc, _, perm = await self._doc(document_id)
        rows = await self.repo.list_for_document(doc.id)
        outs = await self._render(rows, doc, perm)
        top = [c for c in outs if c.parent_id is None]
        by_id = {c.id: c for c in top}
        for c in outs:
            if c.parent_id in by_id and not c.deleted:
                by_id[c.parent_id].replies.append(c)
        # A deleted comment stays only as a placeholder for its replies.
        return [c for c in top if not c.deleted or c.replies]

    async def _check_mentions(self, doc: Document, kb: KnowledgeBase, ids: list[str]) -> list[str]:
        wanted = list(dict.fromkeys(i for i in ids if i != self.ctx.user.id))
        found = await UserRepository(self.session).list_by_ids(self.org_id, wanted)
        users = {u.id: u for u in found}
        denied: list[str] = []
        for uid in wanted:
            user = users.get(uid)
            if user is None or not user.is_active:
                denied.append(uid)
                continue
            acting = await current_user_of(self.session, self.authz_cache, user)
            if await self.access.document_permission(acting, doc, kb) is None:
                denied.append(user.display_name or user.username)
        if denied:
            raise ValidationAppError(
                "Mentioned colleagues cannot read this document",
                code="MENTION_NO_ACCESS",
                detail={"users": denied},
            )
        return wanted

    async def create(self, document_id: str, data: CommentCreate) -> CommentOut:
        doc, kb, perm = await self._doc(document_id)
        parent = None
        if data.parent_id:
            parent = await self.repo.get(self.org_id, data.parent_id)
            if parent is None or parent.document_id != doc.id or parent.deleted_at is not None:
                raise NotFoundError("Comment not found")
            if parent.parent_id is not None:
                raise ValidationAppError("Replies cannot be nested", code="COMMENT_NESTED")
        mentions = await self._check_mentions(doc, kb, data.mentions)
        comment = DocumentComment(
            org_id=self.org_id,
            document_id=doc.id,
            kb_id=doc.kb_id,
            parent_id=parent.id if parent else None,
            author_id=self.ctx.user.id,
            body=data.body,
            mentions=mentions,
            document_version=doc.version,
        )
        await self.repo.add(comment)
        await self._notify(doc, comment, parent, mentions)
        await self.audit.record(
            self.audit_ctx,
            "document.comment",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            snapshot(
                {"comment_id": comment.id, "parent_id": comment.parent_id, "mentions": mentions}
            ),
        )
        return await self._one(comment, doc, perm)

    async def _notify(
        self,
        doc: Document,
        comment: DocumentComment,
        parent: DocumentComment | None,
        mentions: list[str],
    ) -> None:
        author = self.ctx.user.display_name or self.ctx.user.username
        preview = comment.body[:PREVIEW_CHARS]
        link = _link(doc, parent.id if parent else comment.id)
        await notify(
            self.session,
            self.org_id,
            mentions,
            kind=NotificationKind.COMMENT_MENTION,
            title=f"{author} 在《{doc.title[:60]}》中提到了你",
            body=preview,
            resource_type=RESOURCE_DOCUMENT,
            resource_id=doc.id,
            link=link,
            dedupe_key=f"comment:{comment.id}",
        )
        others = {review_recipient(doc), parent.author_id if parent else None}
        others -= {self.ctx.user.id, None, *mentions}
        await notify(
            self.session,
            self.org_id,
            sorted(u for u in others if u),
            kind=NotificationKind.COMMENT_NEW,
            title=(
                f"{author} 回复了《{doc.title[:60]}》的评论"
                if parent
                else f"{author} 评论了《{doc.title[:60]}》"
            ),
            body=preview,
            resource_type=RESOURCE_DOCUMENT,
            resource_id=doc.id,
            link=link,
            dedupe_key=f"comment:{comment.id}",
        )

    async def update(self, comment_id: str, data: CommentUpdate) -> CommentOut:
        comment, doc, _, perm = await self._comment(comment_id)
        if comment.author_id != self.ctx.user.id:
            raise PermissionDeniedError("Only the author can edit a comment")
        before = {"body": comment.body}
        comment.body = data.body
        comment.edited_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "document.comment_edit",
            RESOURCE_DOCUMENT,
            doc.id,
            snapshot({"comment_id": comment.id, **before}),
            snapshot({"comment_id": comment.id, "body": comment.body}),
        )
        return await self._one(comment, doc, perm)

    async def delete(self, comment_id: str) -> None:
        comment, doc, _, perm = await self._comment(comment_id)
        if comment.author_id != self.ctx.user.id and perm.level < AclPermission.MANAGE.level:
            raise PermissionDeniedError("Only the author or a manager can delete a comment")
        comment.deleted_at = utcnow()
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "document.comment_delete",
            RESOURCE_DOCUMENT,
            doc.id,
            snapshot(
                {"comment_id": comment.id, "author_id": comment.author_id, "body": comment.body}
            ),
            None,
        )

    async def resolve(self, comment_id: str, resolved: bool) -> CommentOut:
        comment, doc, _, perm = await self._comment(comment_id)
        if comment.parent_id is not None:
            raise ValidationAppError("Only top-level comments can be resolved")
        if not self._may_resolve(comment, doc, perm):
            raise PermissionDeniedError("Not allowed to resolve this comment")
        comment.resolved_at = utcnow() if resolved else None
        comment.resolved_by = self.ctx.user.id if resolved else None
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "document.comment_resolve" if resolved else "document.comment_reopen",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            snapshot({"comment_id": comment.id}),
        )
        return await self._one(comment, doc, perm)
