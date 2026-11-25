"""Thin sync client for /open/actions* and ontology object reads."""

from __future__ import annotations

from typing import Any

import httpx


class OntologyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base,
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OntologyClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_actions(self) -> dict[str, Any]:
        r = self._client.get("/open/actions")
        r.raise_for_status()
        return r.json()

    def approve_action(
        self,
        action_type: str,
        input: dict[str, Any],
        *,
        acknowledge_risk: bool = True,
    ) -> dict[str, Any]:
        r = self._client.post(
            "/open/actions/approve",
            json={
                "action_type": action_type,
                "input": input,
                "acknowledge_risk": acknowledge_risk,
            },
        )
        r.raise_for_status()
        return r.json()

    def invoke_action(
        self,
        action_type: str,
        input: dict[str, Any],
        *,
        idempotency_key: str,
        approval_id: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "action_type": action_type,
            "input": input,
            "idempotency_key": idempotency_key,
            "dry_run": dry_run,
        }
        if approval_id:
            body["approval_id"] = approval_id
        r = self._client.post("/open/actions/invoke", json=body)
        r.raise_for_status()
        return r.json()

    def get_object(self, object_type: str, **kwargs: Any) -> dict[str, Any]:
        r = self._client.post(
            "/open/objects/get",
            json={"object_type": object_type, **kwargs},
        )
        r.raise_for_status()
        return r.json()
