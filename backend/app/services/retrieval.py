"""硬过滤检索（M0：纯 SQL，PRD-v2 决策 D5）。过滤掉的资源绝不进入候选池。

顺序按选择性从高到低：city → 日期可售（H8） → 档次 → 容量（H1） → 价带。
空值不视为通过：min_child_age IS NULL 的房型放行但标记 child_age_unknown，由约束层判 UNKNOWN。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.schemas.facts import rooms_needed
from app.schemas.search import HotelCandidate, HotelQuery, RelaxationHint, SearchResult

WEEKDAY_ZH = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

TIER_ORDER = ["4star", "boutique", "5star", "ryokan", "luxury"]

HOTEL_SQL = """
SELECT h.hotel_id, h.name_zh, h.name_local, h.city, h.district, h.tier, h.tags, h.lat, h.lng,
       h.updated_at AS hotel_updated_at, h.verified_status,
       r.room_id, r.name_zh AS room_name, r.max_occupancy, r.max_adults, r.max_children, r.min_child_age, r.extra_bed,
       rp.rate_id, rp.net_price, rp.season_uplift, rp.confidence, rp.updated_at AS rate_updated_at,
       (r.min_child_age IS NULL) AS child_age_unknown
FROM hotel h
JOIN room_type r  ON r.hotel_id = h.hotel_id
JOIN rate_plan rp ON rp.resource_type = 'room' AND rp.resource_id = r.room_id
WHERE h.status = 'active'
  AND h.verified_status <> 'expired'          -- 数据治理：复核过期的资料不进候选池
  AND h.city = :city
  AND h.tier = ANY(:tiers)
  -- H8 可售期（覆盖全部住宿夜）
  AND rp.valid_from <= :checkin AND rp.valid_to >= :last_night
  AND NOT (COALESCE(rp.blackout_dates, '{}') && CAST(:stay_dates AS date[]))
  -- H1 容量
  AND r.max_occupancy * :rooms >= :pax_total
  AND r.max_children * :rooms >= :children
  -- H1 儿童年龄：已记录的必须满足；未记录的放行但标记
  AND (:children = 0 OR r.min_child_age IS NULL OR r.min_child_age <= :min_child_age)
  -- 价带
  AND (CAST(:max_price AS numeric) IS NULL OR rp.net_price <= CAST(:max_price AS numeric))
  -- 标签（require_tags 为空时不过滤）
  AND (CAST(:tag_count AS int) = 0 OR h.tags @> CAST(:require_tags AS text[]))
ORDER BY rp.net_price
"""

COUNT_SQL = "SELECT count(DISTINCT h.hotel_id) FROM (" + HOTEL_SQL.replace("ORDER BY rp.net_price", "") + ") h"


def _params(q: HotelQuery, rooms: int) -> dict[str, Any]:
    nights = (q.checkout - q.checkin).days
    stay_dates = [q.checkin + timedelta(days=i) for i in range(nights)]
    return {
        "city": q.city, "tiers": list(q.tiers), "checkin": q.checkin, "last_night": q.checkout - timedelta(days=1),
        "stay_dates": stay_dates, "pax_total": q.adults + q.children, "children": q.children, "rooms": rooms,
        "min_child_age": min(q.child_ages) if q.child_ages else 0,
        "max_price": q.max_price_per_night, "tag_count": len(q.require_tags), "require_tags": list(q.require_tags),
    }


def _score(c: HotelCandidate, q: HotelQuery, now: datetime) -> float:
    tag_ratio = (sum(1 for t in q.require_tags if t in c.tags) / len(q.require_tags)) if q.require_tags else 1.0
    if q.max_price_per_night:
        price_fit = max(0.0, 1.0 - abs(float(c.net_price) / float(q.max_price_per_night) - 0.8))
    else:
        price_fit = 0.5
    upd = datetime.fromisoformat(c.rate_updated_at)
    age = (now - upd).days
    freshness = max(0.0, 1.0 - age / 365)
    penalty = 0.15 if c.confidence != "contracted" else 0.0
    return round(settings.w_tag_match * tag_ratio + settings.w_price_fit * price_fit
                 + settings.w_freshness * freshness - penalty, 4)


def search_hotels(db: Session, q: HotelQuery) -> SearchResult:
    rooms = rooms_needed(q.adults, q.children)
    params = _params(q, rooms)
    rows = db.execute(text(HOTEL_SQL), params).mappings().all()
    now = datetime.now(timezone.utc)
    cands: list[HotelCandidate] = []
    for r in rows:
        c = HotelCandidate(
            hotel_id=r["hotel_id"], room_id=r["room_id"], rate_id=r["rate_id"], name_zh=r["name_zh"],
            name_local=r["name_local"], city=r["city"], district=r["district"], tier=r["tier"], tags=list(r["tags"] or []),
            lat=r["lat"], lng=r["lng"], room_name=r["room_name"], max_occupancy=r["max_occupancy"],
            max_adults=r["max_adults"], max_children=r["max_children"], min_child_age=r["min_child_age"],
            child_age_unknown=bool(r["child_age_unknown"]), extra_bed=r["extra_bed"], net_price=Decimal(r["net_price"]),
            season_uplift=Decimal(r["season_uplift"]), confidence=r["confidence"],
            rate_updated_at=r["rate_updated_at"].isoformat(), hotel_updated_at=r["hotel_updated_at"].isoformat(),
            verified_status=r["verified_status"])
        c.score = _score(c, q, now)
        cands.append(c)
    cands.sort(key=lambda c: (-c.score, c.net_price))
    funnel = _funnel(db, q, rooms)
    hints = relaxation_hints(db, q, rooms) if not cands else []
    return SearchResult(candidates=cands, relaxation_hints=hints, total_before_filter=funnel.get("city_active"),
                        funnel=funnel)


def _funnel(db: Session, q: HotelQuery, rooms: int) -> dict[str, int]:
    """检索漏斗（供 trace / 界面「检索过程」页展示）。"""
    p = _params(q, rooms)
    steps = {
        "city_active": "SELECT count(*) FROM hotel h WHERE h.status='active' AND h.city=:city",
        "tier": "SELECT count(*) FROM hotel h WHERE h.status='active' AND h.city=:city AND h.tier = ANY(:tiers)",
        "availability_h8": """SELECT count(DISTINCT h.hotel_id) FROM hotel h JOIN room_type r ON r.hotel_id=h.hotel_id
            JOIN rate_plan rp ON rp.resource_type='room' AND rp.resource_id=r.room_id
            WHERE h.status='active' AND h.city=:city AND h.tier = ANY(:tiers)
            AND rp.valid_from <= :checkin AND rp.valid_to >= :last_night
            AND NOT (COALESCE(rp.blackout_dates,'{}') && CAST(:stay_dates AS date[]))""",
        "capacity_h1": COUNT_SQL,
    }
    out: dict[str, int] = {}
    for k, sql in steps.items():
        out[k] = int(db.execute(text(sql), p).scalar() or 0)
    return out


def relaxation_hints(db: Session, q: HotelQuery, rooms: int) -> list[RelaxationHint]:
    """候选为空时，依次去掉一个非硬性条件重跑 count，取收益最大的 2–3 条。绝不返回空列表。"""
    hints: list[RelaxationHint] = []
    trials: list[tuple[str, str, dict]] = []
    # 放宽档次
    all_tiers = TIER_ORDER
    if set(q.tiers) != set(all_tiers):
        lower = [t for t in all_tiers if t not in q.tiers]
        for t in lower:
            trials.append(("tiers", f"放宽到{TIER_ZH[t]}档", {"tiers": list(q.tiers) + [t]}))
    if q.max_price_per_night is not None:
        for mult, label in ((Decimal("1.3"), "+30%"), (Decimal("1.6"), "+60%")):
            trials.append(("max_price_per_night", f"预算上限放宽 {label}", {"max_price_per_night": q.max_price_per_night * mult}))
        trials.append(("max_price_per_night", "取消价格上限", {"max_price_per_night": None}))
    if q.require_tags:
        trials.append(("require_tags", "取消标签要求", {"require_tags": []}))
    # 组合放宽：单项放宽都无解时，档次 + 价格一起放
    if set(q.tiers) != set(all_tiers) and q.max_price_per_night is not None:
        trials.append(("tiers+max_price_per_night", "放宽到全部档次并取消价格上限", {"tiers": list(all_tiers), "max_price_per_night": None}))
    if set(q.tiers) != set(all_tiers):
        trials.append(("tiers", "放宽到全部档次", {"tiers": list(all_tiers)}))
        if q.max_price_per_night is not None:
            for t in [t for t in all_tiers if t not in q.tiers]:
                trials.append(("tiers+max_price_per_night", f"放宽到{TIER_ZH[t]}档并取消价格上限",
                               {"tiers": list(q.tiers) + [t], "max_price_per_night": None}))
    # 日期整体前后移一周
    for delta, label in ((7, "行程后移一周"), (-7, "行程前移一周")):
        trials.append(("dates", label, {"checkin": q.checkin + timedelta(days=delta), "checkout": q.checkout + timedelta(days=delta)}))
    for fld, label, patch in trials:
        q2 = q.model_copy(update=patch)
        n = int(db.execute(text(COUNT_SQL), _params(q2, rooms)).scalar() or 0)
        if n > 0:
            hints.append(RelaxationHint(field=fld, suggestion=f"{label}可得 {n} 家酒店", would_yield=n))
    hints.sort(key=lambda h: -h.would_yield)
    if not hints:
        hints.append(RelaxationHint(field="destination_cities", suggestion="该城市在此条件下无可售酒店，建议更换城市或日期",
                                    would_yield=0))
    return hints[:3]


TIER_ZH = {"4star": "四星", "5star": "五星", "luxury": "奢华", "ryokan": "高端旅馆", "boutique": "精品"}


# ───────────────────────── 候选池（进 prompt 的摘要，不含价格与描述文本） ─────────────────────────
@dataclass
class CandidatePool:
    hotels: list[HotelCandidate] = field(default_factory=list)
    restaurants: list[dict] = field(default_factory=list)
    pois: list[dict] = field(default_factory=list)
    vehicles: list[dict] = field(default_factory=list)
    funnels: dict[str, dict] = field(default_factory=dict)
    hotel_hints: dict[str, list[RelaxationHint]] = field(default_factory=dict)
    routes: list[dict] = field(default_factory=list)        # 参考路线（不进 ids()：不能直接作为行程条目）
    references: list[dict] = field(default_factory=list)    # 相似历史方案（脱敏）

    def ids(self) -> set[str]:
        s = {h.hotel_id for h in self.hotels} | {h.room_id for h in self.hotels}
        s |= {r["rest_id"] for r in self.restaurants} | {p["poi_id"] for p in self.pois} | {v["vehicle_id"] for v in self.vehicles}
        return s

    def room_ids_of(self, hotel_id: str) -> set[str]:
        return {h.room_id for h in self.hotels if h.hotel_id == hotel_id}

    def to_compact(self, per_type_limit: int = 12) -> dict:
        """摘要化：只输出 resource_id + 关键结构化字段。不含价格、描述、advisor_notes。"""
        seen: set[str] = set()
        hotels = []
        per_city: dict[str, int] = {}
        for h in self.hotels:
            if h.hotel_id in seen:
                # 同酒店多个房型：追加房型
                for x in hotels:
                    if x["hotel_id"] == h.hotel_id and len(x["rooms"]) < 4:
                        x["rooms"].append({"room_id": h.room_id, "max_occupancy": h.max_occupancy,
                                           "min_child_age": h.min_child_age})
                continue
            if per_city.get(h.city, 0) >= per_type_limit:
                continue                      # 按城市限额：多城行程里每座城市都要有酒店候选
            per_city[h.city] = per_city.get(h.city, 0) + 1
            seen.add(h.hotel_id)
            hotels.append({"hotel_id": h.hotel_id, "city": h.city, "district": h.district, "tier": h.tier,
                           "tags": h.tags[:6], "lat": h.lat, "lng": h.lng,
                           "rooms": [{"room_id": h.room_id, "max_occupancy": h.max_occupancy, "min_child_age": h.min_child_age}]})

        def by_city(rows: list[dict], key: str, fields: list[str]) -> list[dict]:
            out: list[dict] = []
            count: dict[str, int] = {}
            for r in rows:
                c = r["city"]
                if count.get(c, 0) >= per_type_limit:
                    continue
                count[c] = count.get(c, 0) + 1
                item = {k: r[k] for k in [key, *fields] if k in r}
                if "closed_days" in item:
                    # 给模型看的中文标注：closed_days=[1] → "周一休"；null → "休息日未记录"
                    cd = item["closed_days"]
                    item["closed_zh"] = "休息日未记录" if cd is None else ("无休" if not cd else "、".join(WEEKDAY_ZH[d] for d in cd) + "休")
                out.append(item)
            return out

        pois = by_city(self.pois, "poi_id",
                       ["city", "district", "category", "closed_days", "duration_min", "intensity", "accessible", "tags", "lat", "lng"])
        return {
            "hotels": hotels,
            "restaurants": by_city(self.restaurants, "rest_id",
                                   ["city", "district", "cuisine", "price_band", "closed_days", "dietary_support", "child_friendly", "lat", "lng"]),
            "pois": pois,
            "vehicles": [{k: v[k] for k in ("vehicle_id", "city", "seats", "luggage_28")} for v in self.vehicles],
            "reference_routes": self._compact_routes({p["poi_id"] for p in pois}),
            "similar_cases": [{k: c[k] for k in ("plan_id", "summary", "lessons")} for c in self.references],
            "note": "closed_days: 0=周日..6=周六（closed_zh 是中文标注）；null 表示未记录（不等于全年无休）。安排前对照 skeleton 里每天的 weekday_zh。"
                    "reference_routes / similar_cases 只是参考：可以借鉴路线里景点的顺序，但条目必须引用 pois 里出现的 poi_id。",
        }

    def _compact_routes(self, visible_pois: set[str]) -> list[dict]:
        """路线只保留模型在本次 prompt 里看得到的景点，避免引导它引用摘要外的 ID。"""
        out = []
        for r in self.routes:
            pois = [p for p in r["poi_ids"] if p in visible_pois]
            if len(pois) >= 2:
                out.append({"route_id": r["route_id"], "city": r["city"], "theme": r["theme"],
                            "duration_type": r["duration_type"], "poi_ids": pois})
        return out


def search_restaurants(db: Session, city: str, restrictions: list[str], children: int) -> list[dict]:
    """硬过滤：city/active；有饮食限制时，明确不支持的排除，未记录（空）的保留（约束层判 UNKNOWN）。"""
    sql = """SELECT rest_id, name_zh, name_local, city, district, cuisine, price_band, closed_days, open_from, open_to,
                    dietary_support, child_friendly, lat, lng, tags, updated_at, verified_status
             FROM restaurant WHERE status='active' AND verified_status <> 'expired' AND city=:city
               AND (CAST(:need_count AS int) = 0 OR cardinality(dietary_support) = 0 OR dietary_support @> CAST(:need AS text[]))
             ORDER BY CASE price_band WHEN 'luxury' THEN 0 WHEN 'high' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, rest_id"""
    rows = db.execute(text(sql), {"city": city, "need_count": len(restrictions), "need": restrictions}).mappings().all()
    return [_row(r) for r in rows]


def search_pois(db: Session, city: str, accessible_required: bool, children: int) -> list[dict]:
    """硬过滤：city/active；需要无障碍时排除 accessible=false（NULL 保留，判 UNKNOWN）。"""
    sql = """SELECT poi_id, name_zh, name_local, city, district, category, closed_days, open_from, open_to, duration_min,
                    intensity, accessible, tags, lat, lng, updated_at, verified_status
             FROM poi WHERE status='active' AND verified_status <> 'expired' AND city=:city
               AND (NOT CAST(:acc AS boolean) OR accessible IS DISTINCT FROM false)
               AND (CAST(:children AS int) = 0 OR intensity <> 'hard')
             ORDER BY category, poi_id"""
    rows = db.execute(text(sql), {"city": city, "acc": accessible_required, "children": children}).mappings().all()
    return [_row(r) for r in rows]


def search_vehicles(db: Session, city: str, pax: int, luggage_est: int) -> list[dict]:
    """硬过滤：座位必须够；行李已记录的必须够，未记录的保留（判 UNKNOWN）。"""
    sql = """SELECT vehicle_id, name_zh, city, seats, luggage_28, service_hours, updated_at, verified_status
             FROM vehicle WHERE status='active' AND verified_status <> 'expired' AND city=:city AND seats >= :pax
               AND (luggage_28 IS NULL OR luggage_28 >= :lug)
             ORDER BY seats, vehicle_id"""
    rows = db.execute(text(sql), {"city": city, "pax": pax, "lug": luggage_est}).mappings().all()
    return [_row(r) for r in rows]


def _row(r) -> dict:
    d = dict(r)
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, Decimal):
            d[k] = float(v)
    return d


# 客户兴趣（自由文本）→ 路线主题
INTEREST_THEMES = {
    "亲子": "亲子博物馆", "儿童": "亲子博物馆", "动物": "亲子博物馆", "火车": "亲子博物馆", "动漫": "亲子博物馆",
    "艺术": "艺术漫游", "美术": "艺术漫游", "博物馆": "艺术漫游", "寺": "寺社古迹", "神社": "寺社古迹", "历史": "寺社古迹",
    "文化": "寺社古迹", "庭园": "庭园慢游", "园林": "庭园慢游", "安静": "庭园慢游", "夜景": "夜景夜游", "摄影": "夜景夜游",
    "美食": "在地美食与市井", "购物": "在地美食与市井", "温泉": "自然与湖景", "自然": "自然与湖景", "湖": "自然与湖景",
    "经典": "经典首访", "首次": "经典首访",
}


def interest_themes(interests: list[str] | None, children: int, accessible_required: bool) -> set[str]:
    themes = {t for i in (interests or []) for k, t in INTEREST_THEMES.items() if k in str(i)}
    if children:
        themes.add("亲子博物馆")
    if accessible_required:
        themes.add("轻松无障碍")
    return themes or {"经典首访"}


def search_routes(db: Session, city: str, themes: set[str], accessible_required: bool, limit: int = 4) -> list[dict]:
    """参考路线：同城、主题命中优先；需要无障碍时只取全程可达的路线。"""
    sql = """SELECT route_id, name_zh, city, theme, duration_type, poi_ids, total_minutes, intensity, accessible,
                    suitable_for, highlights, notes
             FROM route WHERE status='active' AND verified_status <> 'expired' AND city=:city
               AND (NOT CAST(:acc AS boolean) OR accessible IS TRUE)
             ORDER BY (theme = ANY(:themes)) DESC, route_id LIMIT :limit"""
    rows = db.execute(text(sql), {"city": city, "acc": accessible_required, "themes": list(themes), "limit": limit})
    return [_row(r) for r in rows.mappings().all()]


def search_history(db: Session, cities: list[str], ctx, tiers: list[str], interests: list[str] | None,
                   limit: int = 3) -> list[dict]:
    """相似历史方案：城市重合度 + 客群（儿童/饮食/无障碍）+ 档次 + 兴趣，打分取前 N。只取成交或修改后成交的。"""
    rows = db.execute(text("""SELECT plan_id, cities, children, dietary, accessibility, hotel_tier, interests, summary,
                                     lessons, outcome FROM history_plan WHERE outcome <> '未成交'
                                AND cities && CAST(:cities AS text[])"""), {"cities": cities}).mappings().all()
    want_diet = set(ctx.restrictions)

    def score(r) -> float:
        s = len(set(r["cities"]) & set(cities)) / len(set(r["cities"]) | set(cities))
        s += 0.5 if bool(r["children"]) == bool(ctx.children) else 0
        s += 0.4 if want_diet and want_diet & set(r["dietary"]) else 0
        s += 0.4 if ctx.accessible_required and r["accessibility"] else 0
        s += 0.3 if set(r["hotel_tier"]) & set(tiers) else 0
        s += 0.1 * len({str(i) for i in interests or []} & set(r["interests"]))
        return s

    return [dict(r) for r in sorted(rows, key=lambda r: (-score(r), r["plan_id"]))[:limit]]


def build_pool(db: Session, cities: list[str], checkin: date, checkout: date, ctx, tiers: list[str],
               require_tags: list[str] | None = None, interests: list[str] | None = None) -> CandidatePool:
    """按城市构建候选池。酒店按每城停留区间检索（简化：用整段行程日期，保证任意夜都可售）。"""
    pool = CandidatePool()
    themes = interest_themes(interests, ctx.children, ctx.accessible_required)
    for city in cities:
        q = HotelQuery(city=city, checkin=checkin, checkout=checkout, adults=ctx.adults, children=ctx.children,
                       child_ages=ctx.child_ages, tiers=tiers, require_tags=require_tags or [],
                       accessible_required=ctx.accessible_required)
        res = search_hotels(db, q)
        pool.hotels.extend(res.candidates)
        pool.funnels[city] = res.funnel
        if res.relaxation_hints:
            pool.hotel_hints[city] = res.relaxation_hints
        pool.restaurants.extend(search_restaurants(db, city, ctx.restrictions, ctx.children))
        pool.pois.extend(search_pois(db, city, ctx.accessible_required, ctx.children))
        pool.vehicles.extend(search_vehicles(db, city, ctx.pax, ctx.luggage_est))
        pool.routes.extend(search_routes(db, city, themes, ctx.accessible_required))
    pool.references = search_history(db, cities, ctx, tiers, interests)
    return pool
