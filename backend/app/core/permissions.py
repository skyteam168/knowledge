from collections.abc import Iterable

WILDCARD = "*"

PERMISSION_CATALOG: dict[str, str] = {
    "kb:create": "创建知识库",
    "kb:read": "查看知识库",
    "kb:update": "编辑知识库",
    "kb:delete": "删除知识库",
    "doc:upload": "上传文档",
    "doc:delete": "删除文档",
    "review:approve": "审核通过",
    "gap:review": "处理知识缺口",
    "ko:edit": "编辑知识条目",
    "chat:use": "使用 AI 助手",
    "search:use": "使用搜索",
    "analytics:view": "查看分析",
    "analytics:usage": "查看模型用量（含每人 token 消耗）",
    "admin:org": "管理组织信息",
    "admin:dept": "管理部门",
    "admin:user": "管理用户",
    "admin:group": "管理用户组",
    "admin:role": "管理角色与授权",
    "admin:audit": "查看审计日志",
    "admin:index": "管理索引同步",
    "admin:retrieval": "管理检索策略与检索调试",
    "admin:openapi": "管理开放平台（外部 Agent 接入）",
    "admin:directory": "管理组织架构同步与扫码登录",
    "admin:model": "管理模型（提供方、模型检测、对话模型切换）",
    "admin:*": "全部管理权限",
    "*": "超级权限",
}

DEFAULT_ROLES: dict[str, tuple[str, list[str]]] = {
    "kb_admin": ("知识库管理员", [WILDCARD]),
    "kb_editor": (
        "知识库编辑者",
        [
            "kb:create",
            "kb:read",
            "kb:update",
            "doc:upload",
            "gap:review",
            "ko:edit",
            "chat:use",
            "search:use",
            "analytics:view",
        ],
    ),
    "kb_viewer": ("知识库只读用户", ["kb:read", "chat:use", "search:use"]),
}
DEFAULT_ROLE_CODES = frozenset({"kb_viewer"})


def is_privileged(codes: Iterable[str]) -> bool:
    """Superuser or administration permissions: never granted implicitly or in bulk."""
    return any(c == WILDCARD or c.startswith("admin:") for c in codes)


def has_permission(granted: Iterable[str], required: str) -> bool:
    """`*` grants everything; `prefix:*` grants every `prefix:xxx`."""
    granted_set = set(granted)
    if WILDCARD in granted_set or required in granted_set:
        return True
    prefix = required.split(":", 1)[0]
    return f"{prefix}:*" in granted_set


def has_any_permission(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted_set = set(granted)
    return any(has_permission(granted_set, r) for r in required)
