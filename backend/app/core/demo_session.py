"""公开演示用匿名签名 Cookie，不共享访客的需求与会话。"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings

COOKIE = "xingce_demo_session"


def _sign(identifier: str) -> str:
    return hmac.new(settings.demo_session_secret.encode(), identifier.encode(), hashlib.sha256).hexdigest()


def session_identity(cookie: str | None) -> tuple[str, str]:
    if cookie:
        identifier, _, signature = cookie.partition(".")
        if len(identifier) == 32 and all(c in "0123456789abcdef" for c in identifier):
            if hmac.compare_digest(signature, _sign(identifier)):
                return "demo-" + identifier, cookie
    identifier = secrets.token_hex(16)
    return "demo-" + identifier, identifier + "." + _sign(identifier)


class DemoSessionMiddleware:
    """直接添加响应头，保留原始 ASGI 请求体及响应，不引入流式代理。"""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or not settings.public_demo or settings.auth_enabled
                or not scope["path"].startswith("/api/")):
            return await self.app(scope, receive, send)
        if not settings.demo_mode or not settings.llm_budget_enabled or len(settings.demo_session_secret) < 32:
            response = JSONResponse(status_code=503, content={
                "error": {"code": "AUTH_CONFIG_INVALID", "message": "演示环境配置未完成"}})
            return await response(scope, receive, send)
        request = Request(scope)
        identity, cookie = session_identity(request.cookies.get(COOKIE))
        scope.setdefault("state", {})["demo_user_id"] = identity
        extra = [(b"cache-control", b"no-store")]
        if request.cookies.get(COOKIE) != cookie:
            response = Response()
            response.set_cookie(COOKIE, cookie, httponly=True, samesite="lax", max_age=86400,
                                secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
            extra.extend((k, v) for k, v in response.raw_headers if k == b"set-cookie")

        async def send_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        return await self.app(scope, receive, send_headers)
