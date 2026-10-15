"""Mock OpenAI-compatible model server for local development.

Endpoints: /v1/models, /v1/embeddings, /v1/rerank, /v1/chat/completions (supports stream).
All outputs are deterministic fake data.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

EMBEDDING_DIM = int(os.getenv("MOCK_EMBEDDING_DIM", "1024"))
STREAM_DELAY = float(os.getenv("MOCK_STREAM_DELAY", "0.02"))
MODELS = ["mock-embedding", "mock-reranker", "mock-chat"]

app = FastAPI(title="Mock LLM Server")


def _embed(text: str) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < EMBEDDING_DIM:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend((b - 127.5) / 127.5 for b in digest)
        counter += 1
    vec = values[:EMBEDDING_DIM]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


_TERM = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]", re.IGNORECASE)


def _terms(text: str) -> set[str]:
    """Latin words plus CJK character bigrams."""
    tokens = _TERM.findall(text.lower())
    terms = {t for t in tokens if len(t) > 1}
    terms |= {a + b for a, b in zip(tokens, tokens[1:]) if len(a) == 1 and len(b) == 1}
    return terms


def _overlap_score(query: str, doc: str) -> float:
    """Share of the query's terms found in the document (0..1, like a relevance probability)."""
    q = _terms(query)
    if not q:
        return 0.0
    return round(len(q & _terms(doc)) / len(q), 6)


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]
    top_n: int | None = None
    return_documents: bool = True


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in MODELS],
    }


@app.post("/v1/embeddings")
async def embeddings(req: EmbeddingRequest) -> dict[str, Any]:
    inputs = [req.input] if isinstance(req.input, str) else req.input
    data = [
        {"object": "embedding", "index": i, "embedding": _embed(text)}
        for i, text in enumerate(inputs)
    ]
    tokens = sum(len(t) for t in inputs)
    return {
        "object": "list",
        "model": req.model,
        "data": data,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }


@app.post("/v1/rerank")
async def rerank(req: RerankRequest) -> dict[str, Any]:
    scored = [
        {"index": i, "relevance_score": _overlap_score(req.query, doc), "document": doc}
        for i, doc in enumerate(req.documents)
    ]
    scored.sort(key=lambda r: r["relevance_score"], reverse=True)
    if req.top_n is not None:
        scored = scored[: req.top_n]
    results = [
        {
            "index": r["index"],
            "relevance_score": r["relevance_score"],
            **({"document": {"text": r["document"]}} if req.return_documents else {}),
        }
        for r in scored
    ]
    return {"id": f"rerank-{uuid.uuid4().hex}", "model": req.model, "results": results}


_QUESTION = re.compile(r"<question>\n(.*?)\n</question>", re.DOTALL)
_MATERIAL = re.compile(r'<material id="(\d+)">.*?内容：\n(.*?)\n</material>', re.DOTALL)
_GREETING = re.compile(
    r"^(你好|您好|嗨|hi|hello|谢谢|感谢|早上好|晚上好|在吗)[\s!！。,，~]*$", re.IGNORECASE
)
_SENTENCE_END = re.compile(r"[。！？!?\n]")


def _first_sentence(text: str, limit: int = 120) -> str:
    lines = [ln.strip(" #|-") for ln in text.splitlines()]
    body = " ".join(ln for ln in lines if ln)
    match = _SENTENCE_END.search(body)
    sentence = body[: match.start()] if match else body
    return sentence[:limit].strip()


_NEW = re.compile(r"<new>\n(.*?)\n</new>", re.DOTALL)
_EXISTING = re.compile(r"<existing>\n(.*?)\n</existing>", re.DOTALL)
_ANSWER = re.compile(r"<answer>\n(.*?)\n</answer>", re.DOTALL)
_CITED = re.compile(r"\[\d+\]")


def _judged(user: str) -> str:
    """Mimics the evaluation judge: cited sentences = faithful, shared characters = relevant."""
    found_q = _QUESTION.search(user)
    question = found_q.group(1) if found_q else ""
    found = _ANSWER.search(user)
    answer = found.group(1) if found else ""
    sentences = [s for s in _SENTENCE_END.split(answer) if s.strip()]
    cited = [s for s in sentences if _CITED.search(s)]
    q_chars = set(question)
    has_materials = bool(_MATERIAL.search(user))
    verdict = {
        "faithfulness": round(len(cited) / len(sentences), 4) if sentences else 0.0,
        "answer_relevance": round(len(q_chars & set(answer)) / len(q_chars), 4) if q_chars else 0.0,
        "citation_accuracy": (1.0 if has_materials else 0.0) if cited else None,
        "reasons": {"faithfulness": "mock 判断"},
    }
    return json.dumps(verdict, ensure_ascii=False)


def _compiled(system: str, user: str) -> str | None:
    """Mimics the Knowledge Compiler prompts (KO draft, FAQ batch, conflict judge)."""
    if '"faithfulness"' in system:
        return _judged(user)
    if '"verdict"' in system:
        new = _NEW.search(user)
        old = _EXISTING.search(user)
        same = bool(new and old and new.group(1).strip() == old.group(1).strip())
        verdict = {"verdict": "duplicate" if same else "consistent", "reason": "mock 判断"}
        return json.dumps(verdict, ensure_ascii=False)
    materials = _MATERIAL.findall(user)
    if '"items"' in system:
        items = [
            {
                "title": _first_sentence(content, 30),
                "question": f"{_first_sentence(content, 40)}是怎样规定的？",
                "variants": [f"请问{_first_sentence(content, 40)}？"],
                "answer": f"{_first_sentence(content)}。",
                "citations": [int(n)],
            }
            for n, content in materials[:3]
            if _first_sentence(content)
        ]
        return json.dumps({"items": items}, ensure_ascii=False)
    if '"variants"' in system:
        found = _QUESTION.search(user)
        question = found.group(1).strip() if found else ""
        lines = [f"- {_first_sentence(content)}。" for _, content in materials[:3]]
        return json.dumps(
            {
                "title": question[:30],
                "question": question,
                "variants": [],
                "answer": "\n".join(lines) or "资料不足。",
                "citations": [int(n) for n, _ in materials[:3]],
            },
            ensure_ascii=False,
        )
    return None


def _answer_for(req: ChatRequest) -> str:
    """Mimics the backend prompts: query-rewrite JSON, answers citing [n], plain replies."""
    system = next((m.content for m in req.messages if m.role == "system"), "")
    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
    compiled = _compiled(system, last_user)
    if compiled is not None:
        return compiled
    if '"sub_queries"' in system:
        found = _QUESTION.search(last_user)
        question = found.group(1).strip() if found else last_user.strip()
        intent = "chitchat" if _GREETING.match(question) else "knowledge_qa"
        return json.dumps(
            {"intent": intent, "query": question, "sub_queries": []}, ensure_ascii=False
        )
    materials = _MATERIAL.findall(last_user)
    if materials:
        lines = [f"- {_first_sentence(content)}。[{n}]" for n, content in materials[:2]]
        return "根据知识库资料：\n\n" + "\n".join(lines)
    if system and "闲聊" in system:
        return "你好！我是企业知识库 AI 助手，可以帮你查询制度、流程、产品与技术资料。"
    return f"[mock] 这是对“{last_user[:50]}”的模拟回答。"


async def _stream_chat(req: ChatRequest, completion_id: str, created: int) -> AsyncIterator[str]:
    answer = _answer_for(req)
    for i, ch in enumerate(answer):
        delta: dict[str, Any] = {"content": ch}
        if i == 0:
            delta["role"] = "assistant"
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        await asyncio.sleep(STREAM_DELAY)
    final = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": req.model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(req: ChatRequest) -> dict[str, Any] | StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    if req.stream:
        return StreamingResponse(
            _stream_chat(req, completion_id, created), media_type="text/event-stream"
        )
    answer = _answer_for(req)
    prompt_tokens = sum(len(m.content) for m in req.messages)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": len(answer),
            "total_tokens": prompt_tokens + len(answer),
        },
    }
