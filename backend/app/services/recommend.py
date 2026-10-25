"""产品推荐（确定性规则，不经过模型）。

方案定稿后，按实际用到的景点推荐门票 / 预约产品，并按客户兴趣推荐同城主题路线作为备选。
必须按时段预约才能入场的门票（timed_entry）同时写进待核实清单（code=TKT），交给顾问在报价前处理；
特别参观 / 快速通道等可选产品只做推荐，不进清单。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.common import ChecklistItem
from app.schemas.facts import TripContext
from app.schemas.plan import Recommendation, RenderedPlan
from app.services.retrieval import interest_themes

MAX_ROUTES = 3


def recommend_products(db: Session, plan: RenderedPlan, ctx: TripContext,
                       interests: list[str] | None = None) -> tuple[list[Recommendation], list[ChecklistItem]]:
    poi_day: dict[str, int] = {}
    for d in plan.days:
        for it in d.items:
            if it.type == "poi" and it.resource_id and it.provenance:
                poi_day.setdefault(it.resource_id, d.day_index)
    cities = sorted({d.city for d in plan.days})
    recs: list[Recommendation] = []
    checklist: list[ChecklistItem] = []

    if poi_day:
        rows = db.execute(text("""SELECT ticket_id, poi_id, city, name_zh, ticket_type, reservation_required,
                                         lead_time_days, child_age_max, notes
                                  FROM ticket WHERE status='active' AND verified_status <> 'expired'
                                    AND poi_id = ANY(:pois) ORDER BY ticket_id"""),
                          {"pois": list(poi_day)}).mappings().all()
        for t in rows:
            if not _wanted(t, ctx):
                continue
            day = poi_day[t["poi_id"]]
            reason = _ticket_reason(t, ctx)
            recs.append(Recommendation(kind="ticket", ref_id=t["ticket_id"], name_zh=t["name_zh"], city=t["city"],
                                       day_index=day, reason=reason, reservation_required=t["reservation_required"],
                                       lead_time_days=t["lead_time_days"], notes=t["notes"]))
            if t["ticket_type"] == "timed_entry":
                checklist.append(ChecklistItem(code="TKT", day_index=day, resource_id=t["poi_id"],
                                               what_to_verify=f"至少提前 {t['lead_time_days']} 天预约「{t['name_zh']}」",
                                               reason="需按时段预约的门票，未预约当天可能无法入场"))
    # 通票：箱根周游券等，按城市推荐
    passes = db.execute(text("""SELECT ticket_id, city, name_zh, notes FROM ticket
                                WHERE ticket_type='pass' AND status='active' AND city = ANY(:cities)
                                ORDER BY ticket_id"""), {"cities": cities}).mappings().all()
    for p in passes:
        if p["city"] == "箱根" or ctx.pax <= 2:      # 包车为主的多人家庭，市内通票意义不大
            recs.append(Recommendation(kind="ticket", ref_id=p["ticket_id"], name_zh=p["name_zh"], city=p["city"],
                                       reason="覆盖当地主要交通与景点，适合自由活动时段", notes=p["notes"]))
            break
    # 备选主题路线：与兴趣匹配、且方案尚未覆盖其中多数景点的
    themes = interest_themes(interests, ctx.children, ctx.accessible_required)
    routes = db.execute(text("""SELECT route_id, name_zh, city, theme, poi_ids, highlights, notes FROM route
                                WHERE status='active' AND verified_status <> 'expired' AND city = ANY(:cities)
                                  AND theme = ANY(:themes) AND (NOT CAST(:acc AS boolean) OR accessible IS TRUE)
                                ORDER BY route_id"""),
                        {"cities": cities, "themes": list(themes), "acc": ctx.accessible_required}).mappings().all()
    n = 0
    for r in routes:
        if sum(p in poi_day for p in r["poi_ids"]) * 2 >= len(r["poi_ids"]):
            continue
        recs.append(Recommendation(kind="route", ref_id=r["route_id"], name_zh=r["name_zh"], city=r["city"],
                                   reason=f"与「{r['theme']}」偏好匹配，可替换自由活动时段：{r['highlights']}",
                                   notes=r["notes"]))
        n += 1
        if n >= MAX_ROUTES:
            break
    return recs, checklist


def _wanted(t, ctx: TripContext) -> bool:
    kind = t["ticket_type"]
    if kind == "general" and t["child_age_max"] is not None:
        return ctx.children > 0                      # 儿童票：有儿童才推荐
    if kind == "priority":
        return ctx.children > 0 or ctx.accessible_required
    if kind == "guided_tour":
        return False                                 # 导览套票按需人工推荐，不自动加
    return True


def _ticket_reason(t, ctx: TripContext) -> str:
    kind = t["ticket_type"]
    if kind == "timed_entry":
        return "该景点按时段预约入场，需提前锁定"
    if kind == "special_visit":
        return "季节限定的特别参观，开放日期需逐年复核"
    if kind == "priority":
        return "节假日排队时间长，带儿童或行动不便的客人建议购买"
    if t["child_age_max"] is not None:
        return f"随行 {ctx.children} 名儿童，按儿童票计"
    return "方案已安排该景点"
