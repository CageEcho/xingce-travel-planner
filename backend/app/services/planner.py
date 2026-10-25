"""行程编排 + 回退重排。

两种编排器（由 settings.planner_mode 选择）：
- llm：Claude 结构化输出（只输出 resource_id，防线①）
- heuristic：确定性编排器。用途：eval --dry-run 只测规则层；LLM 不可用时的降级路径（PRD-v3 §15）。

回退重排：validating 发现 blocking 违规 → 把违规写进下一轮 constraints → 重排，最多 MAX_REPLAN_ROUNDS；
仍失败则带违规交人工，绝不静默通过。
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.core.llm import LLMResult, load_prompt, parse_structured
from app.schemas.common import ChecklistItem, Violation
from app.schemas.cost import CostSummary
from app.schemas.facts import RateFacts, TripContext
from app.schemas.plan import ItineraryPlan, PlannedDay, PlannedItem, RenderedPlan
from app.schemas.slots import SlotSet
from app.services import constraints as C
from app.services.cost import calc_cost
from app.services.recommend import recommend_products
from app.services.render import build_checklist, render_plan, structural_violations
from app.schemas.search import HotelCandidate
from app.services.retrieval import CandidatePool

CITY_ORDER = ["东京", "箱根", "京都"]   # 地理顺序：东京 → 箱根 → 京都（或反向）
log = logging.getLogger("app.planner")


# ───────────────────────── 需求卡 → 行程骨架 ─────────────────────────
def trip_dates(slots: SlotSet) -> tuple[date, int]:
    """(起始日期, 天数)。缺起始日期时按 duration 推 10 月中旬；缺天数时按起止推。"""
    ds = slots.get("date_start")
    de = slots.get("date_end")
    n = slots.get("duration_days")
    start = date.fromisoformat(str(ds)) if ds else None
    end = date.fromisoformat(str(de)) if de else None
    days = int(n) if n else None
    if start and end and not days:
        days = (end - start).days + 1
    if start and days:
        return start, days
    if start and not days:
        return start, 7
    if days and end:
        return end - timedelta(days=days - 1), days
    return date(2026, 10, 15), days or 7


def city_sequence(slots: SlotSet, days: int) -> list[tuple[str, int]]:
    cities = slots.get("destination_cities") or ["东京"]
    if isinstance(cities, str):
        cities = [cities]
    cities = [c for c in CITY_ORDER if c in cities] or ["东京"]
    # 天数分配：箱根最多 2 天，其余按比例
    alloc = {c: 1 for c in cities}
    remaining = days - len(cities)
    while remaining > 0:
        for c in cities:
            if remaining <= 0:
                break
            if c == "箱根" and alloc[c] >= 2:
                continue
            alloc[c] += 1
            remaining -= 1
        if all(c == "箱根" for c in cities):
            alloc["箱根"] += remaining
            remaining = 0
    return [(c, alloc[c]) for c in cities]


WEEKDAY_ZH = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]


def build_day_skeleton(start: date, seq: list[tuple[str, int]]) -> list[dict]:
    """逐日骨架：day_index / date / weekday(0=周日..6=周六) / weekday_zh / city / is_transfer。"""
    out: list[dict] = []
    d = start
    prev_city: str | None = None
    for city, n in seq:
        for _ in range(n):
            wd = (d.weekday() + 1) % 7   # Python: 周一=0 → 转成 0=周日
            out.append({"day_index": len(out) + 1, "date": d.isoformat(), "weekday": wd, "weekday_zh": WEEKDAY_ZH[wd],
                        "city": city, "is_transfer": prev_city is not None and prev_city != city})
            prev_city = city
            d += timedelta(days=1)
    return out


def build_constraint_brief(ctx: TripContext, slots: SlotSet, previous: list[Violation] | None = None,
                           rendered: RenderedPlan | None = None) -> str:
    lines = ["- 每天的日期与星期已在 requirement.skeleton 中给出（weekday 0=周日..6=周六）；安排景点/餐厅前必须对照候选的 closed_days，休息日的资源当天不得使用",
             f"- 人数：{ctx.adults} 成人 + {ctx.children} 儿童（年龄 {ctx.child_ages}），需 {ctx.rooms} 间房",
             f"- 饮食限制：{ctx.restrictions or '无'}", f"- 无障碍：{'需要' if ctx.accessible_required else '不需要'}",
             f"- 同日通勤上限 {settings.commute_max_min} 分钟（转场日 {settings.commute_max_min_transfer}）",
             f"- 节奏：{slots.get('pace') or 'moderate'}；兴趣：{slots.get('interests') or []}"]
    if previous:
        lines.append("\n## 上一轮违规（必须修正，对应 resource_id 在该日期不得再用）")
        date_of = {d.day_index: d.date for d in rendered.days} if rendered else {}
        for v in previous:
            lines.append(f"- Day {v.day_index}（{date_of.get(v.day_index, '')}）的 `{v.resource_id or '-'}` 违反 {v.code}：{v.message}。请更换。")
    return "\n".join(lines)


# ───────────────────────── LLM 编排 ─────────────────────────
def plan_itinerary_llm(slots: SlotSet, pool: CandidatePool, brief: str, skeleton: list[dict]) -> tuple[ItineraryPlan, LLMResult]:
    system = load_prompt("plan_itinerary.md")
    req = {"slots": json.loads(slots.model_dump_json(exclude_none=True)), "skeleton": skeleton}
    user = (f"<requirement>\n{json.dumps(req, ensure_ascii=False)}\n</requirement>\n\n"
            f"<candidates>\n{json.dumps(pool.to_compact(), ensure_ascii=False)}\n</candidates>\n\n"
            f"<constraints>\n{brief}\n</constraints>")
    res = parse_structured(system=system, user=user, output_format=ItineraryPlan, max_tokens=32000,
                           effort=settings.plan_effort)
    assert isinstance(res.parsed, ItineraryPlan)
    return res.parsed, res


# ───────────────────────── 确定性修补（回退用尽后） ─────────────────────────
SLOT_ZH = {"morning": "上午", "lunch": "午餐", "afternoon": "下午", "dinner": "晚餐", "evening": "晚间", "accommodation": "住宿", "transport": "用车"}


def _open_on(row: dict, d: date) -> int:
    cd = row.get("closed_days")
    if cd is None:
        return 1          # 未记录：可用但次优（会进待核实清单）
    return 2 if C.dow(d) not in cd else 0


def repair_blocking(plan: ItineraryPlan, blocking: list[Violation], pool: CandidatePool, ctx: TripContext,
                    banned: set[tuple[str, str]]) -> tuple[ItineraryPlan, list[str]]:
    """LLM 回退 3 轮仍有资源级 blocking 违规时，用确定性规则替换违规条目（同城、同类型、当日营业、容量/行李达标）。
    餐厅 / 景点换不到合规替代时改为「自理 / 待顾问安排」并写入说明（不用不合适的资源凑数）；
    住宿 / 用车换不到的保留原样交人工。不改模型输出边界：替换的仍只是 resource_id。"""
    plan = plan.model_copy(deep=True)
    used = {it.resource_id for d in plan.days for it in d.items if it.resource_id}
    notes: list[str] = []
    hotel_for_city: dict[str, HotelCandidate] = {}
    city_of: dict[str, str] = {}
    for h in pool.hotels:
        city_of[h.hotel_id] = h.city
    for r in pool.restaurants:
        city_of[r["rest_id"]] = r["city"]
    for r in pool.pois:
        city_of[r["poi_id"]] = r["city"]
    for x in pool.vehicles:
        city_of[x["vehicle_id"]] = x["city"]

    # 展开成「(违规, 待换条目下标)」：资源级违规直接定位；H5（同日通勤超限）→ 该日所有不在当天城市的资源
    targets: list[tuple[Violation, int]] = []
    for v in blocking:
        if not (1 <= v.day_index <= len(plan.days)):
            continue
        day = plan.days[v.day_index - 1]
        if v.item_index is not None:
            if v.item_index < len(day.items):
                targets.append((v, v.item_index))
        elif v.code == "H5":
            for i, it in enumerate(day.items):
                if it.resource_id and city_of.get(it.resource_id) not in (None, day.city):
                    targets.append((v, i))
    seen_targets: set[tuple[int, int]] = set()
    for v, idx in targets:
        if (v.day_index, idx) in seen_targets:
            continue
        seen_targets.add((v.day_index, idx))
        day = plan.days[v.day_index - 1]
        item = day.items[idx]
        d = date.fromisoformat(day.date)
        old = item.resource_id
        new_id: str | None = None
        if item.type == "restaurant":
            cands = [r for r in pool.restaurants if r["city"] == day.city and r["rest_id"] not in used
                     and (day.date, r["rest_id"]) not in banned and _open_on(r, d) == 2
                     and (not ctx.dietary or ctx.dietary == ["none"] or set(ctx.dietary) <= set(r["dietary_support"]))]
            cands.sort(key=lambda r: (r["child_friendly"] is None if ctx.children else False, r["price_band"] not in ("high", "luxury")))
            new_id = cands[0]["rest_id"] if cands else None
        elif item.type == "poi":
            cands = [r for r in pool.pois if r["city"] == day.city and r["poi_id"] not in used
                     and (day.date, r["poi_id"]) not in banned and _open_on(r, d) == 2
                     and (not day.is_transfer or r["intensity"] != "hard")
                     and (not ctx.accessible_required or r.get("accessible") is True)]
            new_id = cands[0]["poi_id"] if cands else None
        elif item.type == "vehicle":
            cands = [x for x in pool.vehicles if x["city"] == day.city and (day.date, x["vehicle_id"]) not in banned
                     and x["seats"] >= ctx.pax and x["luggage_28"] is not None and x["luggage_28"] >= ctx.luggage_est]
            cands.sort(key=lambda x: (x["seats"], x["luggage_28"]))
            new_id = cands[0]["vehicle_id"] if cands else None
        elif item.type == "hotel":
            h = hotel_for_city.get(day.city)
            if h is None:
                min_age = min(ctx.child_ages) if ctx.child_ages else None
                cands = [x for x in pool.hotels if x.city == day.city and x.max_occupancy >= ctx.pax and x.max_children >= ctx.children
                         and (ctx.children == 0 or (x.min_child_age is not None and (min_age is None or x.min_child_age <= min_age)))
                         and (day.date, x.hotel_id) not in banned and (day.date, x.room_id) not in banned]
                cands.sort(key=lambda x: (x.confidence != "contracted", -x.score))
                h = cands[0] if cands else None
                if h:
                    hotel_for_city[day.city] = h
            if h and (h.hotel_id != item.resource_id or h.room_id != item.room_id):
                item.resource_id, item.room_id = h.hotel_id, h.room_id
                notes.append(f"Day {v.day_index} 住宿由系统自动替换：{old} → {h.hotel_id}/{h.room_id}（{v.message}）")
            continue
        if new_id is None and item.type in ("restaurant", "poi"):
            item.type, item.resource_id, item.room_id = "free_time", None, None
            item.reason_note = "候选池内没有当天可用且满足约束的资源，改为自理 / 待顾问安排"
            notes.append(f"Day {v.day_index} {SLOT_ZH.get(item.slot, item.slot)}：没有满足约束的替代资源，"
                         f"已移除 {old}，改为自理 / 待顾问安排（{v.message}）")
            continue
        if new_id:
            used.add(new_id)
            item.resource_id = new_id
            item.reason_note = (item.reason_note + "（系统按约束自动替换）").strip("（）") if not item.reason_note else item.reason_note + "（系统按约束自动替换）"
            notes.append(f"Day {v.day_index} {SLOT_ZH.get(item.slot, item.slot)}由系统自动替换：{old} → {new_id}（{v.message}）")
    return plan, notes


# ───────────────────────── 确定性编排器 ─────────────────────────
# 客户兴趣（自由文本）→ 景点标签：规则编排兜底时也优先满足偏好
INTEREST_TAGS = {
    "动物": {"animals", "kids"}, "火车": {"trains"}, "动漫": {"anime"}, "亲子": {"kids"}, "儿童": {"kids"},
    "艺术": {"art"}, "美术": {"art"}, "博物馆": {"history", "art"}, "寺": {"temple", "shrine", "heritage"},
    "神社": {"shrine"}, "历史": {"history", "heritage"}, "文化": {"culture", "heritage"}, "庭园": {"garden"},
    "温泉": {"onsen", "day_spa"}, "美食": {"food", "market"}, "购物": {"shopping", "shopping_street", "retro"},
    "摄影": {"view", "night", "scenic"}, "夜景": {"night", "view"}, "自然": {"nature", "lake", "forest"},
}


def interest_tags(slots: SlotSet, children: int) -> set[str]:
    raw = slots.get("interests") or []
    interests = raw if isinstance(raw, list) else [raw]
    tags = {t for i in interests for k, ts in INTEREST_TAGS.items() if k in str(i) for t in ts}
    return tags | ({"kids"} if children else set())


def plan_itinerary_heuristic(slots: SlotSet, pool: CandidatePool, ctx: TripContext, start: date,
                             seq: list[tuple[str, int]], banned: set[tuple[str, str]] | None = None) -> ItineraryPlan:
    banned = banned or set()
    used: set[str] = set()
    days: list[PlannedDay] = []
    idx = 0
    total_days = sum(n for _, n in seq)
    pace = str(slots.get("pace") or "moderate")
    wanted = interest_tags(slots, ctx.children)

    def open_on(row: dict, d: date) -> int:
        cd = row.get("closed_days")
        if cd is None:
            return 1          # 未记录：可用但次优
        return 2 if C.dow(d) not in cd else 0

    def pick(rows: list[dict], key: str, d: date, ref: tuple[float, float] | None, pred=lambda r: True) -> dict | None:
        best, best_key = None, None
        for r in rows:
            rid = r[key]
            if rid in used or (d.isoformat(), rid) in banned or not pred(r):
                continue
            o = open_on(r, d)
            if o == 0:
                continue
            dist = C.haversine_km(ref[0], ref[1], r["lat"], r["lng"]) if ref and r.get("lat") else 0.0
            hit = bool(wanted & set(r.get("tags") or [])) if key == "poi_id" else False
            k = (-o, -hit, dist)                 # 营业 > 命中兴趣 > 距离近
            if best_key is None or k < best_key:
                best, best_key = r, k
        return best

    for city, n_days in seq:
        hotels = [h for h in pool.hotels if h.city == city]
        # 首选合约价、容量最贴近的房型
        hotels.sort(key=lambda h: (h.confidence != "contracted", h.child_age_unknown, -h.score))
        hotel = next((h for h in hotels if all((d, h.hotel_id) not in banned and (d, h.room_id) not in banned
                                               for d in [(start + timedelta(days=idx + k)).isoformat() for k in range(n_days)])), None)
        rests = [r for r in pool.restaurants if r["city"] == city]
        rests.sort(key=lambda r: (len(r["dietary_support"]) == 0, r["child_friendly"] is None))
        pois = [p for p in pool.pois if p["city"] == city]
        veh = next((v for v in sorted([v for v in pool.vehicles if v["city"] == city],
                                      key=lambda v: (v["luggage_28"] is None, v["seats"]))), None)
        for k in range(n_days):
            d = start + timedelta(days=idx)
            is_transfer = k == 0 and idx > 0
            ref = (hotel.lat, hotel.lng) if hotel else None
            items: list[PlannedItem] = []
            if is_transfer and veh:
                items.append(PlannedItem(slot="transport", type="vehicle", resource_id=veh["vehicle_id"], start_time="09:00",
                                         reason_slots=["destination_cities"], reason_note="转场日包车，行李随车不用搬"))
            if not is_transfer:
                p1 = pick(pois, "poi_id", d, ref, lambda r: r["intensity"] != "hard")
                if p1:
                    used.add(p1["poi_id"])
                    items.append(PlannedItem(slot="morning", type="poi", resource_id=p1["poi_id"], start_time="09:30",
                                             reason_slots=["interests"], reason_note="上午安排步行强度较低的景点"))
            r1 = pick(rests, "rest_id", d, ref, lambda r: r["price_band"] in ("mid", "high"))
            if r1:
                used.add(r1["rest_id"])
                items.append(PlannedItem(slot="lunch", type="restaurant", resource_id=r1["rest_id"], start_time="12:30",
                                         reason_slots=["dietary"], reason_note="支持客户饮食限制的午餐"))
            if pace != "relaxed" or is_transfer:
                p2 = pick(pois, "poi_id", d, ref, lambda r: r["intensity"] != "hard")
                if p2:
                    used.add(p2["poi_id"])
                    items.append(PlannedItem(slot="afternoon", type="poi", resource_id=p2["poi_id"], start_time="14:30",
                                             reason_slots=["interests"], reason_note="下午就近安排第二处景点"))
            else:
                items.append(PlannedItem(slot="afternoon", type="free_time", reason_slots=["pace"], reason_note="节奏放松，留白"))
            r2 = pick(rests, "rest_id", d, ref, lambda r: r["price_band"] in ("high", "luxury"))
            if r2:
                used.add(r2["rest_id"])
                items.append(PlannedItem(slot="dinner", type="restaurant", resource_id=r2["rest_id"], start_time="18:30",
                                         reason_slots=["dietary", "hotel_tier"], reason_note="与客户档次匹配的晚餐"))
            if idx < total_days - 1 and hotel:
                items.append(PlannedItem(slot="accommodation", type="hotel", resource_id=hotel.hotel_id, room_id=hotel.room_id,
                                         nights=(n_days - k if idx + n_days - k <= total_days - 1 else total_days - 1 - idx) if k == 0 else None,
                                         reason_slots=["hotel_tier", "children"], reason_note="连住减少搬酒店"))
            days.append(PlannedDay(day_index=idx + 1, date=d.isoformat(), city=city,
                                   theme=f"{city}{'转场' if is_transfer else '深度'}日", is_transfer=is_transfer, items=items))
            idx += 1
    assumptions = []
    if any(c for c, _ in seq if not [h for h in pool.hotels if h.city == c]):
        assumptions.append("部分城市在硬过滤后无可用酒店，已留空待顾问处理")
    return ItineraryPlan(days=days, assumptions=assumptions)


# ───────────────────────── 生成主流程（含回退重排） ─────────────────────────
@dataclass
class GenerationResult:
    rendered: RenderedPlan
    violations: list[Violation]
    checklist: list[ChecklistItem]
    cost: CostSummary
    rounds: int
    rates: dict[str, RateFacts]
    llm_calls: list[dict] = field(default_factory=list)
    ref_blocked: int = 0
    unknown_count: int = 0
    blocking_count: int = 0


def generate_with_validation(db: Session, slots: SlotSet, pool: CandidatePool, ctx: TripContext,
                             on_stage: Callable[[str, float, int], None] | None = None,
                             mode: str | None = None, trace: Callable[[str, dict], None] | None = None) -> GenerationResult:
    mode = mode or settings.planner_mode
    start, days = trip_dates(slots)
    seq = city_sequence(slots, days)
    # 骨架按天展开并直接给出星期：模型自己推算日期→星期不可靠，是 H3（当日休息）违规的主因
    skeleton = build_day_skeleton(start, seq)
    brief = build_constraint_brief(ctx, slots)
    banned: set[tuple[str, str]] = set()
    rendered: RenderedPlan | None = None
    violations: list[Violation] = []
    rates: dict[str, RateFacts] = {}
    llm_calls: list[dict] = []
    fallback_used = False
    ref_blocked = 0
    rounds = 0
    for round_i in range(settings.max_replan_rounds):
        rounds = round_i + 1
        if on_stage:
            on_stage("planning", 0.35 + 0.15 * round_i, round_i)
        if mode == "llm":
            try:
                plan, res = plan_itinerary_llm(slots, pool, brief, skeleton)
                llm_calls.append({"round": rounds, "latency_ms": res.latency_ms, "input_tokens": res.input_tokens,
                                  "output_tokens": res.output_tokens, "cache_read_tokens": res.cache_read_tokens, "retried": res.retried})
            except AppError as error:
                if error.code not in {"LLM_FAILED", "LLM_INVALID_OUTPUT"}:
                    raise
                # 模型网络/格式故障不应让完整需求卡失去生成能力；显式降级并留 trace / assumptions。
                fallback_used = True
                mode = "heuristic"
                log.warning("planner llm unavailable, fallback to heuristic: %s", error.code)
                if trace:
                    trace("fallback", {"from": "llm", "to": "heuristic", "reason": error.code})
                plan = plan_itinerary_heuristic(slots, pool, ctx, start, seq, banned)
        else:
            plan = plan_itinerary_heuristic(slots, pool, ctx, start, seq, banned)
        if on_stage:
            on_stage("validating", 0.6 + 0.1 * round_i, round_i)
        rendered, violations, rates = render_plan(db, plan, pool, ctx)
        violations += structural_violations(rendered)
        blocking = [v for v in violations if v.blocking]
        ref_blocked += sum(1 for v in blocking if v.code == "REF")
        if trace:
            trace("validate", {"round": rounds, "blocking": len(blocking), "unknown": sum(1 for v in violations if not v.blocking),
                               "codes": sorted({v.code for v in blocking}), "ref_blocked": sum(1 for v in blocking if v.code == "REF")})
        if not blocking:
            break
        # 把违规反馈进下一轮
        date_of = {d.day_index: d.date for d in rendered.days}
        for v in blocking:
            if v.resource_id:
                banned.add((date_of.get(v.day_index, ""), v.resource_id))
        brief = build_constraint_brief(ctx, slots, previous=blocking, rendered=rendered)
    assert rendered is not None
    if fallback_used:
        rendered.assumptions = ["本次模型服务不可用，已使用确定性规则完成编排；请顾问重点复核体验节奏。", *rendered.assumptions]
    blocking = [v for v in violations if v.blocking]
    if blocking and mode == "llm":
        # 回退用尽仍有违规：确定性修补一次；仍失败的显式交人工，不静默通过
        plan, repairs = repair_blocking(plan, blocking, pool, ctx, banned)
        if repairs:
            plan.assumptions = list(plan.assumptions) + repairs
            rendered, violations, rates = render_plan(db, plan, pool, ctx)
            violations += structural_violations(rendered)
            if trace:
                trace("repair", {"replaced": len(repairs), "blocking_after": sum(1 for v in violations if v.blocking)})
    if on_stage:
        on_stage("costing", 0.9, rounds - 1)
    cost = calc_cost(rendered, ctx, rates)
    checklist = build_checklist(violations)
    for m in cost.missing_rates:
        checklist.append(ChecklistItem(code="COST", day_index=0, resource_id=m, what_to_verify=f"向供应商索取 {m} 的报价",
                                       reason="未找到价格档，成本中未计入"))
    # 产品推荐（确定性）：门票 / 预约产品 + 备选主题路线；需预约的门票进待核实清单
    interests = slots.get("interests")
    rendered.recommendations, ticket_checks = recommend_products(
        db, rendered, ctx, interests if isinstance(interests, list) else ([interests] if interests else []))
    checklist += ticket_checks
    return GenerationResult(rendered=rendered, violations=violations, checklist=checklist, cost=cost, rounds=rounds,
                            rates=rates, llm_calls=llm_calls, ref_blocked=ref_blocked,
                            unknown_count=sum(1 for v in violations if not v.blocking),
                            blocking_count=sum(1 for v in violations if v.blocking))
