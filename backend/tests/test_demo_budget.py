"""公开演示的真实边界：匿名隔离、原子预算、失败与重试计量。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core import llm, token_budget
from app.core.config import settings
from app.core.db import get_sessionmaker
from app.core.demo_session import COOKIE
from app.core.errors import AppError
from app.models.business import LLMUsageBudget
from app.schemas.slots import SlotExtraction


@pytest.fixture
def budget(db, monkeypatch):
    db.execute(delete(LLMUsageBudget))
    db.commit()
    monkeypatch.setattr(settings, "llm_budget_enabled", True)
    monkeypatch.setattr(settings, "llm_daily_token_limit", 500_000)
    monkeypatch.setattr(settings, "llm_daily_call_limit", 60)
    monkeypatch.setattr(settings, "llm_calls_per_minute", 60)
    monkeypatch.setattr(settings, "llm_max_concurrency", 1)
    monkeypatch.setattr(token_budget, "_now", lambda: datetime(2026, 10, 14, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")))


def rows():
    with get_sessionmaker()() as db:
        return {r.bucket: (r.tokens, r.calls) for r in db.scalars(select(LLMUsageBudget))}


def reserve():
    return token_budget.reserve("system", "user", SlotExtraction, 100)


def test_day_limit_denies_before_upstream_and_preserves_counter(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_daily_call_limit", 1)
    reserve()
    before = rows()
    with pytest.raises(AppError, match="今日") as exc:
        reserve()
    assert exc.value.code == "LLM_BUDGET_EXCEEDED"
    assert rows() == before


def test_token_reservation_blocks_concurrent_overspend(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_daily_token_limit", 1)
    with pytest.raises(AppError) as exc:
        reserve()
    assert exc.value.code == "LLM_BUDGET_EXCEEDED"
    assert rows() == {}


def test_simultaneous_call_reservations_are_atomic(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_daily_call_limit", 1)
    def attempt(_):
        try:
            reserve()
            return True
        except AppError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    assert rows()["day:2026-10-14"][1] == 1


def test_minute_limit_and_midnight_reset(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_calls_per_minute", 1)
    reserve()
    with pytest.raises(AppError) as exc:
        reserve()
    assert exc.value.code == "LLM_RATE_LIMITED"
    monkeypatch.setattr(token_budget, "_now", lambda: datetime(2026, 10, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    reserve()
    assert rows()["day:2026-10-15"][1] == 1


def test_settlement_includes_cache_and_unknown_failure_keeps_reservation(budget):
    ticket = reserve()
    before = rows()["day:2026-10-14"][0]
    token_budget.settle(ticket, SimpleNamespace(usage=None))
    assert rows()["day:2026-10-14"][0] == before
    usage = SimpleNamespace(input_tokens=20, output_tokens=30, cache_read_input_tokens=100, cache_creation_input_tokens=50)
    token_budget.settle(ticket, SimpleNamespace(usage=usage))
    assert rows()["day:2026-10-14"] == (200, 1)


def test_concurrency_slot_released_after_failure(budget):
    with pytest.raises(RuntimeError):
        with token_budget.model_slot():
            with pytest.raises(AppError) as exc:
                with token_budget.model_slot():
                    pass
            assert exc.value.code == "LLM_BUSY"
            raise RuntimeError("upstream failure")
    with token_budget.model_slot():
        pass


def test_large_prompt_never_reaches_upstream(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_input_token_limit", 10)
    with pytest.raises(AppError) as exc:
        reserve()
    assert exc.value.code == "LLM_INPUT_TOO_LARGE"
    assert rows() == {}


def test_each_format_retry_is_charged_and_output_capped(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_extract_output_limit", 120)
    responses = [None, SlotExtraction(slots={}, followups=[], notes="")]
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed_output=responses.pop(0), stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0))
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=8000)
    assert len(calls) == 2 and all(c["max_tokens"] == 120 for c in calls)
    assert rows()["day:2026-10-14"] == (240, 2)


def test_quota_failure_does_not_make_second_provider_request(budget, monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_daily_call_limit", 1)
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(parsed_output=None, stop_reason="end_turn", usage=None)
    monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    with pytest.raises(AppError) as exc:
        llm.parse_structured(system="S", user="U", output_format=SlotExtraction, max_tokens=8000)
    assert exc.value.code == "LLM_BUDGET_EXCEEDED" and len(calls) == 1


def test_public_demo_works_without_key_and_isolates_visitors(budget, client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "demo_session_secret", "test-session-secret-" * 3)
    client.cookies.clear()
    first = client.post("/api/v1/conversations")
    assert first.status_code == 201
    conv = first.json()["conv_id"]
    assert "HttpOnly" in first.headers["set-cookie"]
    assert client.get(f"/api/v1/conversations/{conv}/card").status_code == 200
    client.cookies.clear()
    assert client.get(f"/api/v1/conversations/{conv}/card").status_code == 404
    assert conv not in {c["conv_id"] for c in client.get("/api/v1/conversations").json()["items"]}


def test_tampered_session_cannot_read_another_visitors_card(budget, client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "demo_session_secret", "test-session-secret-" * 3)
    client.cookies.clear()
    conv = client.post("/api/v1/conversations").json()["conv_id"]
    cookie = client.cookies.get(COOKIE)
    client.cookies.clear()
    client.cookies.set(COOKIE, cookie.rsplit(".", 1)[0] + ".invalid")
    assert client.get(f"/api/v1/conversations/{conv}/card").status_code == 404


def test_public_demo_fails_closed_without_budget(budget, client, monkeypatch):
    monkeypatch.setattr(settings, "public_demo", True)
    monkeypatch.setattr(settings, "auth_enabled", False)
    monkeypatch.setattr(settings, "llm_budget_enabled", False)
    assert client.post("/api/v1/conversations").status_code == 503
