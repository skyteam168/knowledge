"""Understanding stage: intent + task slots from the admin's message.

Native function calling first (the provider enforces the argument JSON); when the provider does
not support tools, or returns no call, fall back to a JSON-only answer. Either way the result is
validated against `Understanding` before anything else looks at it.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.llm import ChatMessage, LLMError, LLMGateway
from app.llm.usage import FEATURE_ADMIN_AGENT, usage_scope
from app.services.admin_agent import prompt
from app.services.admin_agent.tasks import TASKS

logger = logging.getLogger(__name__)

TOOL_NAME = "submit_understanding"
TIMEOUT_SECONDS = 60.0
Mode = Literal["tools", "json"]


@dataclass(frozen=True)
class UnderstandResult:
    understanding: prompt.Understanding
    mode: Mode


def understanding_tool() -> dict[str, Any]:
    """OpenAI tool spec; per-task slot schemas are in the system prompt catalog."""
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Submit the recognized intent and tasks of the admin's latest message.",
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {"type": "string", "description": "e.g. zh, en, vi"},
                    "intent": {
                        "type": "string",
                        "enum": ["query", "change", "mixed", "chitchat", "out_of_scope"],
                    },
                    "thought": {"type": "string"},
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": sorted(TASKS)},
                                "slots": {"type": "object"},
                            },
                            "required": ["type", "slots"],
                        },
                    },
                    "reply": {"type": "string"},
                },
                "required": ["language", "intent", "thought", "tasks"],
            },
        },
    }


class UnderstandError(AppError):
    code = "AGENT_UNDERSTAND_FAILED"
    message = "无法理解这条请求（模型输出不符合约定格式）"


async def _complete(gateway: LLMGateway, messages: list[ChatMessage], **options: Any) -> Any:
    try:
        with usage_scope(feature=FEATURE_ADMIN_AGENT):
            return await gateway.complete(
                messages, time_limit=TIMEOUT_SECONDS, temperature=0.0, max_tokens=2000, **options
            )
    except LLMError as exc:
        raise AppError("模型调用失败，请稍后重试", code="AGENT_LLM_UNAVAILABLE") from exc


async def understand(
    gateway: LLMGateway,
    history: list[ChatMessage],
    message: str,
    *,
    native_tools: bool = True,
    today: date | None = None,
) -> UnderstandResult:
    messages = prompt.understand_messages(TASKS.values(), history, message, today=today)
    if native_tools:
        try:
            with usage_scope(feature=FEATURE_ADMIN_AGENT):
                result = await gateway.complete(
                    messages,
                    time_limit=TIMEOUT_SECONDS,
                    temperature=0.0,
                    max_tokens=2000,
                    tools=[understanding_tool()],
                    tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
                )
        except LLMError as exc:
            logger.info("admin_agent_tools_unsupported", extra={"error": str(exc)[:200]})
        else:
            call = next((c for c in result.tool_calls if c.name == TOOL_NAME), None)
            try:
                if call is not None:
                    return UnderstandResult(
                        prompt.Understanding.model_validate_json(call.arguments), "tools"
                    )
                if result.content.strip():
                    return UnderstandResult(prompt.parse_understanding(result.content), "json")
            except (ValueError, ValidationError):
                logger.info("admin_agent_tool_output_invalid")
    # JSON mode: one retry with the validation error fed back.
    for attempt in range(2):
        raw = (await _complete(gateway, messages)).content
        try:
            return UnderstandResult(prompt.parse_understanding(raw), "json")
        except (ValueError, ValidationError) as exc:
            if attempt:
                raise UnderstandError() from exc
            messages = [
                *messages,
                ChatMessage("assistant", raw),
                ChatMessage(
                    "user",
                    f"Your output is invalid ({exc.__class__.__name__}). "
                    "Return only the JSON object.",
                ),
            ]
    raise UnderstandError()
