"""Favorites, recently viewed, document comments and online Markdown documents."""

from typing import Any

import httpx

from tests.conftest import auth
from tests.samples import make_pdf
from tests.test_indexing import BOB, create_kb, me

ALICE, CAROL = auth("alice-token"), auth("carol-token")
DOCS = "/api/v1/documents"
KBS = "/api/v1/knowledge-bases"


async def _acl(api: httpx.AsyncClient, kb_id: str, carol: str | None) -> None:
    entries = [
        {
            "principal_type": "user",
            "principal_id": (await me(api, BOB))["id"],
            "permission": "manage",
        }
    ]
    if carol:
        entries.append({"principal_type": "user", "principal_id": carol, "permission": "read"})
    resp = await api.put(
        f"{KBS}/{kb_id}/acl", json={"visibility": "restricted", "entries": entries}, headers=BOB
    )
    assert resp.status_code == 200, resp.text


async def _kb_with_doc(
    api: httpx.AsyncClient, name: str, *, carol_reads: bool = True
) -> tuple[dict[str, Any], dict[str, Any], str]:
    carol = (await me(api, CAROL))["id"]
    kb = await create_kb(api, name)
    await _acl(api, kb["id"], carol if carol_reads else None)
    resp = await api.post(
        f"{KBS}/{kb['id']}/documents",
        files={"file": ("手册.md", f"# {name}\n\n内容".encode(), "text/markdown")},
        headers=BOB,
    )
    return kb, dict(resp.json()["document"]), carol


async def test_favorites_and_recent_follow_current_permissions(api: httpx.AsyncClient) -> None:
    kb, doc, carol = await _kb_with_doc(api, "收藏库")
    for path in (
        f"/api/v1/me/favorites/document/{doc['id']}",
        f"/api/v1/me/favorites/kb/{kb['id']}",
    ):
        assert (await api.put(path, headers=CAROL)).json() == {"favorited": True}
    assert (
        await api.put(f"/api/v1/me/favorites/document/{doc['id']}", headers=CAROL)
    ).status_code == 200
    state = await api.get(f"/api/v1/me/favorites/document/{doc['id']}", headers=CAROL)
    assert state.json() == {"favorited": True}
    items = (await api.get("/api/v1/me/favorites", headers=CAROL)).json()
    assert [(i["resource_type"], i["title"]) for i in items] == [
        ("kb", "收藏库"),
        ("document", "手册"),
    ]
    assert items[1]["link"] == f"/knowledge/{kb['id']}/documents/{doc['id']}"

    view = {"resource_type": "document", "resource_id": doc["id"]}
    assert (await api.post("/api/v1/me/recent", json=view, headers=CAROL)).status_code == 204
    assert (await api.post("/api/v1/me/recent", json=view, headers=CAROL)).status_code == 204
    recent = (await api.get("/api/v1/me/recent", headers=CAROL)).json()
    assert [r["resource_id"] for r in recent] == [doc["id"]]

    await _acl(api, kb["id"], None)
    assert (await api.get("/api/v1/me/favorites", headers=CAROL)).json() == []
    assert (await api.get("/api/v1/me/recent", headers=CAROL)).json() == []
    hidden = await api.put(f"/api/v1/me/favorites/document/{doc['id']}", headers=CAROL)
    assert hidden.status_code == 404
    await _acl(api, kb["id"], carol)
    assert len((await api.get("/api/v1/me/favorites", headers=CAROL)).json()) == 2
    await api.delete(f"/api/v1/me/favorites/kb/{kb['id']}", headers=CAROL)
    assert len((await api.get("/api/v1/me/favorites", headers=CAROL)).json()) == 1


async def _notes(
    api: httpx.AsyncClient, headers: dict[str, str], kind: str
) -> list[dict[str, Any]]:
    items = (await api.get("/api/v1/notifications", headers=headers)).json()["items"]
    return [n for n in items if n["kind"] == kind]


async def test_comments_threads_mentions_and_resolve(api: httpx.AsyncClient) -> None:
    kb, doc, carol = await _kb_with_doc(api, "评论库", carol_reads=False)
    bob = (await me(api, BOB))["id"]
    url = f"{DOCS}/{doc['id']}/comments"
    denied = await api.post(url, json={"body": "看看", "mentions": [carol]}, headers=BOB)
    assert denied.status_code == 422 and denied.json()["code"] == "MENTION_NO_ACCESS"
    await _acl(api, kb["id"], carol)

    resp = await api.post(url, json={"body": "第 3 段参数已过时", "mentions": [bob]}, headers=CAROL)
    assert resp.status_code == 201, resp.text
    top = resp.json()
    assert top["mentions"][0]["id"] == bob and top["can_resolve"] and top["document_version"] == 1
    mention = await _notes(api, BOB, "comment_mention")
    assert len(mention) == 1 and "提到了你" in mention[0]["title"]
    assert mention[0]["link"].endswith(f"tab=comments&comment={top['id']}")

    reply = await api.post(url, json={"body": "已更新", "parent_id": top["id"]}, headers=BOB)
    assert reply.status_code == 201
    assert len(await _notes(api, CAROL, "comment_new")) == 1
    nested = await api.post(url, json={"body": "x", "parent_id": reply.json()["id"]}, headers=CAROL)
    assert nested.status_code == 422

    threads = (await api.get(url, headers=CAROL)).json()
    assert len(threads) == 1 and [r["body"] for r in threads[0]["replies"]] == ["已更新"]
    assert not threads[0]["replies"][0]["can_edit"]

    edit = await api.put(f"/api/v1/comments/{top['id']}", json={"body": "改"}, headers=BOB)
    assert edit.status_code == 403
    edit = await api.put(
        f"/api/v1/comments/{top['id']}", json={"body": "第 3 段参数已更新?"}, headers=CAROL
    )
    assert edit.json()["edited"] is True
    resolved = await api.post(f"/api/v1/comments/{top['id']}/resolve", json={}, headers=BOB)
    assert resolved.json()["resolved_at"] and resolved.json()["resolved_by_name"]
    assert resolved.json()["edited"] is True

    assert (await api.delete(f"/api/v1/comments/{top['id']}", headers=BOB)).status_code == 204
    threads = (await api.get(url, headers=CAROL)).json()
    assert threads[0]["deleted"] and threads[0]["body"] == "" and threads[0]["replies"]
    other = await api.get(url, headers=auth("other-org-token"))
    assert other.status_code == 404


async def test_online_markdown_documents_save_new_versions(api: httpx.AsyncClient) -> None:
    kb, _, _ = await _kb_with_doc(api, "在线库")
    create = await api.post(
        f"{KBS}/{kb['id']}/documents/markdown",
        json={"title": "安全操作规程", "content": "# 规程\n\n戴手套", "tags": ["安全"]},
        headers=BOB,
    )
    assert create.status_code == 200, create.text
    doc = create.json()["document"]
    assert doc["filename"] == "安全操作规程.md" and doc["title"] == "安全操作规程"
    again = await api.post(
        f"{KBS}/{kb['id']}/documents/markdown",
        json={"title": "安全操作规程", "content": "别的"},
        headers=BOB,
    )
    assert again.status_code == 409

    content = (await api.get(f"{DOCS}/{doc['id']}/content", headers=BOB)).json()
    assert content["content"] == "# 规程\n\n戴手套" and content["version"] == 1
    assert (await api.get(f"{DOCS}/{doc['id']}/content", headers=CAROL)).status_code == 403

    body = {"content": "# 规程\n\n戴手套和护目镜", "base_version": 1}
    saved = await api.put(f"{DOCS}/{doc['id']}/content", json=body, headers=BOB)
    assert saved.status_code == 200, saved.text
    assert saved.json()["new_version"] and saved.json()["document"]["version"] == 2
    stale = await api.put(f"{DOCS}/{doc['id']}/content", json=body, headers=BOB)
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"

    pdf = await api.post(
        f"{KBS}/{kb['id']}/documents",
        files={"file": ("图.pdf", make_pdf(), "application/pdf")},
        headers=BOB,
    )
    not_text = await api.get(f"{DOCS}/{pdf.json()['document']['id']}/content", headers=BOB)
    assert not_text.status_code == 422 and not_text.json()["code"] == "NOT_EDITABLE"
