"""OIDC bridge endpoints for Keycloak (generic OIDC IdP) -> WeCom / DingTalk login."""

import base64
import binascii
import html
from typing import Annotated
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.api.deps import DbSessionDep, ResourcesDep, SettingsDep
from app.core.exceptions import AppError
from app.services.oidc_bridge.service import OAuthError, OidcBridgeService

router = APIRouter(prefix="/oidc/{provider}", tags=["oidc-bridge"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def get_bridge(
    session: DbSessionDep, settings: SettingsDep, resources: ResourcesDep
) -> OidcBridgeService:
    return OidcBridgeService(session, settings, resources.cache)


BridgeDep = Annotated[OidcBridgeService, Depends(get_bridge)]


def _cookie_name(provider: str) -> str:
    return f"ekb_oidc_{provider}"


def _error_page(bridge: OidcBridgeService, exc: AppError) -> HTMLResponse:
    # idp=none: back to the normal login page instead of auto-redirecting to scan login again.
    home = html.escape(f"{bridge.settings.public_base_url.rstrip('/')}/?idp=none")
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录失败</title>
<style>
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f5f7fa;margin:0}}
.box{{max-width:420px;margin:15vh auto;background:#fff;border-radius:8px;padding:32px;
box-shadow:0 2px 12px rgba(0,0,0,.08);text-align:center}}
h1{{font-size:20px;margin:0 0 16px}}p{{color:#606266;line-height:1.7}}
a{{display:inline-block;margin-top:16px;padding:8px 24px;background:#409eff;color:#fff;
border-radius:4px;text-decoration:none}}small{{color:#c0c4cc}}
</style></head>
<body><div class="box"><h1>登录失败</h1><p>{html.escape(exc.message)}</p>
<a href="{home}">返回登录</a><p><small>{html.escape(exc.code)}</small></p></div></body></html>"""
    return HTMLResponse(body, status_code=exc.status_code, headers=NO_STORE)


def _oauth_error(exc: OAuthError) -> JSONResponse:
    headers = dict(NO_STORE)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = f'Bearer error="{exc.error}"'
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status_code,
        headers=headers,
    )


@router.get("/.well-known/openid-configuration", include_in_schema=False)
async def discovery(provider: str, bridge: BridgeDep) -> Response:
    try:
        return JSONResponse(bridge.discovery(provider))
    except AppError as exc:
        return JSONResponse({"error": exc.code, "error_description": exc.message}, 404)


@router.get("/jwks", include_in_schema=False)
async def jwks(provider: str, bridge: BridgeDep) -> JSONResponse:
    return JSONResponse(await bridge.jwks())


@router.get("/authorize", include_in_schema=False)
async def authorize(
    provider: str,
    request: Request,
    bridge: BridgeDep,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    response_type: str | None = None,
    state: str | None = None,
    nonce: str | None = None,
    source: str | None = None,
) -> Response:
    try:
        result = await bridge.authorize(
            provider,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            state=state,
            nonce=nonce,
            source_id=source,
            user_agent=request.headers.get("user-agent", ""),
        )
    except AppError as exc:
        return _error_page(bridge, exc)
    response = RedirectResponse(result.redirect_url, status_code=302, headers=NO_STORE)
    # Binds the upstream callback to the browser that started the login.
    response.set_cookie(
        _cookie_name(provider),
        result.state_key,
        max_age=bridge.settings.oidc_bridge_state_ttl_seconds,
        path=f"/oidc/{provider}",
        httponly=True,
        secure=bridge.settings.public_base_url.startswith("https://"),
        samesite="lax",
    )
    return response


@router.get("/callback", include_in_schema=False)
async def callback(provider: str, request: Request, bridge: BridgeDep) -> Response:
    try:
        target = await bridge.callback(
            provider,
            dict(request.query_params),
            request.cookies.get(_cookie_name(provider)),
        )
    except AppError as exc:
        response: Response = _error_page(bridge, exc)
    else:
        response = RedirectResponse(target, status_code=302, headers=NO_STORE)
    response.delete_cookie(_cookie_name(provider), path=f"/oidc/{provider}")
    return response


def _basic_auth(header: str | None) -> tuple[str | None, str | None]:
    if not header or not header.lower().startswith("basic "):
        return None, None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None, None
    client_id, _, secret = decoded.partition(":")
    return unquote(client_id), unquote(secret)


@router.post("/token", include_in_schema=False)
async def token(
    provider: str,
    bridge: BridgeDep,
    grant_type: Annotated[str | None, Form()] = None,
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    basic_id, basic_secret = _basic_auth(authorization)
    try:
        result = await bridge.token(
            provider,
            grant_type=grant_type,
            code=code,
            redirect_uri=redirect_uri,
            client_id=basic_id or client_id,
            client_secret=basic_secret or client_secret,
        )
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(result, headers=NO_STORE)


@router.api_route("/userinfo", methods=["GET", "POST"], include_in_schema=False)
async def userinfo(
    provider: str,
    bridge: BridgeDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    token_value = None
    if authorization and authorization.lower().startswith("bearer "):
        token_value = authorization[7:].strip()
    try:
        return JSONResponse(await bridge.userinfo(provider, token_value), headers=NO_STORE)
    except OAuthError as exc:
        return _oauth_error(exc)
