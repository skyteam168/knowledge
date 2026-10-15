"""Deterministic in-process model clients for tests and offline development."""

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.llm.base import ChatMessage, ChatResult, EmbeddingSpec, RerankResult

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


def mock_answer(system: str, user: str) -> str:
    """Mimics the prompts of app.services.chat: rewrite JSON, cited answers, plain replies."""
    compiled = _compiled(system, user)
    if compiled is not None:
        return compiled
    if '"sub_queries"' in system:
        found = _QUESTION.search(user)
        question = found.group(1).strip() if found else user.strip()
        intent = "chitchat" if _GREETING.match(question) else "knowledge_qa"
        return json.dumps(
            {"intent": intent, "query": question, "sub_queries": []}, ensure_ascii=False
        )
    materials = _MATERIAL.findall(user)
    if materials:
        lines = [f"- {_first_sentence(content)}。[{n}]" for n, content in materials[:2]]
        return "根据知识库资料：\n\n" + "\n".join(lines)
    return f"[mock] 这是对“{user[:50]}”的模拟回答。"


def mock_vector(text: str, dim: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        values.extend((b - 127.5) / 127.5 for b in digest)
        counter += 1
    vec = values[:dim]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class MockEmbeddingClient:
    def __init__(self, spec: EmbeddingSpec) -> None:
        self._spec = spec
        self.calls: list[list[str]] = []

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [mock_vector(t, self._spec.dim) for t in texts]


class MockRerankClient:
    def __init__(self, model: str = "mock-reranker") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int | None = None
    ) -> list[RerankResult]:
        q = set(query.lower())
        results = []
        for i, doc in enumerate(documents):
            d = set(doc.lower())
            score = len(q & d) / len(q | d) if q and d else 0.0
            results.append(RerankResult(index=i, score=round(score, 6)))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_n] if top_n is not None else results


class MockChatClient:
    def __init__(self, model: str = "mock-chat") -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return mock_answer(system, last_user)

    async def complete(self, messages: Sequence[ChatMessage], **options: Any) -> ChatResult:
        answer = self._answer(messages)
        return ChatResult(content=answer, model=self._model, finish_reason="stop")

    async def stream(self, messages: Sequence[ChatMessage], **options: Any) -> AsyncIterator[str]:
        for ch in self._answer(messages):
            yield ch
