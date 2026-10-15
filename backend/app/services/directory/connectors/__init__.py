from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.models import DirectorySourceType
from app.services.directory.connectors.base import ConnectorError, DirectoryConnector
from app.services.directory.connectors.dingtalk import DingTalkConfig, DingTalkConnector
from app.services.directory.connectors.excel import ExcelConfig, ExcelConnector
from app.services.directory.connectors.weaver import WeaverConfig, WeaverConnector
from app.services.directory.connectors.wecom import WeComConfig, WeComConnector

CONNECTORS: dict[str, type[DirectoryConnector]] = {
    DirectorySourceType.WECOM: WeComConnector,
    DirectorySourceType.DINGTALK: DingTalkConnector,
    DirectorySourceType.WEAVER: WeaverConnector,
    DirectorySourceType.EXCEL: ExcelConnector,
}
CONFIG_MODELS: dict[str, type[BaseModel]] = {
    DirectorySourceType.WECOM: WeComConfig,
    DirectorySourceType.DINGTALK: DingTalkConfig,
    DirectorySourceType.WEAVER: WeaverConfig,
    DirectorySourceType.EXCEL: ExcelConfig,
}


def build_connector(
    source_type: str,
    config: dict[str, Any],
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    upload: bytes | None = None,
) -> DirectoryConnector:
    if source_type == DirectorySourceType.EXCEL:
        return ExcelConnector(config, settings, content=upload)
    if source_type == DirectorySourceType.WEAVER:
        return WeaverConnector(config, settings)
    if source_type == DirectorySourceType.WECOM:
        return WeComConnector(config, settings, transport=transport)
    if source_type == DirectorySourceType.DINGTALK:
        return DingTalkConnector(config, settings, transport=transport)
    raise ConnectorError(f"Unknown directory source type: {source_type}", status_code=400)


__all__ = [
    "CONFIG_MODELS",
    "CONNECTORS",
    "ConnectorError",
    "DirectoryConnector",
    "build_connector",
]
