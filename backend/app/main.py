"""FastAPI 入口：API + 最小验收界面（同源托管，避免 CORS）。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1 import router as v1_router
from app.core.db import get_sessionmaker
from app.core.demo_session import DemoSessionMiddleware
from app.core.errors import install_error_handlers
from app.services.tasks import recover_orphans

log = logging.getLogger("app.main")
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动补偿：把僵死任务标 failed，避免前端永久轮询（手册 [A]）
    try:
        with get_sessionmaker()() as db:
            recover_orphans(db, timeout_sec=0)
    except Exception:  # noqa: BLE001
        log.exception("startup recovery failed")
    yield


app = FastAPI(title="行策 · 高端旅行智能方案生成平台（M0）", version="0.1.0", lifespan=lifespan)
install_error_handlers(app)
app.include_router(v1_router)
app.add_middleware(DemoSessionMiddleware)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


# 最小验收界面：单 HTML 挂 static/，放在路由之后
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
