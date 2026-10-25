"""渲染层：事实回填 + 引用校验（防线②）+ 一致性校验（防线③）+ 约束校验汇总。

- 防线②：resource_id 必须在本次候选池内 —— 拦截「看起来合理但不存在」的资源
- 防线③：回填后逐字段与库值比对（候选池摘要 vs 数据库当前值）
失败时把该条目标 blocked 并记录，绝不静默丢弃或留空。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Hotel, Poi, RatePlan, Restaurant, RoomType, Vehicle
from app.schemas.common import ChecklistItem, Verdict, Violation
from app.schemas.facts import PoiFacts, RateFacts, RestaurantFacts, RoomFacts, TripContext, VehicleFacts
from app.schemas.plan import (
    ItineraryPlan, Provenance, RenderedDay, RenderedItem, RenderedPlan, RenderError,
)
from app.services import constraints as C
from app.services.retrieval import CandidatePool

TYPE_PREFIX = {"hotel": "HTL-", "restaurant": "RST-", "poi": "POI-", "vehicle": "VEH-"}


def pick_rate(db: Session, resource_type: str, resource_id: str, start: date, end: date) -> RateFacts | None:
    """选覆盖 [start, end] 的价格档；多条时取更新最晚的。"""
    rows = db.execute(select(RatePlan).where(RatePlan.resource_type == resource_type, RatePlan.resource_id == resource_id,
                                             RatePlan.valid_from <= start, RatePlan.valid_to >= end)
                      .order_by(RatePlan.updated_at.desc())).scalars().all()
    if not rows:
        # 找不到覆盖的档 → 退化取任意一条（让 H8 判 FAIL 而不是 UNKNOWN），仍找不到 → None
        rows = db.execute(select(RatePlan).where(RatePlan.resource_type == resource_type,
                                                 RatePlan.resource_id == resource_id)
                          .order_by(RatePlan.valid_to.desc())).scalars().all()
        if not rows:
            return None
    r = rows[0]
    return RateFacts(rate_id=r.rate_id, resource_type=r.resource_type, resource_id=r.resource_id, valid_from=r.valid_from,
                     valid_to=r.valid_to, blackout_dates=list(r.blackout_dates or []), net_price=r.net_price,
                     price_basis=r.price_basis, season_uplift=r.season_uplift, confidence=r.confidence, updated_at=r.updated_at)


def render_plan(db: Session, plan: ItineraryPlan, pool: CandidatePool, ctx: TripContext,
                now: datetime | None = None) -> tuple[RenderedPlan, list[Violation], dict[str, RateFacts]]:
    """返回 (渲染后的方案, 约束违规列表[含 UNKNOWN], 资源→价格档)。引用/一致性错误转成 code=REF 的 blocking 违规。"""
    now = now or datetime.now(timezone.utc)
    pool_ids = pool.ids()
    pool_index = _pool_index(pool)
    errors: list[RenderError] = []
    violations: list[Violation] = []
    rates: dict[str, RateFacts] = {}
    days: list[RenderedDay] = []

    for d in plan.days:
        the_date = date.fromisoformat(d.date)
        items: list[RenderedItem] = []
        points: list[tuple[float, float] | None] = []
        for i, item in enumerate(d.items):
            ri = RenderedItem(slot=item.slot, type=item.type, resource_id=item.resource_id, room_id=item.room_id,
                              nights=item.nights, start_time=item.start_time, reason_slots=item.reason_slots,
                              reason_note=item.reason_note)
            if item.type in ("free_time", "transfer"):
                items.append(ri)
                continue
            rid = item.resource_id
            # 防线②：ID 必须在候选池内
            if not rid or rid not in pool_ids:
                _block(ri, errors, d.day_index, i, "id_not_in_pool", rid, f"{rid} 不在本次检索候选池")
                items.append(ri)
                continue
            if not rid.startswith(TYPE_PREFIX.get(item.type, "")):
                _block(ri, errors, d.day_index, i, "type_mismatch", rid, f"{rid} 与条目类型 {item.type} 不匹配")
                items.append(ri)
                continue
            if item.type == "hotel" and (not item.room_id or item.room_id not in pool.room_ids_of(rid)):
                _block(ri, errors, d.day_index, i, "id_not_in_pool", item.room_id,
                       f"房型 {item.room_id} 不属于候选池中的 {rid}")
                items.append(ri)
                continue
            # 从 DB 回填事实
            row = _fetch(db, item.type, rid)
            if row is None:
                _block(ri, errors, d.day_index, i, "id_not_found", rid, f"{rid} 在数据库中不存在")
                items.append(ri)
                continue
            # 防线③：候选池摘要 vs 库值逐字段比对
            mismatch = _consistency(item.type, row, pool_index.get(rid))
            if mismatch:
                _block(ri, errors, d.day_index, i, "field_mismatch", rid, f"{rid} 字段与库值不一致：{mismatch}")
                items.append(ri)
                continue
            ri.name_zh, ri.name_local, ri.district = row.name_zh, getattr(row, "name_local", None), getattr(row, "district", None)
            prov = Provenance(resource_id=rid, resource_type=item.type,
                              updated_at=row.updated_at.isoformat() if row.updated_at else None,
                              matched_slots=item.reason_slots)
            vio: list[Violation] = []
            # ───── 逐类型：事实 + 约束 ─────
            if item.type == "hotel":
                room = db.get(RoomType, item.room_id)
                if room is None or room.hotel_id != rid:
                    _block(ri, errors, d.day_index, i, "id_not_found", item.room_id, f"房型 {item.room_id} 在数据库中不存在或不属于 {rid}")
                    items.append(ri)
                    continue
                nights = item.nights or 1
                rf = RoomFacts(hotel_id=rid, room_id=room.room_id, city=row.city, max_occupancy=room.max_occupancy,
                               max_adults=room.max_adults, max_children=room.max_children, min_child_age=room.min_child_age,
                               extra_bed=room.extra_bed, lat=row.lat, lng=row.lng)
                ri.facts = {"room_name": room.name_zh, "bed_config": room.bed_config, "max_occupancy": room.max_occupancy,
                            "max_children": room.max_children, "min_child_age": room.min_child_age,
                            "extra_bed": room.extra_bed, "tier": row.tier, "tags": row.tags, "nights": nights}
                rate = pick_rate(db, "room", room.room_id, the_date, the_date + timedelta(days=nights - 1))
                if rate:
                    rates[room.room_id] = rate
                vio += _collect(C.h1_room_capacity(rf, ctx, d.day_index, i),
                                C.h8_availability(rate, the_date, the_date + timedelta(days=nights - 1), room.room_id, d.day_index, i),
                                C.h11_price_source(rate, room.room_id, now, d.day_index, i))
                points.append((row.lat, row.lng))
            elif item.type == "restaurant":
                rf2 = RestaurantFacts(rest_id=rid, closed_days=row.closed_days, open_from=row.open_from, open_to=row.open_to,
                                      dietary_support=list(row.dietary_support or []), child_friendly=row.child_friendly,
                                      lat=row.lat, lng=row.lng)
                ri.facts = {"cuisine": row.cuisine, "price_band": row.price_band, "closed_days": row.closed_days,
                            "open_from": _t(row.open_from), "open_to": _t(row.open_to),
                            "dietary_support": row.dietary_support, "child_friendly": row.child_friendly}
                rate = pick_rate(db, "restaurant", rid, the_date, the_date)
                if rate:
                    rates[rid] = rate
                vio += _collect(C.h2_dietary(rf2, ctx, d.day_index, i), C.h3_restaurant(rf2, the_date, item.start_time, d.day_index, i),
                                C.h8_availability(rate, the_date, the_date, rid, d.day_index, i),
                                C.h11_price_source(rate, rid, now, d.day_index, i))
                points.append((row.lat, row.lng))
            elif item.type == "poi":
                pf = PoiFacts(poi_id=rid, closed_days=row.closed_days, open_from=row.open_from, open_to=row.open_to,
                              accessible=row.accessible, intensity=row.intensity, duration_min=row.duration_min,
                              lat=row.lat, lng=row.lng)
                ri.facts = {"category": row.category, "closed_days": row.closed_days, "open_from": _t(row.open_from),
                            "open_to": _t(row.open_to), "duration_min": row.duration_min, "intensity": row.intensity,
                            "accessible": row.accessible, "tags": row.tags}
                rate = pick_rate(db, "ticket", rid, the_date, the_date)
                if rate:
                    rates[rid] = rate
                vio += _collect(C.h3_poi(pf, the_date, item.start_time, d.day_index, i),
                                C.h8_availability(rate, the_date, the_date, rid, d.day_index, i),
                                C.h11_price_source(rate, rid, now, d.day_index, i))
                if ctx.accessible_required:
                    vio += _collect(_h9_accessible(pf, d.day_index, i))
                points.append((row.lat, row.lng))
            elif item.type == "vehicle":
                vf = VehicleFacts(vehicle_id=rid, seats=row.seats, luggage_28=row.luggage_28)
                ri.facts = {"seats": row.seats, "luggage_28": row.luggage_28, "service_hours": row.service_hours}
                rate = pick_rate(db, "vehicle", rid, the_date, the_date)
                if rate:
                    rates[rid] = rate
                vio += _collect(C.h4_vehicle(vf, ctx, d.day_index, i),
                                C.h8_availability(rate, the_date, the_date, rid, d.day_index, i),
                                C.h11_price_source(rate, rid, now, d.day_index, i))
            # H12 数据治理：待校验 → UNKNOWN；同时把来源标注写进溯源浮层
            vio += _collect(C.h12_verified(row.verified_status, rid, row.review_due, d.day_index, i))
            prov.source_type, prov.verified_status = row.source_type, row.verified_status
            prov.verified_at = row.verified_at.isoformat() if row.verified_at else None
            prov.review_due = row.review_due.isoformat() if row.review_due else None
            if rate:
                prov.price_source, prov.rate_id = rate.confidence, rate.rate_id
            prov.satisfied_constraints = _satisfied(item.type, vio)
            prov.unknown_constraints = sorted({v.code for v in vio if v.verdict == Verdict.UNKNOWN})
            ri.provenance = prov
            violations += vio
            items.append(ri)
        # H5 同日通勤
        h5 = C.h5_commute(points, d.city, d.is_transfer, d.day_index)
        if h5:
            violations.append(h5)
        commute = C.commute_minutes([p for p in points if p], d.city) if len([p for p in points if p]) >= 2 else 0
        days.append(RenderedDay(day_index=d.day_index, date=d.date, weekday=C.dow(the_date), city=d.city, theme=d.theme,
                                is_transfer=d.is_transfer, items=items, commute_min_est=commute))

    rendered = RenderedPlan(days=days, assumptions=plan.assumptions, render_errors=errors)
    for e in errors:
        violations.append(Violation(code="REF", verdict=Verdict.FAIL, day_index=e.day_index, item_index=e.item_index,
                                    resource_id=e.resource_id, message=f"引用校验拦截（{e.kind}）：{e.detail}", blocking=True))
    return rendered, violations, rates


def structural_violations(rendered: RenderedPlan) -> list[Violation]:
    """结构性硬规则（确定性）：S1 非最后一天必须有可用住宿；S2 不允许空白天。防止「缺条目的方案」静默通过。"""
    out: list[Violation] = []
    last = max((d.day_index for d in rendered.days), default=0)
    for d in rendered.days:
        if not d.items:
            out.append(Violation(code="S2", verdict=Verdict.FAIL, day_index=d.day_index, message="当日没有任何安排（空白天）", blocking=True))
        if d.day_index < last and not any(i.type == "hotel" and i.status == "ok" for i in d.items):
            out.append(Violation(code="S1", verdict=Verdict.FAIL, day_index=d.day_index, message="当日缺少可用住宿", blocking=True))
    return out


def build_checklist(violations: list[Violation]) -> list[ChecklistItem]:
    return [ChecklistItem(code=v.code, day_index=v.day_index, resource_id=v.resource_id,
                          what_to_verify=v.verify_hint or v.message, reason=v.message)
            for v in violations if v.verdict == Verdict.UNKNOWN]


# ───────────────────────── helpers ─────────────────────────
def _block(ri: RenderedItem, errors: list[RenderError], day_index: int, item_index: int, kind: str,
           rid: str | None, detail: str) -> None:
    ri.status, ri.block_reason = "blocked", detail
    errors.append(RenderError(day_index=day_index, item_index=item_index, kind=kind, resource_id=rid, detail=detail))


def _collect(*vs: Violation | None) -> list[Violation]:
    return [v for v in vs if v is not None]


def _fetch(db: Session, item_type: str, rid: str):
    model = {"hotel": Hotel, "restaurant": Restaurant, "poi": Poi, "vehicle": Vehicle}[item_type]
    return db.get(model, rid)


def _pool_index(pool: CandidatePool) -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for h in pool.hotels:
        idx.setdefault(h.hotel_id, {"city": h.city, "tier": h.tier, "lat": h.lat, "lng": h.lng})
    for r in pool.restaurants:
        idx[r["rest_id"]] = {"city": r["city"], "closed_days": r["closed_days"], "dietary_support": r["dietary_support"]}
    for p in pool.pois:
        idx[p["poi_id"]] = {"city": p["city"], "closed_days": p["closed_days"], "accessible": p["accessible"]}
    for v in pool.vehicles:
        idx[v["vehicle_id"]] = {"city": v["city"], "seats": v["seats"], "luggage_28": v["luggage_28"]}
    return idx


def _consistency(item_type: str, row, snapshot: dict | None) -> str | None:
    """防线③：候选池里的字段快照必须与库值一致；不一致说明数据在检索后变了或被篡改。"""
    if not snapshot:
        return None
    for k, v in snapshot.items():
        dbv = getattr(row, k, None)
        if isinstance(dbv, list) or isinstance(v, list):
            if list(dbv or []) != list(v or []):
                return f"{k}: 候选池={v} 库值={dbv}"
        elif isinstance(dbv, float) or isinstance(v, float):
            if dbv is None or v is None or abs(float(dbv) - float(v)) > 1e-6:
                return f"{k}: 候选池={v} 库值={dbv}"
        elif dbv != v:
            return f"{k}: 候选池={v} 库值={dbv}"
    return None


def _satisfied(item_type: str, vio: list[Violation]) -> list[str]:
    checked = {"hotel": ["H1", "H8", "H11", "H12"], "restaurant": ["H2", "H3", "H8", "H11", "H12"],
               "poi": ["H3", "H8", "H11", "H12"], "vehicle": ["H4", "H8", "H11", "H12"]}[item_type]
    bad = {v.code for v in vio}
    return [c for c in checked if c not in bad]


def _h9_accessible(poi: PoiFacts, day_index: int, item_index: int) -> Violation | None:
    """H9 无障碍（M0 不在 7 条硬约束内，仅在需求明确时做三态提示，不阻断）。"""
    if poi.accessible is None:
        return Violation(code="H9", verdict=Verdict.UNKNOWN, day_index=day_index, item_index=item_index,
                         resource_id=poi.poi_id, message="景点无障碍适配未记录", blocking=False,
                         verify_hint=f"核实 {poi.poi_id} 是否有轮椅通道 / 电梯")
    if poi.accessible is False:
        return Violation(code="H9", verdict=Verdict.FAIL, day_index=day_index, item_index=item_index,
                         resource_id=poi.poi_id, message="景点不适配无障碍需求", blocking=True)
    return None


def _t(t) -> str | None:
    return t.strftime("%H:%M") if t else None
