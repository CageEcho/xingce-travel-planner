"""统一错误结构 {"error": {"code", "message"}}（手册 [A]）。不返回堆栈。"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("app.errors")

# 错误码表（集中定义）
ERROR_STATUS: dict[str, int] = {
    "AUTH_REQUIRED": 401,
    "AUTH_INVALID": 401,
    "FORBIDDEN": 403,
    "AUTH_CONFIG_INVALID": 503,
    "CONV_NOT_FOUND": 404,
    "CARD_NOT_FOUND": 404,
    "PLAN_NOT_FOUND": 404,
    "VERSION_NOT_FOUND": 404,
    "SLOT_UNKNOWN": 400,
    "VALUE_INVALID": 400,
    "PARAM_INVALID": 400,
    "COMPLETENESS_TOO_LOW": 409,   # 人工节点①前置：完整度不足不得确认
    "CARD_NOT_READY": 409,         # 必问项未确认或存在冲突
    "CARD_NOT_CONFIRMED": 409,     # 人工节点①：未确认不得生成（G4）
    "CANDIDATES_TOO_FEW": 409,     # 硬过滤后候选不足，先返回放宽建议
    "LLM_FAILED": 502,
    "LLM_INVALID_OUTPUT": 502,
    "LLM_BUDGET_EXCEEDED": 429,
    "LLM_RATE_LIMITED": 429,
    "LLM_BUSY": 429,
    "LLM_INPUT_TOO_LARGE": 400,
    "ORPHANED": 500,
    "INTERNAL": 500,
}


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = ERROR_STATUS.get(code, 500)

    def body(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.details:
            err["details"] = self.details
        return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        msgs = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', []))}: {e.get('msg')}" for e in exc.errors()
        )
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "PARAM_INVALID", "message": msgs or "请求参数不合法"}},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # 记日志，但绝不把堆栈返回给调用方
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL", "message": "服务内部错误，请稍后重试"}},
        )
