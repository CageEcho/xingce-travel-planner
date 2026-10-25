"""硬约束——三态判定 PASS / FAIL / UNKNOWN。确定性 Python，不经过模型。

⚠️ 本项目最容易写错的地方：`if row.min_child_age and row.min_child_age > age` 会让 NULL 静默通过。
   每个允许 NULL 的字段都必须显式三分支：None → UNKNOWN；不满足 → FAIL；满足 → PASS。

| 约束 | 判定 | UNKNOWN 条件 |
| H1  | 房型容量与儿童年龄 | min_child_age IS NULL 且有儿童 |
| H2  | 饮食禁忌 ⊆ dietary_support | dietary_support 为空 且客户有限制 |
| H3  | 营业日 / 营业时段 | closed_days IS NULL |
| H4  | 车辆座位 AND 行李 | luggage_28 IS NULL |
| H5  | 同日通勤 ≤ 180（转场日 300） | 缺经纬度 |
| H8  | 可售期 valid_from ≤ 日期 ≤ valid_to 且不在 blackout | 未找到价格档 |
| H11 | 价格来源 contracted 且 90 天内 | 其余情况 → UNKNOWN；超 RESOURCE_STALENESS_DAYS → FAIL |
| H12 | 资料已人工校验（数据治理） | verified_status=pending → UNKNOWN；expired → FAIL（正常情况下检索已排除） |
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timezone

from app.core.config import settings
from app.schemas.common import Verdict, Violation
from app.schemas.facts import PoiFacts, RateFacts, RestaurantFacts, RoomFacts, TripContext, VehicleFacts

WEEKDAY_ZH = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
CITY_SPEED_KMH = {"东京": 22.0, "京都": 25.0, "箱根": 30.0}
ROAD_FACTOR = 1.35


def dow(d: date) -> int:
    """0=周日..6=周六（与 DDL 约定一致；Python weekday() 是 0=周一）。"""
    return (d.weekday() + 1) % 7


def _v(code: str, verdict: Verdict, day_index: int, item_index: int | None, resource_id: str | None,
       message: str, verify_hint: str | None = None) -> Violation:
    return Violation(code=code, verdict=verdict, day_index=day_index, item_index=item_index,
                     resource_id=resource_id, message=message, blocking=(verdict == Verdict.FAIL),
                     verify_hint=verify_hint)


# ───────────────────────── H1 房型容量 + 儿童年龄 ─────────────────────────
def h1_room_capacity(room: RoomFacts, ctx: TripContext, day_index: int = 0,
                     item_index: int | None = None) -> Violation | None:
    pax = ctx.pax
    if room.max_occupancy * ctx.rooms < pax:
        return _v("H1", Verdict.FAIL, day_index, item_index, room.room_id,
                  f"房型最大入住 {room.max_occupancy} 人（{ctx.rooms} 间），不足 {pax} 人")
    if room.max_children * ctx.rooms < ctx.children:
        return _v("H1", Verdict.FAIL, day_index, item_index, room.room_id,
                  f"房型最多接待 {room.max_children} 名儿童，实际 {ctx.children} 名")
    if ctx.children > 0:
        # ⭐ 三态：未记录 ≠ 通过
        if room.min_child_age is None:
            return _v("H1", Verdict.UNKNOWN, day_index, item_index, room.room_id,
                      "该房型最低入住年龄未记录，需向供应商确认",
                      verify_hint=f"向酒店确认房型 {room.room_id} 是否接待 {min(ctx.child_ages) if ctx.child_ages else '?'} 岁儿童")
        if ctx.child_ages and min(ctx.child_ages) < room.min_child_age:
            return _v("H1", Verdict.FAIL, day_index, item_index, room.room_id,
                      f"该房型限 {room.min_child_age} 岁以上入住，随行儿童 {min(ctx.child_ages)} 岁")
    return None


# ───────────────────────── H2 饮食禁忌 ─────────────────────────
def h2_dietary(rest: RestaurantFacts, ctx: TripContext, day_index: int = 0,
               item_index: int | None = None) -> Violation | None:
    need = ctx.restrictions
    if not need:
        return None
    if not rest.dietary_support:
        return _v("H2", Verdict.UNKNOWN, day_index, item_index, rest.rest_id,
                  f"餐厅未记录饮食支持信息，无法判定是否满足 {', '.join(need)}",
                  verify_hint=f"向餐厅确认能否提供 {', '.join(need)} 的替代菜单")
    missing = [d for d in need if d not in rest.dietary_support]
    if missing:
        return _v("H2", Verdict.FAIL, day_index, item_index, rest.rest_id,
                  f"餐厅不支持客户的饮食限制：{', '.join(missing)}")
    return None


# ───────────────────────── H3 营业日 / 营业时段 ─────────────────────────
def h3_opening(closed_days: list[int] | None, open_from: time | None, open_to: time | None,
               visit_date: date, start_time: str | None, resource_id: str,
               day_index: int = 0, item_index: int | None = None) -> Violation | None:
    if closed_days is None:
        return _v("H3", Verdict.UNKNOWN, day_index, item_index, resource_id,
                  f"休息日未记录，无法判定 {visit_date.isoformat()}（{WEEKDAY_ZH[dow(visit_date)]}）是否营业",
                  verify_hint=f"核实 {resource_id} 在 {visit_date.isoformat()} 的营业状态")
    wd = dow(visit_date)
    if wd in closed_days:
        return _v("H3", Verdict.FAIL, day_index, item_index, resource_id,
                  f"{visit_date.isoformat()} 是{WEEKDAY_ZH[wd]}，该资源当日休息")
    if start_time and open_from and open_to:
        try:
            hh, mm = (int(x) for x in start_time.split(":"))
            t = time(hh, mm)
        except ValueError:
            t = None
        if t is not None and not (open_from <= t <= open_to):
            return _v("H3", Verdict.FAIL, day_index, item_index, resource_id,
                      f"安排时间 {start_time} 不在营业时段 {open_from:%H:%M}–{open_to:%H:%M} 内")
    return None


def h3_restaurant(rest: RestaurantFacts, visit_date: date, start_time: str | None, day_index: int = 0,
                  item_index: int | None = None) -> Violation | None:
    return h3_opening(rest.closed_days, rest.open_from, rest.open_to, visit_date, start_time, rest.rest_id,
                      day_index, item_index)


def h3_poi(poi: PoiFacts, visit_date: date, start_time: str | None, day_index: int = 0,
           item_index: int | None = None) -> Violation | None:
    return h3_opening(poi.closed_days, poi.open_from, poi.open_to, visit_date, start_time, poi.poi_id,
                      day_index, item_index)


# ───────────────────────── H4 车辆座位 AND 行李 ─────────────────────────
def h4_vehicle(veh: VehicleFacts, ctx: TripContext, day_index: int = 0,
               item_index: int | None = None) -> Violation | None:
    if veh.seats < ctx.pax:
        return _v("H4", Verdict.FAIL, day_index, item_index, veh.vehicle_id,
                  f"车辆座位 {veh.seats}，不足 {ctx.pax} 人")
    if veh.luggage_28 is None:
        return _v("H4", Verdict.UNKNOWN, day_index, item_index, veh.vehicle_id,
                  "车辆行李容量未记录，无法判定能否装下行李",
                  verify_hint=f"向车行确认 {veh.vehicle_id} 可装 28 寸行李箱数（需 ≥{ctx.luggage_est}）")
    if veh.luggage_28 < ctx.luggage_est:
        return _v("H4", Verdict.FAIL, day_index, item_index, veh.vehicle_id,
                  f"车辆可装 {veh.luggage_28} 只 28 寸箱，估算需 {ctx.luggage_est} 只（座位够但行李不够）")
    return None


# ───────────────────────── H5 同日通勤上限 ─────────────────────────
def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def commute_minutes(points: list[tuple[float, float]], city: str) -> int:
    """M0 简化：haversine 直线 × 1.35 路网系数 ÷ 城市均速。"""
    speed = CITY_SPEED_KMH.get(city, 25.0)
    total_km = sum(haversine_km(*points[i], *points[i + 1]) for i in range(len(points) - 1))
    return int(round(total_km * ROAD_FACTOR / speed * 60))


def h5_commute(points: list[tuple[float, float] | None], city: str, is_transfer: bool,
               day_index: int = 0) -> Violation | None:
    if any(p is None for p in points):
        return _v("H5", Verdict.UNKNOWN, day_index, None, None, "当日有条目缺少经纬度，通勤时长无法判定",
                  verify_hint="补齐资源经纬度后重新校验")
    pts = [p for p in points if p is not None]
    if len(pts) < 2:
        return None
    minutes = commute_minutes(pts, city)
    limit = settings.commute_max_min_transfer if is_transfer else settings.commute_max_min
    if minutes > limit:
        return _v("H5", Verdict.FAIL, day_index, None, None,
                  f"当日通勤估算 {minutes} 分钟，超过上限 {limit} 分钟{'（转场日）' if is_transfer else ''}")
    return None


# ───────────────────────── H8 资源可售期 ─────────────────────────
def h8_availability(rate: RateFacts | None, start: date, end: date, resource_id: str,
                    day_index: int = 0, item_index: int | None = None) -> Violation | None:
    """start..end 为占用日期（酒店：入住到退房前一日；单日资源 start=end）。"""
    if rate is None:
        return _v("H8", Verdict.UNKNOWN, day_index, item_index, resource_id,
                  "未找到该资源在此日期的价格档，可售期无法判定",
                  verify_hint=f"向供应商确认 {resource_id} 在 {start.isoformat()} 是否可售及报价")
    if rate.valid_from > start or rate.valid_to < end:
        return _v("H8", Verdict.FAIL, day_index, item_index, resource_id,
                  f"价格档 {rate.rate_id} 可售期 {rate.valid_from}–{rate.valid_to} 不覆盖 {start}–{end}")
    hit = [d for d in rate.blackout_dates if start <= d <= end]
    if hit:
        return _v("H8", Verdict.FAIL, day_index, item_index, resource_id,
                  f"{', '.join(d.isoformat() for d in hit)} 为不可售日期（blackout）")
    return None


# ───────────────────────── H11 价格来源 ─────────────────────────
def h11_price_source(rate: RateFacts | None, resource_id: str, now: datetime | None = None,
                     day_index: int = 0, item_index: int | None = None) -> Violation | None:
    now = now or datetime.now(timezone.utc)
    if rate is None:
        return _v("H11", Verdict.UNKNOWN, day_index, item_index, resource_id, "无价格记录，报价需人工核对",
                  verify_hint=f"向供应商索取 {resource_id} 的最新报价")
    upd = rate.updated_at if rate.updated_at.tzinfo else rate.updated_at.replace(tzinfo=timezone.utc)
    age_days = (now - upd).days
    if age_days > settings.resource_staleness_days:
        return _v("H11", Verdict.FAIL, day_index, item_index, resource_id,
                  f"价格已 {age_days} 天未更新（超过 {settings.resource_staleness_days} 天），不得用于报价")
    if rate.confidence == "contracted" and age_days <= settings.price_staleness_days:
        return None
    reason = ("非合约价（%s）" % rate.confidence) if rate.confidence != "contracted" else f"合约价已 {age_days} 天未更新"
    return _v("H11", Verdict.UNKNOWN, day_index, item_index, resource_id, f"{reason}，报价需人工核对",
              verify_hint=f"与供应商核对 {resource_id} 的价格档 {rate.rate_id} 是否仍有效")


# ───────────────────────── H12 资料校验状态（数据治理） ─────────────────────────
def h12_verified(status: str | None, resource_id: str, review_due: date | None = None,
                 day_index: int = 0, item_index: int | None = None) -> Violation | None:
    if status in (None, "verified"):
        return None
    if status == "expired":
        return _v("H12", Verdict.FAIL, day_index, item_index, resource_id,
                  f"资料复核已过期（应于 {review_due} 前复核），不得用于方案")
    return _v("H12", Verdict.UNKNOWN, day_index, item_index, resource_id, "资料尚未人工校验，报价前需核实",
              verify_hint=f"按来源复核 {resource_id} 的营业、设施与政策信息" + (f"（截止 {review_due}）" if review_due else ""))
