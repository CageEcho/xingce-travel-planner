"""模型调用前预留额度；并发事务、重试、失败调用都不能绕过预算。"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.models.business import LLMUsageBudget

_active = 0
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


@contextmanager
def model_slot():
    global _active
    if not settings.llm_budget_enabled:
        yield
        return
    with _lock:
        if _active >= settings.llm_max_concurrency:
            raise AppError("LLM_BUSY", "演示服务正在处理其他需求，请稍后再试")
        _active += 1
    try:
        yield
    finally:
        with _lock:
            _active -= 1


def output_limit(schema, requested: int) -> int:
    if not settings.llm_budget_enabled:
        return requested
    caps = {"SlotExtraction": settings.llm_extract_output_limit,
            "Guidance": settings.llm_guidance_output_limit,
            "ItineraryPlan": settings.llm_plan_output_limit}
    return min(requested, caps.get(schema.__name__, settings.llm_guidance_output_limit))


def reserve(system: str, user: str, schema, max_output: int) -> tuple[str, int] | None:
    if not settings.llm_budget_enabled:
        return None
    # UTF-8 字节量加协议余量作保守预留；不是把字符数当精确 tokenizer。
    text = system + user + json.dumps(schema.model_json_schema(), ensure_ascii=False)
    input_reserve = len(text.encode("utf-8")) + 4096
    if input_reserve > settings.llm_input_token_limit:
        raise AppError("LLM_INPUT_TOO_LARGE", "本次需求内容过长，请精简后再试")
    amount = input_reserve + max_output
    now = _now()
    daily = f"day:{now:%Y-%m-%d}"
    minute = f"minute:{now:%Y-%m-%dT%H:%M}"
    with get_sessionmaker()() as db, db.begin():
        for bucket in [daily, minute]:
            db.execute(insert(LLMUsageBudget).values(bucket=bucket, tokens=0, calls=0)
                       .on_conflict_do_nothing(index_elements=["bucket"]))
        day = db.scalar(select(LLMUsageBudget).where(LLMUsageBudget.bucket == daily).with_for_update())
        rate = db.scalar(select(LLMUsageBudget).where(LLMUsageBudget.bucket == minute).with_for_update())
        if day.calls >= settings.llm_daily_call_limit or day.tokens + amount > settings.llm_daily_token_limit:
            raise AppError("LLM_BUDGET_EXCEEDED", "今日演示 AI 额度已用完，请明天再试")
        if rate.calls >= settings.llm_calls_per_minute:
            raise AppError("LLM_RATE_LIMITED", "演示请求较频繁，请一分钟后再试")
        day.calls += 1
        day.tokens += amount
        rate.calls += 1
    return daily, amount


def settle(reservation: tuple[str, int] | None, response) -> None:
    if reservation is None:
        return
    usage = getattr(response, "usage", None)
    # 缺少账单信息或网络中断时不退还预留，以免未知消耗被漏记。
    if usage is None:
        return
    fields = ["input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"]
    actual = sum(int(getattr(usage, field, 0) or 0) for field in fields)
    if actual <= 0:
        return
    bucket, reserved = reservation
    with get_sessionmaker()() as db, db.begin():
        row = db.scalar(select(LLMUsageBudget).where(LLMUsageBudget.bucket == bucket).with_for_update())
        row.tokens += actual - reserved
