"""Model Context Protocol (Streamable HTTP, JSON responses) for external agents.

Tools follow the client's scopes: list_knowledge_bases always, search_knowledge with
`retrieve`, ask_knowledge with `chat`. Business errors are returned as tool results with
isError=true (visible to the model); protocol errors as JSON-RPC errors.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.models import ApiScope
from app.schemas.open_api import OpenChatIn, OpenRetrieveIn
from app.services.open_api.open_service import OpenApiService

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "ekb-knowledge", "title": "企业知识库", "version": "1.0.0"}
INSTRUCTIONS = (
    "企业知识库工具。先用 list_knowledge_bases 查看可访问的知识库；"
    "用 search_knowledge 检索原文片段（带出处，适合自行组织回答）；"
    "用 ask_knowledge 直接获得带引用的回答。只能访问管理员授权的知识库。"
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

KB_IDS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "限定的知识库 id，留空表示全部已授权知识库",
}

TOOLS: dict[str, dict[str, Any]] = {
    "list_knowledge_bases": {
        "name": "list_knowledge_bases",
        "title": "列出知识库",
        "description": "列出当前 Agent 被授权访问的知识库（id、名称、描述）。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    "search_knowledge": {
        "name": "search_knowledge",
        "title": "检索知识",
        "description": "在授权知识库中做混合检索与重排，返回最相关的原文片段及出处。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索问题或关键词"},
                "kb_ids": KB_IDS_SCHEMA,
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "ask_knowledge": {
        "name": "ask_knowledge",
        "title": "知识问答",
        "description": "基于授权知识库回答问题，答案带 [n] 引用；资料不足时会明确拒答。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "问题"},
                "kb_ids": KB_IDS_SCHEMA,
                "conversation_id": {
                    "type": "string",
                    "description": "继续之前的多轮对话（上次返回的 conversation_id）",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
}

TOOL_SCOPES = {"search_knowledge": ApiScope.RETRIEVE, "ask_knowledge": ApiScope.CHAT}

Recorder = Callable[[str, dict[str, Any]], Awaitable[None]]


class McpServer:
    def __init__(self, service: OpenApiService, on_tool: Recorder | None = None) -> None:
        self.service = service
        self.on_tool = on_tool

    def _tools(self) -> list[dict[str, Any]]:
        scopes = self.service.caller.scopes
        return [
            tool
            for name, tool in TOOLS.items()
            if name not in TOOL_SCOPES or TOOL_SCOPES[name].value in scopes
        ]

    async def handle(self, payload: Any) -> Any:
        """Returns the JSON-RPC response (list for batches), or None for notifications only."""
        if isinstance(payload, list):
            if not payload:
                return _error(None, INVALID_REQUEST, "Empty batch")
            responses = [r for r in [await self._one(m) for m in payload] if r is not None]
            return responses or None
        return await self._one(payload)

    async def _one(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "Invalid JSON-RPC 2.0 message")
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str):
            # A response sent by the client (we never issue requests): ignore.
            return None
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return (
                None
                if is_notification
                else _error(msg_id, INVALID_PARAMS, "params must be an object")
            )
        try:
            result = await self._dispatch(method, params)
        except _RpcError as exc:
            return None if is_notification else _error(msg_id, exc.code, exc.message)
        except Exception:
            logger.exception("mcp_internal_error", extra={"method": method})
            return None if is_notification else _error(msg_id, INTERNAL_ERROR, "Internal error")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    async def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
            return {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            }
        if method.startswith("notifications/"):
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._tools()}
        if method == "tools/call":
            return await self._call(params)
        raise _RpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

    async def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(name, str) or name not in {t["name"] for t in self._tools()}:
            raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            raise _RpcError(INVALID_PARAMS, "arguments must be an object")
        try:
            data = await self._run_tool(name, args)
        except ValidationError as exc:
            return _tool_error(f"参数错误：{exc.errors(include_url=False)}")
        except AppError as exc:
            if self.on_tool:
                await self.on_tool(name, {"error_code": exc.code, "status_code": exc.status_code})
            return _tool_error(
                f"{exc.code}: {exc.message}", {"code": exc.code, "detail": exc.detail}
            )
        return {
            "content": [
                {"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}
            ],
            "structuredContent": data,
            "isError": False,
        }

    async def _run_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        service = self.service
        if name == "list_knowledge_bases":
            kbs = await service.knowledge_bases()
            data: dict[str, Any] = {"knowledge_bases": [kb.model_dump() for kb in kbs]}
            if self.on_tool:
                await self.on_tool(name, {"result_count": len(kbs)})
            return data
        if name == "search_knowledge":
            service.caller.require_scope(ApiScope.RETRIEVE)
            out = await service.retrieve(OpenRetrieveIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": out.query,
                        "kb_ids": out.kb_ids,
                        "result_count": out.total,
                        "document_ids": list(dict.fromkeys(i.document_id for i in out.items)),
                        "trace_id": out.trace_id,
                    },
                )
            return out.model_dump(mode="json")
        service.caller.require_scope(ApiScope.CHAT)
        chat, outcome = await service.chat(OpenChatIn.model_validate({**args, "stream": False}))
        if self.on_tool:
            await self.on_tool(
                name,
                {
                    "query": args.get("question"),
                    "result_count": len(chat.citations),
                    "document_ids": outcome.document_ids,
                    "trace_id": chat.trace_id,
                },
            )
        return chat.model_dump(mode="json")


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_error(text: str, structured: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": True}
    if structured is not None:
        result["structuredContent"] = structured
    return result
