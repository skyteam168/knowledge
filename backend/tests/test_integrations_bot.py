"""Unit tests for WeCom / DingTalk group-bot helpers (stage 1)."""

from __future__ import annotations

import pytest

from app.api.v1 import integrations_bot as bot_api
from app.core.config import Settings
from app.core.exceptions import UnauthorizedError, ValidationAppError
from app.schemas.open_api import OpenChatOut
from app.services.integrations.bot_qa import (
    citation_label,
    format_bot_reply,
    open_chat_in,
    parse_dingtalk_question,
    parse_wecom_question,
    reply_from_chat_out,
)


def test_parse_wecom_content_field() -> None:
    assert parse_wecom_question({"MsgType": "text", "Content": " 织机保养周期 "}) == "织机保养周期"


def test_parse_wecom_mock_question() -> None:
    assert parse_wecom_question({"question": "hello"}) == "hello"


def test_parse_wecom_skips_image() -> None:
    assert parse_wecom_question({"MsgType": "image", "Content": "x"}) is None


def test_parse_dingtalk_nested_text() -> None:
    assert (
        parse_dingtalk_question({"text": {"content": "@bot 断纱怎么处理"}}) == "@bot 断纱怎么处理"
    )


def test_parse_dingtalk_mock_question() -> None:
    assert parse_dingtalk_question({"question": "q1"}) == "q1"


def test_format_bot_reply_includes_citations() -> None:
    reply = format_bot_reply(
        "答案正文",
        [
            {"title": "织造手册", "document_id": "d1"},
            {"document_title": "保养规程", "document_id": "d2"},
        ],
        max_citations=5,
    )
    assert "答案正文" in reply
    assert "[1] 织造手册" in reply
    assert "[2] 保养规程" in reply


def test_format_bot_reply_truncates_answer() -> None:
    reply = format_bot_reply("abcdefghij", [], max_answer_chars=5)
    assert reply.endswith("…")
    assert len(reply) <= 5


def test_format_bot_reply_limits_citations() -> None:
    cites = [{"title": f"t{i}"} for i in range(10)]
    reply = format_bot_reply("a", cites, max_citations=2)
    assert "[1] t0" in reply
    assert "[2] t1" in reply
    assert "[3]" not in reply


def test_citation_label_fallback() -> None:
    assert citation_label({"document_id": "abc"}) == "abc"
    assert citation_label({}) == "来源"


def test_reply_from_chat_out() -> None:
    out = OpenChatOut(
        conversation_id="c1",
        message_id="m1",
        answer="OK",
        grounding="confident",
        citations=[{"title": "Doc A"}],
        steps=[],
        trace_id="t1",
    )
    assert "[1] Doc A" in reply_from_chat_out(out)


def test_open_chat_in_non_stream() -> None:
    data = open_chat_in("q", ["kb1"])
    assert data.stream is False
    assert data.question == "q"
    assert data.kb_ids == ["kb1"]


def test_require_bot_disabled() -> None:
    with pytest.raises(ValidationAppError) as exc:
        bot_api._require_bot(Settings(integrations_bot_enabled=False))
    assert exc.value.code == "BOT_DISABLED"


def test_require_bot_missing_token() -> None:
    with pytest.raises(ValidationAppError) as exc:
        bot_api._require_bot(
            Settings(
                integrations_bot_enabled=True,
                integrations_bot_token="",
                integrations_bot_open_api_key="ekb_live_x",
            )
        )
    assert exc.value.code == "BOT_NOT_CONFIGURED"


def test_check_token_accepts_header() -> None:
    settings = Settings(integrations_bot_token="secret-bot")
    bot_api._check_token(settings, x_bot_token="secret-bot", authorization=None)


def test_check_token_rejects_bad() -> None:
    settings = Settings(integrations_bot_token="secret-bot")
    with pytest.raises(UnauthorizedError):
        bot_api._check_token(settings, x_bot_token="wrong", authorization=None)
