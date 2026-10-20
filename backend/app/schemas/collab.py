from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ResourceType = Literal["document", "kb"]


class SavedItemOut(BaseModel):
    """A favorite or recently viewed item the caller can still read."""

    resource_type: ResourceType
    resource_id: str
    title: str
    kb_id: str
    kb_name: str
    filename: str | None = None
    link: str
    at: datetime


class FavoriteStateOut(BaseModel):
    favorited: bool


class RecentViewIn(BaseModel):
    resource_type: ResourceType
    resource_id: str = Field(min_length=1, max_length=32)


# ---- comments -------------------------------------------------------------------------


class MentionOut(BaseModel):
    id: str
    name: str


class CommentOut(BaseModel):
    id: str
    parent_id: str | None
    author_id: str
    author_name: str
    body: str
    mentions: list[MentionOut] = Field(default_factory=list)
    document_version: int
    created_at: datetime
    edited: bool = False
    resolved_at: datetime | None = None
    resolved_by_name: str | None = None
    deleted: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_resolve: bool = False
    replies: list["CommentOut"] = Field(default_factory=list)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: str | None = Field(default=None, max_length=32)
    mentions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("body")
    @classmethod
    def _strip(cls, body: str) -> str:
        body = body.strip()
        if not body:
            raise ValueError("Comment is empty")
        return body


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _strip(cls, body: str) -> str:
        body = body.strip()
        if not body:
            raise ValueError("Comment is empty")
        return body


class CommentResolveIn(BaseModel):
    resolved: bool = True
