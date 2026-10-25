"""veFaaS API 启动：迁移、空库种子导入，再启动单个应用进程。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "vendor"), str(ROOT / "backend"), str(ROOT)]


def initialize() -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import func, select

    from app.core.config import settings
    from app.core.db import get_sessionmaker
    from app.models import Hotel
    from seed.load import load

    if not settings.auth_enabled and not (
        settings.public_demo and settings.demo_mode and settings.llm_budget_enabled
        and len(settings.demo_session_secret) >= 32
    ):
        raise RuntimeError("公开演示必须配置模型额度限制与匿名会话签名")
    if settings.database_url.startswith("embedded://"):
        os.environ.setdefault("XINGCE_PGDATA", "/tmp/xingce-travel-planner/pgdata")

    cfg = Config(str(ROOT / "backend" / "alembic.ini"))
    command.upgrade(cfg, "head")
    with get_sessionmaker()() as db:
        empty = db.scalar(select(func.count()).select_from(Hotel)) == 0
    if empty:
        if not settings.demo_mode:
            raise RuntimeError("非演示模式不自动导入模拟资源")
        load()


if __name__ == "__main__":
    initialize()
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), workers=1)
