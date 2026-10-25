"""数据库引擎与 session。

DATABASE_URL 两种形式：
- postgresql+psycopg://user:pwd@host:5432/db     常规（Docker Compose 起的 PG 16）
- embedded:///<dir>                               无 Docker 时用 pgserver 内嵌 PostgreSQL 16（含 pgvector）
"""
from __future__ import annotations

import logging
import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import ROOT_DIR, settings


logging.getLogger("pgserver").setLevel(logging.WARNING)   # 内嵌 PG 的启动日志太吵


class Base(DeclarativeBase):
    pass


_embedded_server = None


def resolve_database_url(url: str | None = None) -> str:
    """把 embedded:// 形式解析成真实的 psycopg 连接串；其余原样返回。"""
    url = url or os.environ.get("DATABASE_URL") or settings.database_url
    if not url.startswith("embedded://"):
        return url
    global _embedded_server
    import pgserver  # 延迟导入：只有内嵌模式才需要

    raw = url[len("embedded://"):]
    # 云端代码目录可能只读；允许把演示数据库放到独立可写目录。
    data_dir = Path(os.environ.get("XINGCE_PGDATA") or raw.lstrip("/") or ".pgdata")
    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    if _embedded_server is None:
        _embedded_server = pgserver.get_server(str(data_dir))
    uri = _embedded_server.get_uri()  # postgresql://postgres:@/postgres?host=/tmp/...
    return uri.replace("postgresql://", "postgresql+psycopg://", 1)


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(resolve_database_url(), pool_pre_ping=True, future=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖。"""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def reset_engine(url: str | None = None) -> None:
    """测试用：切换到另一个数据库。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(resolve_database_url(url), pool_pre_ping=True, future=True)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
