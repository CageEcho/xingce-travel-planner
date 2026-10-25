"""M0 API Key 身份认证与角色权限。

生产模式失败关闭：AUTH_ENABLED=true 但未配置有效 API_KEYS_JSON 时，不会退回匿名身份。
API Key 只用于认证，不写入日志、错误详情或响应。
"""
from __future__ import annotations

import hmac
import json
from typing import Annotated, Callable, Literal

from fastapi import Depends, Header, Request
from pydantic import BaseModel

from app.core.config import settings
from app.core.errors import AppError

Role = Literal["sales", "advisor", "supervisor", "procurement", "admin"]
ALL_ROLES: frozenset[str] = frozenset({"sales", "advisor", "supervisor", "procurement", "admin"})
COST_ROLES: frozenset[str] = frozenset({"advisor", "supervisor", "procurement", "admin"})
WRITE_ROLES: frozenset[str] = frozenset({"sales", "advisor", "supervisor", "admin"})
PERSONAL_SCOPE_ROLES: frozenset[str] = frozenset({"sales", "advisor"})


class Principal(BaseModel):
    user_id: str
    role: Role

    @property
    def can_view_cost(self) -> bool:
        return self.role in COST_ROLES

    @property
    def owner_scope(self) -> str | None:
        """None 表示可读取全部归属；销售与普通顾问只读取本人数据。"""
        return self.user_id if self.role in PERSONAL_SCOPE_ROLES else None


def _credentials() -> dict[str, Principal]:
    try:
        raw = json.loads(settings.api_keys_json)
    except (TypeError, ValueError) as exc:
        raise AppError("AUTH_CONFIG_INVALID", "服务端鉴权配置无效") from exc
    if not isinstance(raw, dict):
        raise AppError("AUTH_CONFIG_INVALID", "服务端鉴权配置无效")
    out: dict[str, Principal] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or len(key) < 16 or not isinstance(value, dict):
            continue
        try:
            out[key] = Principal.model_validate(value)
        except ValueError:
            continue
    if not out:
        raise AppError("AUTH_CONFIG_INVALID", "鉴权已启用，但没有配置有效凭证")
    return out


def current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    if not settings.auth_enabled:
        if settings.public_demo:
            return Principal(user_id=request.state.demo_user_id, role="advisor")
        return Principal(user_id=settings.local_user_id, role=settings.local_role)
    token = x_api_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise AppError("AUTH_REQUIRED", "需要登录后访问")
    for key, principal in _credentials().items():
        if hmac.compare_digest(token, key):
            return principal
    raise AppError("AUTH_INVALID", "登录凭证无效或已失效")


def require_roles(*roles: str) -> Callable[[Principal], Principal]:
    allowed = frozenset(roles)

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in allowed:
            raise AppError("FORBIDDEN", "当前角色无权执行此操作")
        return principal

    return dependency
