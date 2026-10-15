from abc import ABC, abstractmethod
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.directory.snapshot import Snapshot


class ConnectorError(AppError):
    status_code = 502
    code = "DIRECTORY_CONNECTOR_ERROR"
    message = "Directory source request failed"


class DirectoryConnector(ABC):
    """Reads a full directory snapshot from one source; never writes upstream."""

    config_model: ClassVar[type[BaseModel]]
    # Config fields that are write-only (never returned by the API).
    secret_fields: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: dict[str, Any], settings: Settings) -> None:
        self.settings = settings
        self.raw_config = config

    @abstractmethod
    async def fetch(self) -> Snapshot: ...

    async def test(self) -> dict[str, Any]:
        snap = (await self.fetch()).normalized()
        return {
            "departments": len(snap.departments),
            "users": len(snap.users),
            "active_users": sum(1 for u in snap.users if u.active),
            "warnings": snap.warnings[:20],
        }


class HttpConnector(DirectoryConnector):
    def __init__(
        self,
        config: dict[str, Any],
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, settings)
        self.transport = transport

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.settings.directory_http_timeout_seconds, transport=self.transport
        )

    @staticmethod
    async def json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise ConnectorError(
                f"HTTP {response.status_code}", detail={"body": response.text[:500]}
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError("Invalid JSON response", detail=response.text[:500]) from exc
        if not isinstance(data, dict):
            raise ConnectorError("Unexpected response", detail=str(data)[:500])
        return data
