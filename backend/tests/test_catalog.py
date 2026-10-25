"""知识库扩充与数据治理：规模/类目/标签/来源标注验收、H12 三态、过期资料不进候选池、参考资料召回、产品推荐。"""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.schemas.common import Verdict
from app.schemas.facts import TripContext
from app.schemas.plan import Provenance, RenderedDay, RenderedItem, RenderedPlan
from app.schemas.slots import SlotSet, SlotValue
from app.services import constraints as C
from app.services.planner import trip_dates
from app.services.recommend import recommend_products
from app.services.retrieval import build_pool
from seed.generate import CATALOG_TABLES, assert_catalog

DATA = Path(__file__).resolve().parents[2] / "seed" / "data"
CHECKS = assert_catalog({n: json.loads((DATA / f"{n}.json").read_text(encoding="utf-8")) for n in CATALOG_TABLES})


@pytest.mark.parametrize("name,ok,note", CHECKS, ids=[c[0].split(" ")[0] for c in CHECKS])
def test_catalog(name, ok, note):
    assert ok, f"{name}: {note}"


def test_loaded_counts_and_tag_dict(db):
    n = {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("hotel", "supplier", "ticket", "route",
                                                                              "history_plan", "tag_dict")}
    assert n["hotel"] == 300 and n["supplier"] >= 40
    assert n["ticket"] > 0 and n["route"] > 0 and n["history_plan"] > 0
    unregistered = db.execute(text("""SELECT DISTINCT t FROM (SELECT unnest(tags) t FROM hotel
                                      UNION SELECT unnest(tags) FROM restaurant UNION SELECT unnest(tags) FROM poi) x
                                      WHERE t NOT IN (SELECT tag FROM tag_dict)""")).scalars().all()
    assert unregistered == []


def test_h12_three_states():
    assert C.h12_verified("verified", "HTL-X") is None
    pending = C.h12_verified("pending", "HTL-X", date(2026, 9, 20))
    assert pending.verdict == Verdict.UNKNOWN and not pending.blocking and "2026-09-20" in pending.verify_hint
    expired = C.h12_verified("expired", "HTL-X", date(2026, 6, 1))
    assert expired.verdict == Verdict.FAIL and expired.blocking


def _sv(value):
    return SlotValue(value=value, source="advisor_input", confidence=1)


def _pool(db, cities, tiers, interests=None, children=0, ages=None):
    slots = SlotSet(destination_cities=_sv(cities), date_start=_sv("2026-10-15"), duration_days=_sv(5),
                    adults=_sv(2), children=_sv(children), child_ages=_sv(ages or []), hotel_tier=_sv(tiers))
    ctx = TripContext.from_slots(slots)
    start, days = trip_dates(slots)
    return build_pool(db, cities, start, start + timedelta(days=days - 1), ctx, tiers, interests=interests), ctx


def test_expired_resources_never_enter_pool(db):
    pool, _ = _pool(db, ["东京", "京都"], ["luxury", "5star", "ryokan", "boutique", "4star"])
    expired = set(db.execute(text("""SELECT hotel_id FROM hotel WHERE verified_status='expired' UNION
                                     SELECT rest_id FROM restaurant WHERE verified_status='expired'""")).scalars())
    assert expired, "种子数据里应有复核过期的资源"
    assert not ({h.hotel_id for h in pool.hotels} | {r["rest_id"] for r in pool.restaurants}) & expired


def test_pool_carries_reference_routes_and_similar_cases(db):
    pool, _ = _pool(db, ["京都"], ["luxury", "5star"], interests=["寺社", "庭园"], children=1, ages=[6])
    assert pool.routes and all(r["city"] == "京都" for r in pool.routes)
    assert pool.routes[0]["theme"] in {"亲子博物馆", "寺社古迹", "庭园慢游"}
    assert 0 < len(pool.references) <= 3
    compact = pool.to_compact()
    pool_pois = {p["poi_id"] for p in compact["pois"]}
    assert all(set(r["poi_ids"]) <= pool_pois for r in compact["reference_routes"])
    assert {"plan_id", "summary", "lessons"} == set(compact["similar_cases"][0])
    assert not {r["route_id"] for r in pool.routes} & pool.ids()      # 路线不能当行程条目引用


def test_recommend_tickets_and_reservation_checklist(db):
    ghibli = db.execute(text("SELECT poi_id FROM poi WHERE name_zh LIKE '三鹰之森%'")).scalar()
    item = RenderedItem(slot="morning", type="poi", resource_id=ghibli,
                        provenance=Provenance(resource_id=ghibli, resource_type="poi"))
    plan = RenderedPlan(days=[RenderedDay(day_index=1, date="2026-10-16", weekday=5, city="东京", theme="t", items=[item])])
    ctx = TripContext(adults=2, children=1, child_ages=[6])
    recs, checks = recommend_products(db, plan, ctx, ["动漫"])
    tickets = [r for r in recs if r.kind == "ticket" and r.day_index == 1]
    assert tickets and all(r.reservation_required and r.lead_time_days == 30 for r in tickets)
    assert any("儿童" in r.name_zh for r in tickets)                  # 有儿童才推荐儿童票
    assert checks and checks[0].code == "TKT" and "30 天" in checks[0].what_to_verify
    assert any(r.kind == "route" for r in recs)


def test_compact_keeps_hotels_for_every_city(db):
    """扩库后单城酒店会占满摘要名额；多城行程里每座城市都必须有酒店候选，否则模型会编造 ID。"""
    pool, _ = _pool(db, ["东京", "箱根", "京都"], ["5star", "luxury"])
    cities = {h["city"] for h in pool.to_compact()["hotels"]}
    assert cities == {"东京", "箱根", "京都"}


def test_repair_turns_unreplaceable_meal_into_free_time():
    from app.schemas.common import Violation
    from app.schemas.plan import ItineraryPlan, PlannedDay, PlannedItem
    from app.services.planner import repair_blocking
    from app.services.retrieval import CandidatePool

    plan = ItineraryPlan(days=[PlannedDay(day_index=1, date="2026-11-11", city="箱根", theme="t", items=[
        PlannedItem(slot="dinner", type="restaurant", resource_id="RST-HKN-012")])])
    pool = CandidatePool(restaurants=[{"rest_id": "RST-HKN-012", "city": "箱根", "closed_days": [3],
                                       "dietary_support": ["halal"], "child_friendly": True, "price_band": "high"}])
    vio = Violation(code="H3", verdict=Verdict.FAIL, day_index=1, item_index=0, resource_id="RST-HKN-012",
                    message="当日休息", blocking=True)
    fixed, notes = repair_blocking(plan, [vio], pool, TripContext(adults=2, dietary=["halal"]), set())
    item = fixed.days[0].items[0]
    assert item.type == "free_time" and item.resource_id is None
    assert notes and "RST-HKN-012" in notes[0]
