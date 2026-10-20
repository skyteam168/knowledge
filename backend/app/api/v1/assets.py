from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.deps import AuthzCacheDep, DbSessionDep, ResourcesDep, SettingsDep
from app.services.knowledge.page_links import render_watermarked_page

# Authenticated by the link signature (asset, viewer, expiry): <img> tags cannot send tokens.
# ACL is re-checked on every request so revocation is not delayed until signature expiry.
router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "/pages/{asset_id}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def watermarked_page(
    asset_id: str,
    session: DbSessionDep,
    resources: ResourcesDep,
    settings: SettingsDep,
    authz_cache: AuthzCacheDep,
    u: Annotated[str, Query(max_length=64)],
    e: int,
    s: Annotated[str, Query(max_length=64)],
) -> Response:
    data = await render_watermarked_page(
        session,
        resources.storage,
        settings,
        asset_id=asset_id,
        viewer_id=u,
        expires=e,
        signature=s,
        authz_cache=authz_cache,
    )
    return Response(
        data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
        },
    )
