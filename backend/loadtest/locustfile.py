"""Load test of the question-answering API (SSE) and search.

    uv run --group loadtest locust -f loadtest/locustfile.py --host http://127.0.0.1:8000

Environment:
    EKB_TOKEN_URL     Keycloak token endpoint
                      (default http://127.0.0.1:8080/realms/ekb/protocol/openid-connect/token)
    EKB_CLIENT_ID     public client with direct access grants (default ekb-frontend)
    EKB_USERS         comma separated user:password pairs; virtual users are spread over them
    EKB_TOKEN         a fixed bearer token instead of the password grant
    EKB_KB_IDS        comma separated knowledge base scope of the conversations (default: all)
    EKB_QUESTIONS     file with one question per line (default: built-in list)
    EKB_NEW_CONVERSATION_EVERY  start a new conversation after this many questions (default 5)

Besides the regular HTTP rows, three custom rows are reported for every answer:
    SSE  chat: first token   time from sending the question to the first `token` event
    SSE  chat: complete      time until the `done` event
    SSE  chat: <grounding>   one row per answer type (counts only; e.g. no_evidence = refusals)
"""

from __future__ import annotations

import itertools
import json
import os
import random
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import requests
from locust import HttpUser, between, events, task
from locust.env import Environment

API = "/api/v1"
TOKEN_URL = os.getenv(
    "EKB_TOKEN_URL", "http://127.0.0.1:8080/realms/ekb/protocol/openid-connect/token"
)
CLIENT_ID = os.getenv("EKB_CLIENT_ID", "ekb-frontend")
FIXED_TOKEN = os.getenv("EKB_TOKEN")
USERS = [
    tuple(pair.split(":", 1))
    for pair in os.getenv("EKB_USERS", "alice:password,bob:password,carol:password").split(",")
    if ":" in pair
]
KB_IDS = [k for k in os.getenv("EKB_KB_IDS", "").split(",") if k]
NEW_CONVERSATION_EVERY = int(os.getenv("EKB_NEW_CONVERSATION_EVERY", "5"))

DEFAULT_QUESTIONS = [
    "差旅住宿费的报销标准是多少？",
    "出差结束后多久内需要提交报销申请？",
    "新员工入职需要提交哪些材料？",
    "员工请假需要提前多久申请？",
    "设备保养的考核标准有哪些？",
    "物料库存盘点的流程是什么？",
    "飞织鞋面的纱线张力应控制在什么范围？",
    "年假天数如何计算？",
    "加班费怎么计算？",
    "公司的考勤制度是怎样规定的？",
    "采购申请需要哪些审批？",
    "入库检验的抽检比例是多少？",
]
SEARCH_QUERIES = ["报销", "请假 流程", "设备 保养", "库存", "入职 材料", "考勤", "张力", "差旅"]


def _questions() -> list[str]:
    path = os.getenv("EKB_QUESTIONS")
    if not path:
        return DEFAULT_QUESTIONS
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()] or DEFAULT_QUESTIONS


QUESTIONS = _questions()


class TokenCache:
    """One access token per account shared by all virtual users, refreshed before expiry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, tuple[str, float]] = {}

    def get(self, username: str, password: str, force: bool = False) -> str:
        if FIXED_TOKEN:
            return FIXED_TOKEN
        with self._lock:
            cached = self._tokens.get(username)
            if cached and not force and cached[1] > time.time() + 30:
                return cached[0]
            r = requests.post(
                TOKEN_URL,
                data={
                    "grant_type": "password",
                    "client_id": CLIENT_ID,
                    "username": username,
                    "password": password,
                },
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            self._tokens[username] = (body["access_token"], time.time() + body["expires_in"])
            return str(body["access_token"])


tokens = TokenCache()
accounts = itertools.cycle(USERS)
accounts_lock = threading.Lock()


def _sse(lines: Iterator[bytes]) -> Iterator[tuple[str, dict[str, Any]]]:
    event, data = "message", ""
    for raw in lines:
        line = raw.decode("utf-8")
        if not line:
            if data:
                yield event, json.loads(data)
            event, data = "message", ""
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data += line[5:].strip()


class KnowledgeUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        with accounts_lock:
            self.username, self.password = next(accounts)
        self.conversation_id: str | None = None
        self.asked = 0

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens.get(self.username, self.password)}"}

    def _fire(self, name: str, started: float, exc: Exception | None = None) -> None:
        self.environment.events.request.fire(
            request_type="SSE",
            name=name,
            response_time=(time.perf_counter() - started) * 1000,
            response_length=0,
            exception=exc,
            context={},
        )

    def _conversation(self) -> str | None:
        if self.conversation_id and self.asked < NEW_CONVERSATION_EVERY:
            return self.conversation_id
        r = self.client.post(
            f"{API}/chat/conversations",
            json={"title": "locust", "kb_ids": KB_IDS},
            headers=self.headers,
            name="POST /chat/conversations",
        )
        if r.status_code != 201:
            return None
        self.conversation_id, self.asked = r.json()["id"], 0
        return self.conversation_id

    @task(5)
    def ask(self) -> None:
        conversation_id = self._conversation()
        if conversation_id is None:
            return
        self.asked += 1
        started = time.perf_counter()
        first_token = False
        with self.client.post(
            f"{API}/chat/conversations/{conversation_id}/messages",
            json={"content": random.choice(QUESTIONS)},
            headers={**self.headers, "Accept": "text/event-stream"},
            name="POST /chat/conversations/{id}/messages",
            stream=True,
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code}: {r.text[:200]}")
                return
            r.success()
            try:
                for event, data in _sse(r.iter_lines()):
                    if event == "token" and not first_token:
                        first_token = True
                        self._fire("chat: first token", started)
                    elif event == "done":
                        self._fire("chat: complete", started)
                        self._fire(f"chat: {data.get('grounding', 'unknown')}", started)
                        return
                    elif event == "error":
                        raise RuntimeError(data.get("message") or data.get("code") or "error")
                raise RuntimeError("stream ended without a done event")
            except Exception as exc:
                self._fire("chat: complete", started, exc)

    @task(3)
    def search(self) -> None:
        self.client.get(
            f"{API}/search",
            params={"q": random.choice(SEARCH_QUERIES), "top_k": 10},
            headers=self.headers,
            name="GET /search",
        )

    @task(1)
    def conversations(self) -> None:
        self.client.get(
            f"{API}/chat/conversations",
            params={"page": 1, "size": 20},
            headers=self.headers,
            name="GET /chat/conversations",
        )


@events.test_start.add_listener
def _warm_tokens(environment: Environment, **_: Any) -> None:
    for username, password in USERS:
        tokens.get(username, password)
