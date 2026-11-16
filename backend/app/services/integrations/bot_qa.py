"""Group-bot Q&A helpers: parse IM payloads, ask via Open API, format plain replies."""

from __future__ import annotations

from typing import Any

from app.schemas.open_api import OpenChatIn, OpenChatOut


def parse_wecom_question(payload: dict[str, Any]) -> str | None:
    """Extract text from a simplified WeCom callback / mock body.

    Stage-1 accepts either the plaintext XML-mapped JSON shape used by many
    gateways (`MsgType`/`Content`) or a local mock `{question|text|content}`.
    """
    msg_type = str(payload.get("MsgType") or payload.get("msgtype") or "").lower()
    if msg_type and msg_type not in {"text", ""}:
        return None
    for key in ("Content", "content", "question", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("content") or value.get("Content")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def parse_dingtalk_question(payload: dict[str, Any]) -> str | None:
    """Extract text from a DingTalk robot callback / local mock body."""
    text = payload.get("text")
    if isinstance(text, dict):
        content = text.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    for key in ("content", "question", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def citation_label(cite: dict[str, Any]) -> str:
    for key in ("title", "document_title", "source_title", "ko_title"):
        value = cite.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    doc_id = cite.get("document_id")
    return str(doc_id) if doc_id else "来源"


def format_bot_reply(
    answer: str,
    citations: list[dict[str, Any]] | None,
    *,
    max_answer_chars: int = 1200,
    max_citations: int = 5,
) -> str:
    """Plain-text reply suitable for WeCom / DingTalk group messages."""
    body = (answer or "").strip()
    if max_answer_chars > 0 and len(body) > max_answer_chars:
        body = body[: max_answer_chars - 1].rstrip() + "…"
    lines = [body] if body else ["（无回答）"]
    cites = list(citations or [])[: max(0, max_citations)]
    if cites:
        lines.append("")
        lines.append("引用：")
        for i, cite in enumerate(cites, start=1):
            lines.append(f"[{i}] {citation_label(cite)}")
    return "\n".join(lines).strip()


def open_chat_in(question: str, kb_ids: list[str] | None = None) -> OpenChatIn:
    return OpenChatIn(question=question, kb_ids=list(kb_ids or []), stream=False)


def reply_from_chat_out(
    out: OpenChatOut,
    *,
    max_answer_chars: int = 1200,
    max_citations: int = 5,
) -> str:
    return format_bot_reply(
        out.answer,
        out.citations,
        max_answer_chars=max_answer_chars,
        max_citations=max_citations,
    )
