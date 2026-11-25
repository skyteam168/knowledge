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
from app.schemas.open_api import (
    OpenActionApproveIn,
    OpenActionInvokeIn,
    OpenAggregateObjectsIn,
    OpenChatIn,
    OpenEntityReadIn,
    OpenGetObjectIn,
    OpenGraphTraverseIn,
    OpenQueryObjectsIn,
    OpenRetrieveIn,
    OpenTraverseIn,
)
from app.services.open_api.open_service import OpenApiService

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "ekb-knowledge", "title": "企业知识库", "version": "1.0.0"}
INSTRUCTIONS = (
    "企业知识库工具。先用 list_knowledge_bases 查看可访问的知识库；"
    "用 describe_ontology 了解类/属性/关系合约；用 query_objects / get_object 查结构化对象；"
    "用 aggregate_objects 计数（如停机次数）；用 traverse 做有向多跳；也可用 entity_read / graph_traverse；"
    "用 list_actions / invoke_action 做受控写操作（高风险需先 approve）；"
    "用 search_knowledge 检索原文片段；用 ask_knowledge 获得带引用回答。只能访问授权知识库。"
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
        "description": (
            "在授权知识库中做混合检索与重排，返回最相关的原文片段及出处；"
            "若文档有页/幻灯片附图，条目含可访问的 image_url（签名链接，会过期）。"
        ),
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
        "description": (
            "基于授权知识库回答问题，答案带 [n] 引用；资料不足时会明确拒答。"
            "答案中可能含 Markdown 图片；citations 中含 image_url（签名链接，会过期）。"
        ),
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
    "entity_read": {
        "name": "entity_read",
        "title": "读取实体",
        "description": (
            "按术语 id、名称/别名，或结构化外部编号（object_type+external_id）读取概念元数据；"
            "可返回关联的已授权知识条目（仅 id/title，无正文）。三选一查询。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_id": {"type": "string", "description": "术语实体 id"},
                "name": {"type": "string", "description": "术语规范名或别名"},
                "object_type": {
                    "type": "string",
                    "description": "结构化对象类型，如 device / recipe",
                },
                "external_id": {"type": "string", "description": "外部系统编号"},
                "source_id": {"type": "string", "description": "可选数据源 id"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "graph_traverse": {
        "name": "graph_traverse",
        "title": "遍历知识关系图",
        "description": (
            "从已发布知识条目出发，沿 ko_relations 有向多跳（direction=out|in|both），"
            "返回授权范围内可读的邻居条目（id/title/path）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ko_id": {"type": "string", "description": "起始知识条目 id"},
                "max_hops": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                    "default": 2,
                    "description": "最大跳数",
                },
                "direction": {
                    "type": "string",
                    "enum": ["out", "in", "both"],
                    "default": "both",
                },
                "relation_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选关系类型过滤",
                },
                "kb_ids": KB_IDS_SCHEMA,
            },
            "required": ["ko_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "describe_ontology": {
        "name": "describe_ontology",
        "title": "描述本体合约",
        "description": (
            "返回平台 TBox + 已发布组织语义。默认 scope=summary（类/关系/约束，不含全量 attrs）；"
            "scope=attributes|equipment|all 时才返回属性；version=published|platform。"
            "草稿版本对 Agent 不可见。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": [
                        "summary",
                        "classes",
                        "relations",
                        "attributes",
                        "equipment",
                        "all",
                    ],
                    "default": "summary",
                },
                "version": {
                    "type": "string",
                    "description": "published | platform | <published version_id>",
                    "default": "published",
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "get_object": {
        "name": "get_object",
        "title": "获取结构化对象",
        "description": (
            "按 object_type + object_id 或 external_id 读取结构化/设备对象属性，"
            "可选返回 object_relations 邻居。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string"},
                "object_id": {"type": "string"},
                "external_id": {"type": "string"},
                "source_id": {"type": "string"},
                "include_neighbors": {"type": "boolean", "default": True},
                "neighbor_hops": {"type": "integer", "minimum": 0, "maximum": 3, "default": 1},
            },
            "required": ["object_type"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "query_objects": {
        "name": "query_objects",
        "title": "查询结构化对象",
        "description": (
            "按类型与可选条件分页筛选对象。"
            "事件可用 event_type、occurred_from、occurred_to（ISO-8601）做时间窗过滤。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string"},
                "status": {"type": "string"},
                "q": {"type": "string"},
                "line_external_id": {"type": "string"},
                "equipment_external_id": {"type": "string"},
                "event_type": {
                    "type": "string",
                    "description": "alarm|downtime|quality|other",
                },
                "occurred_from": {
                    "type": "string",
                    "description": "ISO-8601；含该时刻起",
                },
                "occurred_to": {
                    "type": "string",
                    "description": "ISO-8601；不含该时刻",
                },
                "page": {"type": "integer", "minimum": 1, "default": 1},
                "size": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["object_type"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "aggregate_objects": {
        "name": "aggregate_objects",
        "title": "结构化对象聚合",
        "description": (
            "对结构化对象做计数（如某设备上周停机次数）。"
            "metric=count；可按 event_type、设备、时间窗过滤；结果经 ACL 过滤。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_type": {"type": "string"},
                "metric": {"type": "string", "enum": ["count"], "default": "count"},
                "status": {"type": "string"},
                "event_type": {"type": "string"},
                "equipment_external_id": {"type": "string"},
                "line_external_id": {"type": "string"},
                "occurred_from": {"type": "string"},
                "occurred_to": {"type": "string"},
            },
            "required": ["object_type"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "traverse": {
        "name": "traverse",
        "title": "有向遍历",
        "description": (
            "统一有向遍历：mode=ko 走知识条目关系；mode=object 走工业 object_relations。"
            "支持 direction 与 relation_types。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["ko", "object"], "default": "ko"},
                "ko_id": {"type": "string"},
                "kind": {"type": "string", "description": "object 模式：terminology|ko|structured"},
                "object_id": {"type": "string"},
                "object_type": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["out", "in", "both"],
                    "default": "out",
                },
                "relation_types": {"type": "array", "items": {"type": "string"}},
                "max_hops": {"type": "integer", "minimum": 1, "maximum": 3, "default": 2},
                "kb_ids": KB_IDS_SCHEMA,
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
    },
    "list_actions": {
        "name": "list_actions",
        "title": "列出可用 Action",
        "description": (
            "返回本组织已启用的 Ontology Action 类型（名称、input_schema、risk、systems）。"
            "写操作需 action scope；高风险 Action 执行前须先 approve。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True},
    },
    "approve_action": {
        "name": "approve_action",
        "title": "审批高风险 Action",
        "description": (
            "为高风险 Action 创建单次 30 分钟审批令牌；必须 acknowledge_risk=true；"
            "随后 invoke_action 携带 approval_id，且 input 须与审批时一致。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string"},
                "input": {"type": "object"},
                "acknowledge_risk": {"type": "boolean", "default": False},
            },
            "required": ["action_type", "input", "acknowledge_risk"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    "invoke_action": {
        "name": "invoke_action",
        "title": "执行 Ontology Action",
        "description": (
            "受控写：按 action_type + input 执行；必须带 idempotency_key；"
            "高风险或缺审批时返回 awaiting_approval；可 dry_run 预览。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action_type": {"type": "string"},
                "input": {"type": "object"},
                "idempotency_key": {"type": "string"},
                "approval_id": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": ["action_type", "input", "idempotency_key"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
}

TOOL_SCOPES = {
    "search_knowledge": ApiScope.RETRIEVE,
    "ask_knowledge": ApiScope.CHAT,
    "entity_read": ApiScope.ENTITY,
    "graph_traverse": ApiScope.ENTITY,
    "describe_ontology": ApiScope.ENTITY,
    "get_object": ApiScope.ENTITY,
    "query_objects": ApiScope.ENTITY,
    "aggregate_objects": ApiScope.ENTITY,
    "traverse": ApiScope.ENTITY,
    "list_actions": ApiScope.ACTION,
    "approve_action": ApiScope.ACTION,
    "invoke_action": ApiScope.ACTION,
}

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
        if name == "ask_knowledge":
            service.caller.require_scope(ApiScope.CHAT)
            chat, outcome = await service.chat(
                OpenChatIn.model_validate({**args, "stream": False})
            )
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
        if name == "entity_read":
            service.caller.require_scope(ApiScope.ENTITY)
            entity = await service.entity_read(OpenEntityReadIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": args.get("entity_id")
                        or args.get("name")
                        or f"{args.get('object_type')}:{args.get('external_id')}",
                        "result_count": len(entity.knowledge_objects),
                        "document_ids": [k.id for k in entity.knowledge_objects],
                    },
                )
            return entity.model_dump(mode="json")
        if name == "graph_traverse":
            service.caller.require_scope(ApiScope.ENTITY)
            graph = await service.graph_traverse(OpenGraphTraverseIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": args.get("ko_id"),
                        "kb_ids": args.get("kb_ids") or [],
                        "result_count": len(graph.neighbors),
                        "document_ids": [graph.seed.id, *[n.ko_id for n in graph.neighbors]],
                    },
                )
            return graph.model_dump(mode="json")
        if name == "describe_ontology":
            service.caller.require_scope(ApiScope.ENTITY)
            out = await service.describe_ontology(
                scope=str(args.get("scope") or "summary"),
                version=str(args.get("version") or "published"),
            )
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": f"{out.scope}:{out.version}",
                        "result_count": len(out.classes),
                    },
                )
            return out.model_dump(mode="json")
        if name == "get_object":
            service.caller.require_scope(ApiScope.ENTITY)
            obj = await service.get_object(OpenGetObjectIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": f"{obj.object_type}:{obj.external_id}",
                        "result_count": 1 + len(obj.neighbors),
                    },
                )
            return obj.model_dump(mode="json")
        if name == "query_objects":
            service.caller.require_scope(ApiScope.ENTITY)
            page = await service.query_objects(OpenQueryObjectsIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {"query": args.get("object_type"), "result_count": len(page.items)},
                )
            return page.model_dump(mode="json")
        if name == "aggregate_objects":
            service.caller.require_scope(ApiScope.ENTITY)
            agg = await service.aggregate_objects(
                OpenAggregateObjectsIn.model_validate(args)
            )
            if self.on_tool:
                await self.on_tool(
                    name,
                    {"query": args.get("object_type"), "result_count": agg.value},
                )
            return agg.model_dump(mode="json")
        if name == "traverse":
            service.caller.require_scope(ApiScope.ENTITY)
            trav = await service.traverse(OpenTraverseIn.model_validate(args))
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": args.get("ko_id") or args.get("object_id"),
                        "result_count": len(trav.neighbors),
                    },
                )
            return trav.model_dump(mode="json")
        if name == "list_actions":
            service.caller.require_scope(ApiScope.ACTION)
            listed = await service.list_actions()
            if self.on_tool:
                await self.on_tool(
                    name,
                    {"query": "actions", "result_count": len(listed.items)},
                )
            return listed.model_dump(mode="json")
        if name == "approve_action":
            service.caller.require_scope(ApiScope.ACTION)
            approved = await service.approve_action(
                OpenActionApproveIn.model_validate(args)
            )
            if self.on_tool:
                await self.on_tool(
                    name,
                    {"query": args.get("action_type"), "result_count": 1},
                )
            return approved.model_dump(mode="json")
        if name == "invoke_action":
            service.caller.require_scope(ApiScope.ACTION)
            invoked = await service.invoke_action(
                OpenActionInvokeIn.model_validate(args)
            )
            if self.on_tool:
                await self.on_tool(
                    name,
                    {
                        "query": args.get("action_type"),
                        "result_count": 1 if invoked.execution_id else 0,
                    },
                )
            return invoked.model_dump(mode="json")
        raise _RpcError(INVALID_PARAMS, f"Unknown tool: {name}")


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
