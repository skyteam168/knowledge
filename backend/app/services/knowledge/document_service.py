import asyncio
import hashlib
import json
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import KeyValueCache
from app.core.config import Settings
from app.core.db import run_after_commit
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationAppError,
)
from app.core.storage import STAGING_PREFIX, ObjectStorage
from app.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    KnowledgeBase,
    PageAssetKind,
)
from app.models.base import new_id, utcnow
from app.repositories.base import paginate
from app.repositories.knowledge_repo import (
    ChunkRepository,
    DocumentPageAssetRepository,
    DocumentRepository,
    KnowledgeBaseRepository,
)
from app.repositories.user_repo import UserRepository
from app.schemas.common import Page
from app.schemas.knowledge import (
    ChunkOut,
    DiffLineOut,
    DocumentAclOut,
    DocumentAclUpdate,
    DocumentDetail,
    DocumentOut,
    DocumentReviewIn,
    DocumentUpdate,
    DocumentVersionOut,
    PagePreviewOut,
    PreviewOut,
    ProtectionOut,
    UploadComplete,
    UploadInit,
    UploadInitOut,
    UploadResult,
    VersionCompareOut,
    VersionTextOut,
)
from app.services.audit_service import snapshot
from app.services.authz import (
    AclPermission,
    AuthzCache,
    CurrentUser,
    PermissionResolver,
    PrincipalResolver,
)
from app.services.context import BaseService, RequestContext
from app.services.ingest.parsers.base import FileKind, canonical_mime, detect_kind
from app.services.ingest.pipeline import parsed_key
from app.services.ingest.queue import TaskQueue
from app.services.ingest.sections import ParsedDocument
from app.services.knowledge.access import RESOURCE_DOCUMENT, RESOURCE_KB, KnowledgeAccess
from app.services.knowledge.directory import PrincipalDirectory
from app.services.knowledge.page_links import PageLinks
from app.services.knowledge.protection import protection_of
from app.services.knowledge.review import (
    mark_reviewed,
    refresh_due,
    review_interval,
    review_state,
)
from app.services.knowledge.version_diff import diff_lines, document_lines
from app.services.outbox_service import ACL_CHANGED, DOCUMENT_DELETED, OutboxService
from app.services.security.file_guard import FileGuard
from app.services.security.pii import PiiMasker

MAX_FILENAME_LENGTH = 255
TICKET_PREFIX = "upload:"
ReviewFilter = Literal["due_soon", "overdue", "attention"]


class UnsupportedFileError(AppError):
    status_code = 415
    code = "UNSUPPORTED_FILE_TYPE"
    message = "Unsupported file type"


class FileTooLargeError(AppError):
    status_code = 413
    code = "FILE_TOO_LARGE"
    message = "File too large"


def clean_filename(filename: str) -> str:
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        raise ValidationAppError("Invalid filename")
    if len(name) > MAX_FILENAME_LENGTH:
        suffix = PurePosixPath(name).suffix[:16]
        name = name[: MAX_FILENAME_LENGTH - len(suffix)] + suffix
    return name


def to_document_out(
    doc: Document, perm: AclPermission | None, kb: KnowledgeBase, *, notice_days: int
) -> DocumentOut:
    protection = protection_of(kb, doc)
    permission = perm.value if perm else None
    return DocumentOut.model_validate(doc).model_copy(
        update={
            "my_permission": permission,
            "protection": ProtectionOut(**asdict(protection)),
            "can_download": protection.can_download(permission),
            "review_interval": review_interval(kb, doc),
            "review_state": review_state(doc, utcnow(), notice_days),
        }
    )


def _staging_key(org_id: str, ticket: str) -> str:
    return f"{STAGING_PREFIX}{org_id}/{ticket}"


def _preview_type(mime_type: str) -> str:
    """Browsers download text/markdown and text/csv instead of showing them inline."""
    if mime_type in {"text/plain", "text/markdown", "text/csv"}:
        return "text/plain; charset=utf-8"
    if mime_type == "text/html":
        return "text/html; charset=utf-8"
    return mime_type


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _entry_strings(rows: Sequence[tuple[str, str, str]]) -> list[str]:
    return sorted(f"{t}:{i}:{p}" for t, i, p in rows)


class DocumentService(BaseService):
    def __init__(
        self,
        session: AsyncSession,
        ctx: RequestContext,
        authz_cache: AuthzCache,
        *,
        storage: ObjectStorage,
        queue: TaskQueue,
        cache: KeyValueCache,
        settings: Settings,
        guard: FileGuard | None = None,
    ) -> None:
        super().__init__(session, ctx, authz_cache)
        self.storage = storage
        self.queue = queue
        self.cache = cache
        self.settings = settings
        self.guard = guard or FileGuard(settings)

    @property
    def repo(self) -> DocumentRepository:
        return DocumentRepository(self.session)

    @property
    def access(self) -> KnowledgeAccess:
        return KnowledgeAccess(self.session)

    def _out(self, doc: Document, perm: AclPermission | None, kb: KnowledgeBase) -> DocumentOut:
        return to_document_out(doc, perm, kb, notice_days=self.settings.expiry_notice_days)

    async def _user_names(self, ids: Iterable[str | None]) -> dict[str, str]:
        wanted = sorted({i for i in ids if i})
        users = await UserRepository(self.session).list_by_ids(self.org_id, wanted)
        return {u.id: u.display_name or u.username for u in users}

    async def _with_owner_names(self, outs: list[DocumentOut]) -> list[DocumentOut]:
        names = await self._user_names(o.owner_id for o in outs)
        return [
            o.model_copy(update={"owner_name": names.get(o.owner_id)}) if o.owner_id else o
            for o in outs
        ]

    # ---- loading + permission checks ----

    async def _kb(self, kb_id: str, required: AclPermission) -> tuple[KnowledgeBase, AclPermission]:
        kb = await KnowledgeBaseRepository(self.session).get(self.org_id, kb_id)
        if kb is None:
            raise NotFoundError("Knowledge base not found")
        return kb, await self.access.require_kb(self.ctx.user, kb, required)

    async def _doc(
        self, document_id: str, required: AclPermission
    ) -> tuple[Document, KnowledgeBase, AclPermission]:
        doc = await self.repo.get(self.org_id, document_id)
        kb = (
            await KnowledgeBaseRepository(self.session).get(self.org_id, doc.kb_id) if doc else None
        )
        if doc is None or kb is None:
            raise NotFoundError("Document not found")
        perm = await self.access.require_document(self.ctx.user, doc, kb, required)
        return doc, kb, perm

    def _check_file(
        self, filename: str, size: int, mime_type: str | None
    ) -> tuple[str, str, FileKind]:
        name = clean_filename(filename)
        kind = detect_kind(name, mime_type)
        allowed = self.settings.upload_allowed_kinds
        if kind is None or (allowed and kind.value not in allowed):
            raise UnsupportedFileError(
                detail={"filename": name, "allowed": allowed or [k.value for k in FileKind]}
            )
        if size <= 0:
            raise ValidationAppError("Empty file")
        if size > self.settings.upload_max_bytes:
            raise FileTooLargeError(detail={"max_bytes": self.settings.upload_max_bytes})
        return name, canonical_mime(kind, name), kind

    # ---- upload ----

    async def _duplicate_result(self, doc: Document, kb: KnowledgeBase) -> UploadResult:
        perm = await self.access.document_permission(self.ctx.user, doc, kb)
        if perm is None:
            raise ConflictError("An identical file already exists in this knowledge base")
        return UploadResult(document=self._out(doc, perm, kb), duplicate=True, new_version=False)

    async def create_upload(self, kb_id: str, data: UploadInit) -> UploadInitOut:
        kb, _ = await self._kb(kb_id, AclPermission.EDIT)
        filename, mime_type, _ = self._check_file(data.filename, data.size_bytes, data.mime_type)
        sha256 = data.sha256.lower()
        existing = await self.repo.find_by_sha256(self.org_id, kb.id, sha256)
        if existing is not None:
            dup = await self._duplicate_result(existing, kb)
            return UploadInitOut(duplicate=True, document=dup.document)
        await self.storage.ensure_bucket()
        ticket = secrets.token_hex(16)
        key = _staging_key(self.org_id, ticket)
        ttl = self.settings.upload_ticket_ttl_seconds
        payload = {
            "org_id": self.org_id,
            "kb_id": kb.id,
            "user_id": self.ctx.user.id,
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": data.size_bytes,
            "sha256": sha256,
            "key": key,
        }
        await self.cache.set(f"{TICKET_PREFIX}{ticket}", json.dumps(payload), ttl)
        expires = min(ttl, self.settings.presign_expiry_seconds)
        return UploadInitOut(
            duplicate=False,
            ticket=ticket,
            upload_url=self.storage.presign_put(key, expires),
            expires_in=expires,
        )

    async def complete_upload(self, kb_id: str, data: UploadComplete) -> UploadResult:
        kb, _ = await self._kb(kb_id, AclPermission.EDIT)
        raw = await self.cache.get(f"{TICKET_PREFIX}{data.ticket}")
        ticket: dict[str, Any] | None = json.loads(raw) if raw else None
        if (
            ticket is None
            or ticket["org_id"] != self.org_id
            or ticket["kb_id"] != kb.id
            or ticket["user_id"] != self.ctx.user.id
        ):
            raise NotFoundError("Upload ticket not found or expired")
        key = str(ticket["key"])
        info = await self.storage.stat(key)
        if info is None:
            raise ValidationAppError("File has not been uploaded yet")
        if info.size != int(ticket["size_bytes"]):
            await self.storage.delete(key)
            raise ValidationAppError(
                "Uploaded size mismatch",
                detail={"expected": ticket["size_bytes"], "actual": info.size},
            )
        actual_sha = await self.storage.sha256(key)
        if actual_sha != ticket["sha256"]:
            await self.storage.delete(key)
            raise ValidationAppError("Uploaded content checksum mismatch")
        kind = detect_kind(str(ticket["filename"]), str(ticket["mime_type"]))
        if kind is not None and self.guard.inspects_content:
            try:
                await self.guard.check(
                    kind, str(ticket["filename"]), await self.storage.get_bytes(key)
                )
            except AppError as exc:
                if exc.status_code != 503:
                    await self.storage.delete(key)
                    await self.cache.delete(f"{TICKET_PREFIX}{data.ticket}")
                raise
        await self.cache.delete(f"{TICKET_PREFIX}{data.ticket}")
        return await self._register(
            kb,
            filename=str(ticket["filename"]),
            mime_type=str(ticket["mime_type"]),
            size_bytes=info.size,
            sha256=actual_sha,
            source_key=key,
            tags=data.tags,
        )

    async def upload_direct(
        self,
        kb_id: str,
        *,
        filename: str,
        content: bytes,
        mime_type: str | None,
        tags: list[str] | None = None,
    ) -> UploadResult:
        kb, _ = await self._kb(kb_id, AclPermission.EDIT)
        name, mime, kind = self._check_file(filename, len(content), mime_type)
        sha256 = hashlib.sha256(content).hexdigest()
        existing = await self.repo.find_by_sha256(self.org_id, kb.id, sha256)
        if existing is not None:
            return await self._duplicate_result(existing, kb)
        await self.guard.check(kind, name, content)
        key = _staging_key(self.org_id, secrets.token_hex(16))
        await self.storage.ensure_bucket()
        await self.storage.put_bytes(key, content, mime)
        return await self._register(
            kb,
            filename=name,
            mime_type=mime,
            size_bytes=len(content),
            sha256=sha256,
            source_key=key,
            tags=tags or [],
        )

    async def _register(
        self,
        kb: KnowledgeBase,
        *,
        filename: str,
        mime_type: str,
        size_bytes: int,
        sha256: str,
        source_key: str,
        tags: list[str],
    ) -> UploadResult:
        duplicate = await self.repo.find_by_sha256(self.org_id, kb.id, sha256)
        if duplicate is not None:
            await self.storage.delete(source_key)
            return await self._duplicate_result(duplicate, kb)

        clean_tags = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
        doc = await self.repo.find_by_filename(self.org_id, kb.id, filename)
        new_version = doc is not None
        if doc is not None:
            perm = await self.access.document_permission(self.ctx.user, doc, kb)
            if perm is None or perm.level < AclPermission.EDIT.level:
                raise PermissionDeniedError(
                    "A document with this filename exists and you cannot update it"
                )
            before = snapshot(doc)
            self._advance(doc, mime_type=mime_type, size_bytes=size_bytes, sha256=sha256)
            if clean_tags:
                doc.tags = list(dict.fromkeys([*doc.tags, *clean_tags]))
        else:
            before = None
            doc = Document(
                id=new_id(),
                org_id=self.org_id,
                kb_id=kb.id,
                title=PurePosixPath(filename).stem or filename,
                filename=filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256,
                minio_key="",
                version=1,
                status=DocumentStatus.UPLOADED.value,
                tags=clean_tags,
                meta={},
                acl_inherit=True,
                created_by=self.ctx.user.id,
            )
        mark_reviewed(kb, doc, self.ctx.user.id, utcnow())
        final_key = self._file_key(doc, filename)
        await self.storage.copy(source_key, final_key)
        await self.storage.delete(source_key)
        doc.minio_key = final_key
        if not new_version:
            await self.repo.add(doc)
        await self.repo.add_version(
            DocumentVersion(
                org_id=self.org_id,
                document_id=doc.id,
                version=doc.version,
                filename=filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                sha256=sha256,
                minio_key=final_key,
                created_by=self.ctx.user.id,
            )
        )
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "document.new_version" if new_version else "document.upload",
            RESOURCE_DOCUMENT,
            doc.id,
            before,
            snapshot(doc),
        )
        self._enqueue_parse(doc)
        perm = await self.access.document_permission(self.ctx.user, doc, kb)
        return UploadResult(
            document=self._out(doc, perm, kb), duplicate=False, new_version=new_version
        )

    @staticmethod
    def _advance(doc: Document, *, mime_type: str, size_bytes: int, sha256: str) -> None:
        """Start a new version of `doc`: new file facts, parse state reset."""
        doc.version += 1
        doc.mime_type = mime_type
        doc.size_bytes = size_bytes
        doc.sha256 = sha256
        doc.status = DocumentStatus.UPLOADED.value
        doc.error_message = None
        doc.chunk_count = None
        doc.parsed_at = None
        doc.chunked_at = None
        doc.meta = {k: v for k, v in doc.meta.items() if k != "parse"}

    def _file_key(self, doc: Document, filename: str) -> str:
        return f"{self.org_id}/{doc.kb_id}/{doc.id}/v{doc.version}/{filename}"

    def _enqueue_parse(self, doc: Document) -> None:
        document_id, version, queue = doc.id, doc.version, self.queue
        run_after_commit(self.session, lambda: queue.enqueue_parse(document_id, version))

    # ---- read ----

    async def search(
        self,
        kb_id: str,
        *,
        page: int,
        size: int,
        status: str | None = None,
        keyword: str | None = None,
        review: ReviewFilter | None = None,
        mine: bool = False,
    ) -> Page[DocumentOut]:
        """`review`: due_soon (within the notice period), overdue, or attention (both)."""
        kb, kb_perm = await self._kb(kb_id, AclPermission.READ)
        now = utcnow()
        soon = now + timedelta(days=self.settings.expiry_notice_days)
        windows: dict[ReviewFilter, tuple[datetime | None, datetime | None]] = {
            "due_soon": (now, soon),
            "overdue": (None, now),
            "attention": (None, soon),
        }
        stmt = self.repo.search_stmt(
            self.org_id,
            kb.id,
            status=status,
            keyword=keyword,
            visible=self.access.visible_document_clause(self.ctx.user, kb_perm),
            review_due=windows[review] if review else None,
            owner_id=self.ctx.user.id if mine else None,
        )
        if review:
            stmt = stmt.order_by(None).order_by(Document.review_due_at, Document.id)
        docs, total = await paginate(self.session, stmt, page, size)
        perms = await self.access.document_permissions(self.ctx.user, docs, kb_perm)
        items = await self._with_owner_names([self._out(d, perms.get(d.id), kb) for d in docs])
        return Page(items=items, total=total, page=page, size=size)

    async def get(self, document_id: str) -> DocumentDetail:
        doc, kb, perm = await self._doc(document_id, AclPermission.READ)
        versions = await self.repo.versions(doc.id)
        (base,) = await self._with_owner_names([self._out(doc, perm, kb)])
        return DocumentDetail(
            **base.model_dump(),
            kb_name=kb.name,
            kb_review_interval_days=kb.review_interval_days,
            versions=await self._version_outs(versions),
        )

    async def _version_outs(self, rows: Sequence[DocumentVersion]) -> list[DocumentVersionOut]:
        names = await self._user_names(r.created_by for r in rows)
        return [
            DocumentVersionOut.model_validate(r).model_copy(
                update={"created_by_name": names.get(r.created_by or "")}
            )
            for r in rows
        ]

    async def _version(self, doc: Document, version: int) -> DocumentVersion:
        row = await self.repo.get_version(doc.id, version)
        if row is None:
            raise NotFoundError("Document version not found")
        return row

    async def chunks(self, document_id: str) -> list[ChunkOut]:
        doc, _, _ = await self._doc(document_id, AclPermission.READ)
        rows = await ChunkRepository(self.session).list_for_document(doc.id, doc.version)
        return [ChunkOut.model_validate(c) for c in rows]

    def _links(self) -> PageLinks:
        return PageLinks(self.session, self.storage, self.settings, self.ctx.user.id)

    async def preview_url(self, document_id: str, version: int | None = None) -> PreviewOut:
        doc, kb, perm = await self._doc(document_id, AclPermission.READ)
        source = await self._version(doc, version) if version is not None else None
        number = source.version if source else doc.version
        if protection_of(kb, doc).raw_preview(perm.value):
            return await self._file_url(doc, attachment=False, source=source)
        assets = await DocumentPageAssetRepository(self.session).list_for_version(doc.id, number)
        links = self._links()
        pages = [
            PagePreviewOut(
                index=a.page_index, url=await links.url(a), width=a.width, height=a.height
            )
            for a in assets
        ]
        await self.audit.record(
            self.audit_ctx,
            "document.preview",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"kb_id": doc.kb_id, "version": number, "mode": "pages", "pages": len(pages)},
        )
        return PreviewOut(
            mode="pages" if pages else "none",
            filename=source.filename if source else doc.filename,
            mime_type=source.mime_type if source else doc.mime_type,
            expires_in=self.settings.presign_expiry_seconds,
            pages=pages,
        )

    async def download_url(self, document_id: str, version: int | None = None) -> PreviewOut:
        doc, kb, perm = await self._doc(document_id, AclPermission.READ)
        if not protection_of(kb, doc).can_download(perm.value):
            raise PermissionDeniedError(
                "Downloading the original file is not allowed", code="DOWNLOAD_FORBIDDEN"
            )
        source = await self._version(doc, version) if version is not None else None
        return await self._file_url(doc, attachment=True, source=source)

    async def page_asset_url(self, document_id: str, *, kind: str, page_index: int) -> PreviewOut:
        if kind not in {PageAssetKind.PAGE.value, PageAssetKind.SLIDE.value}:
            raise NotFoundError("Page asset not found")
        doc, _, _ = await self._doc(document_id, AclPermission.READ)
        asset = await DocumentPageAssetRepository(self.session).get(
            doc.id, doc.version, kind, page_index
        )
        if asset is None:
            raise NotFoundError("Page asset not found")
        expires = self.settings.presign_expiry_seconds
        filename = f"{kind}-{page_index}.png"
        url = await self._links().url(asset)
        await self.audit.record(
            self.audit_ctx,
            "document.page_preview",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"kb_id": doc.kb_id, "version": doc.version, "kind": kind, "page_index": page_index},
        )
        return PreviewOut(url=url, filename=filename, mime_type=asset.mime_type, expires_in=expires)

    async def _file_url(
        self, doc: Document, *, attachment: bool, source: DocumentVersion | None = None
    ) -> PreviewOut:
        """Presigned URL of the current file, or of the older version `source`."""
        expires = self.settings.presign_expiry_seconds
        key = source.minio_key if source else doc.minio_key
        filename = source.filename if source else doc.filename
        mime_type = source.mime_type if source else doc.mime_type
        version = source.version if source else doc.version
        url = self.storage.presign_get(
            key,
            expires,
            filename=filename,
            content_type=mime_type if attachment else _preview_type(mime_type),
            attachment=attachment,
        )
        await self.audit.record(
            self.audit_ctx,
            "document.download" if attachment else "document.preview",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"kb_id": doc.kb_id, "version": version, "filename": filename},
        )
        return PreviewOut(url=url, filename=filename, mime_type=mime_type, expires_in=expires)

    # ---- versions ----

    async def _version_text(self, row: DocumentVersion) -> tuple[list[str], bool] | None:
        key = parsed_key(row.minio_key)
        if await self.storage.stat(key) is None:
            return None
        parsed = ParsedDocument.from_dict(json.loads(await self.storage.get_bytes(key)))
        settings = self.settings
        masker = (
            PiiMasker(settings.pii_types)
            if settings.pii_mask_on_ingest or settings.pii_mask_on_output
            else None
        )
        return document_lines(parsed, masker.mask if masker else None)

    async def version_text(self, document_id: str, version: int) -> VersionTextOut:
        doc, _, _ = await self._doc(document_id, AclPermission.READ)
        row = await self._version(doc, version)
        text = await self._version_text(row)
        await self.audit.record(
            self.audit_ctx,
            "document.version_view",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"kb_id": doc.kb_id, "version": version},
        )
        if text is None:
            return VersionTextOut(version=version, available=False)
        lines, truncated = text
        return VersionTextOut(version=version, available=True, lines=lines, truncated=truncated)

    async def compare_versions(self, document_id: str, base: int, target: int) -> VersionCompareOut:
        doc, _, _ = await self._doc(document_id, AclPermission.READ)
        old_row, new_row = await self._version(doc, base), await self._version(doc, target)
        rows = await self._version_outs([old_row, new_row])
        await self.audit.record(
            self.audit_ctx,
            "document.version_compare",
            RESOURCE_DOCUMENT,
            doc.id,
            None,
            {"kb_id": doc.kb_id, "base": base, "target": target},
        )
        out = VersionCompareOut(
            base=rows[0],
            target=rows[1],
            available=False,
            same_file=old_row.sha256 == new_row.sha256,
        )
        old_text, new_text = await self._version_text(old_row), await self._version_text(new_row)
        if old_text is None or new_text is None:
            return out
        diff = await asyncio.to_thread(diff_lines, old_text[0], new_text[0])
        return out.model_copy(
            update={
                "available": True,
                "added": diff.added,
                "removed": diff.removed,
                "truncated": diff.truncated or old_text[1] or new_text[1],
                "hunks": [[DiffLineOut(**asdict(line)) for line in hunk] for hunk in diff.hunks],
            }
        )

    async def restore_version(self, document_id: str, version: int) -> DocumentOut:
        """Make an older version current again by copying it into a new version."""
        doc, kb, perm = await self._doc(document_id, AclPermission.EDIT)
        row = await self._version(doc, version)
        if version == doc.version:
            raise ConflictError("This version is already the current one")
        twin = await self.repo.find_by_sha256(self.org_id, kb.id, row.sha256)
        if twin is not None and twin.id != doc.id:
            raise ConflictError(
                "Another document in this knowledge base has the same content",
                detail={"document_id": twin.id, "title": twin.title},
            )
        if await self.storage.stat(row.minio_key) is None:
            raise NotFoundError("The file of this version is no longer stored")
        before = snapshot(doc)
        self._advance(doc, mime_type=row.mime_type, size_bytes=row.size_bytes, sha256=row.sha256)
        mark_reviewed(kb, doc, self.ctx.user.id, utcnow())
        doc.minio_key = self._file_key(doc, row.filename)
        await self.storage.copy(row.minio_key, doc.minio_key)
        await self.repo.add_version(
            DocumentVersion(
                org_id=self.org_id,
                document_id=doc.id,
                version=doc.version,
                filename=row.filename,
                mime_type=row.mime_type,
                size_bytes=row.size_bytes,
                sha256=row.sha256,
                minio_key=doc.minio_key,
                restored_from=version,
                created_by=self.ctx.user.id,
            )
        )
        await self.session.flush()
        after = snapshot(doc)
        await self.audit.record(
            self.audit_ctx,
            "document.restore_version",
            RESOURCE_DOCUMENT,
            doc.id,
            before,
            {**after, "restored_from": version} if after else None,
        )
        self._enqueue_parse(doc)
        return self._out(doc, perm, kb)

    # ---- write ----

    async def update(self, document_id: str, data: DocumentUpdate) -> DocumentOut:
        doc, kb, perm = await self._doc(document_id, AclPermission.EDIT)
        before = snapshot(doc)
        fields = data.model_fields_set
        protection_fields = fields & {"watermark", "copy_protect", "download_permission"}
        if protection_fields:
            if perm.level < AclPermission.MANAGE.level:
                raise PermissionDeniedError("Changing document protection needs manage permission")
            for name in protection_fields:
                setattr(doc, name, getattr(data, name))
        if data.title is not None:
            doc.title = data.title
        if data.tags is not None:
            doc.tags = data.tags
        if data.metadata is not None:
            parse_info = doc.meta.get("parse")
            doc.meta = {**data.metadata, **({"parse": parse_info} if parse_info else {})}
        if "effective_from" in fields:
            doc.effective_from = data.effective_from
        if "effective_to" in fields:
            doc.effective_to = data.effective_to
        if "owner_id" in fields and data.owner_id != doc.owner_id:
            if data.owner_id is not None:
                await self._check_owner(doc, kb, data.owner_id)
            doc.owner_id = data.owner_id
        if "review_interval_days" in fields:
            doc.review_interval_days = data.review_interval_days
            refresh_due(kb, doc)
        if (
            doc.effective_from
            and doc.effective_to
            and _aware(doc.effective_from) > _aware(doc.effective_to)
        ):
            raise ValidationAppError("effective_from must be earlier than effective_to")
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "document.update", RESOURCE_DOCUMENT, doc.id, before, snapshot(doc)
        )
        (out,) = await self._with_owner_names([self._out(doc, perm, kb)])
        return out

    async def _check_owner(self, doc: Document, kb: KnowledgeBase, owner_id: str) -> None:
        """The owner must be an active member who can edit the document."""
        owner = await UserRepository(self.session).get(self.org_id, owner_id)
        if owner is None or not owner.is_active:
            raise ValidationAppError("Owner not found", code="OWNER_INVALID")
        principals = await PrincipalResolver(self.session, self.authz_cache).resolve(
            self.org_id, owner.id
        )
        as_owner = CurrentUser(
            id=owner.id,
            org_id=self.org_id,
            username=owner.username,
            display_name=owner.display_name,
            principals=principals,
            permissions=await PermissionResolver(self.session, self.authz_cache).resolve(
                principals
            ),
        )
        perm = await self.access.document_permission(as_owner, doc, kb)
        if perm is None or perm.level < AclPermission.EDIT.level:
            raise ValidationAppError(
                "The owner needs edit permission on this document",
                code="OWNER_NO_EDIT",
                detail={"owner_id": owner_id},
            )

    async def review(self, document_id: str, data: DocumentReviewIn) -> DocumentOut:
        """Confirm the document is still accurate: the review clock starts again."""
        doc, kb, perm = await self._doc(document_id, AclPermission.EDIT)
        before = {"reviewed_at": doc.reviewed_at, "review_due_at": doc.review_due_at}
        mark_reviewed(kb, doc, self.ctx.user.id, utcnow())
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx,
            "document.review",
            RESOURCE_DOCUMENT,
            doc.id,
            snapshot(before),
            snapshot(
                {
                    "reviewed_at": doc.reviewed_at,
                    "review_due_at": doc.review_due_at,
                    "note": data.note,
                }
            ),
        )
        (out,) = await self._with_owner_names([self._out(doc, perm, kb)])
        return out

    async def delete(self, document_id: str) -> None:
        doc, kb, _ = await self._doc(document_id, AclPermission.EDIT)
        before = snapshot(doc)
        doc.deleted_at = utcnow()
        doc.deleted_by = self.ctx.user.id
        await OutboxService(self.session).publish(
            self.org_id,
            RESOURCE_DOCUMENT,
            doc.id,
            DOCUMENT_DELETED,
            {"document_id": doc.id, "kb_id": kb.id, "version": doc.version},
        )
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "document.delete", RESOURCE_DOCUMENT, doc.id, before, snapshot(doc)
        )

    async def reprocess(self, document_id: str) -> DocumentOut:
        doc, kb, perm = await self._doc(document_id, AclPermission.EDIT)
        if doc.status == DocumentStatus.PARSING.value:
            raise ConflictError("Document is being parsed")
        before = snapshot(doc)
        doc.status = DocumentStatus.UPLOADED.value
        doc.error_message = None
        await self.session.flush()
        await self.audit.record(
            self.audit_ctx, "document.reprocess", RESOURCE_DOCUMENT, doc.id, before, snapshot(doc)
        )
        self._enqueue_parse(doc)
        return self._out(doc, perm, kb)

    # ---- ACL ----

    async def get_acl(self, document_id: str) -> DocumentAclOut:
        doc, kb, _ = await self._doc(document_id, AclPermission.MANAGE)
        directory = PrincipalDirectory(self.session, self.org_id)
        kb_rows = await self.access.entries(self.org_id, RESOURCE_KB, kb.id)
        doc_rows = await self.access.entries(self.org_id, RESOURCE_DOCUMENT, doc.id)
        return DocumentAclOut(
            inherit=doc.acl_inherit,
            kb_visibility=kb.visibility,
            kb_entries=await directory.describe(
                (r.principal_type, r.principal_id, r.permission) for r in kb_rows
            ),
            entries=await directory.describe(
                (r.principal_type, r.principal_id, r.permission) for r in doc_rows
            ),
        )

    async def set_acl(self, document_id: str, data: DocumentAclUpdate) -> DocumentAclOut:
        doc, kb, _ = await self._doc(document_id, AclPermission.MANAGE)
        entries = await PrincipalDirectory(self.session, self.org_id).validate(data.entries)
        new_rows = (
            []
            if data.inherit
            else [(e.principal_type, e.principal_id, e.permission) for e in entries]
        )
        old_rows = [
            (r.principal_type, r.principal_id, r.permission)
            for r in await self.access.entries(self.org_id, RESOURCE_DOCUMENT, doc.id)
        ]
        before = {"inherit": doc.acl_inherit, "entries": _entry_strings(old_rows)}
        doc.acl_inherit = data.inherit
        await self.access.replace_entries(
            self.org_id, RESOURCE_DOCUMENT, doc.id, new_rows, self.ctx.user.id
        )
        after = {"inherit": doc.acl_inherit, "entries": _entry_strings(new_rows)}
        if before != after:
            await OutboxService(self.session).publish(
                self.org_id,
                RESOURCE_DOCUMENT,
                doc.id,
                ACL_CHANGED,
                {"resource_type": RESOURCE_DOCUMENT, "resource_id": doc.id, "kb_id": kb.id},
            )
        await self.audit.record(
            self.audit_ctx, "document.set_acl", RESOURCE_DOCUMENT, doc.id, before, after
        )
        return await self.get_acl(doc.id)
