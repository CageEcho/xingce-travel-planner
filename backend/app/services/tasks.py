"""generation_task 生命周期 + 启动补偿。

- 每进入一个阶段更新 status / progress / heartbeat_at（落库，可恢复）
- 服务启动（lifespan）时把僵死任务标 failed / ORPHANED，避免前端永久轮询
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.core.llm import active_model
from app.core.logging import write_trace
from app.models import GenerationTask, PlanVersion, RequirementCard
from app.schemas.common import ErrorBody, PlanStatus
from app.schemas.facts import TripContext
from app.schemas.slots import SlotSet
from app.services.planner import generate_with_validation, trip_dates
from app.services.retrieval import CandidatePool, TIER_ORDER, TIER_ZH, build_pool
from datetime import timedelta

log = logging.getLogger("app.tasks")


def expand_demo_hotel_coverage(db: Session, pool: CandidatePool, cities: list[str], start, end,
                               ctx: TripContext, requested_tiers: list[str]) -> list[str]:
    """DEMO 专用：只为完全没有住宿候选的城市补充其它档次，保留全部硬约束过滤。"""
    if not settings.demo_mode:
        return []
    covered = {hotel.city for hotel in pool.hotels}
    missing = [city for city in cities if city not in covered]
    if not missing:
        return []
    expanded = build_pool(db, missing, start, end, ctx, list(TIER_ORDER))
    added_cities: list[str] = []
    for city in missing:
        additions = [hotel for hotel in expanded.hotels if hotel.city == city]
        if not additions:
            continue
        pool.hotels.extend(additions)
        pool.funnels[city] = expanded.funnels.get(city, pool.funnels.get(city, {}))
        pool.hotel_hints.pop(city, None)
        added_cities.append(city)
    if added_cities:
        log.info("demo hotel tiers expanded for cities=%s requested=%s", added_cities, requested_tiers)
    return added_cities


def candidate_recovery_details(slots: SlotSet, cities: list[str], pool: CandidatePool,
                               requested_tiers: list[str]) -> dict:
    """把候选不足转成前端可直接执行的修复动作；只建议真正影响检索的字段。"""
    covered = {hotel.city for hotel in pool.hotels}
    missing = [city for city in cities if city not in covered]
    actions: list[dict] = []
    current_start = str(slots.get("date_start") or "")
    if settings.demo_mode and current_start != settings.demo_safe_date:
        actions.append({
            "id": "use_demo_date",
            "label": f"改为 {settings.demo_safe_date} 出发",
            "description": "使用演示资源覆盖充分的日期，保留当前天数和目的地",
            "patches": [
                {"slot": "date_start", "value": settings.demo_safe_date},
                {"slot": "date_end", "value": None},
            ],
        })
    if set(requested_tiers) != set(TIER_ORDER):
        actions.append({
            "id": "expand_hotel_tiers",
            "label": "放宽酒店档次",
            "description": "增加四星、五星、奢华、高端旅馆和精品酒店",
            "patches": [{"slot": "hotel_tier", "value": list(TIER_ORDER)}],
        })
    available_cities = [city for city in cities if city in covered]
    if available_cities and len(available_cities) < len(cities):
        actions.append({
            "id": "keep_available_cities",
            "label": "只保留当前可用城市",
            "description": "移除没有合规住宿的目的地，天数保持不变",
            "patches": [{"slot": "destination_cities", "value": available_cities}],
        })
    return {
        "kind": "candidate_recovery",
        "problem_slots": ["date_start", "hotel_tier", "destination_cities"],
        "missing_cities": missing,
        "candidate_counts": {city: len({hotel.hotel_id for hotel in pool.hotels if hotel.city == city}) for city in cities},
        "actions": actions,
    }


def recovery_details_for_card(db: Session, card: RequirementCard) -> dict:
    """供历史失败任务补算恢复建议；需求卡已冻结，因此刷新后结果稳定。"""
    slots = SlotSet.model_validate(card.slots)
    ctx = TripContext.from_slots(slots)
    start, days = trip_dates(slots)
    cities = slots.get("destination_cities") or ["东京"]
    if isinstance(cities, str):
        cities = [cities]
    tiers = slots.get("hotel_tier") or ["5star", "luxury", "ryokan"]
    if isinstance(tiers, str):
        tiers = [tiers]
    pool = build_pool(db, cities, start, start + timedelta(days=days - 1), ctx, tiers)
    return candidate_recovery_details(slots, cities, pool, tiers)


def recover_orphans(db: Session, timeout_sec: int | None = None) -> int:
    """把心跳超时且未完成的任务标为 failed/ORPHANED。返回处理条数。"""
    timeout_sec = timeout_sec if timeout_sec is not None else settings.generation_timeout_sec
    res = db.execute(text("""
        UPDATE generation_task
        SET status='failed', error_code='ORPHANED',
            error_message='服务重启导致任务中断，请重新生成', error_details=NULL, finished_at=now()
        WHERE status NOT IN ('done','failed')
          AND heartbeat_at < now() - make_interval(secs => :t)
    """), {"t": timeout_sec})
    db.commit()
    n = res.rowcount or 0
    if n:
        log.warning("recovered %d orphaned generation task(s)", n)
    return n


def create_task(db: Session, card_id: str) -> tuple[str, str]:
    card = db.get(RequirementCard, card_id)
    if card is None:
        raise AppError("CARD_NOT_FOUND", "需求卡不存在")
    if card.confirmed_at is None:
        raise AppError("CARD_NOT_CONFIRMED", "需求卡尚未确认，无法生成方案")   # 人工节点①（G4）
    plan_id = f"PLN-{uuid.uuid4().hex[:10]}"
    task_id = f"TSK-{uuid.uuid4().hex[:10]}"
    db.add(GenerationTask(task_id=task_id, plan_id=plan_id, card_id=card_id, status="queued", progress=0))
    db.commit()
    return plan_id, task_id


def _beat(db: Session, task: GenerationTask, status: str, progress: float, replan_round: int | None = None) -> None:
    task.status = status
    task.progress = progress
    task.heartbeat_at = datetime.now(timezone.utc)
    if replan_round is not None:
        task.replan_round = replan_round
    db.commit()


def run_generation(task_id: str, mode: str | None = None) -> None:
    """后台执行（BackgroundTasks）。用独立 session。"""
    Session = get_sessionmaker()
    with Session() as db:
        task = db.get(GenerationTask, task_id)
        if task is None:
            return
        card = db.get(RequirementCard, task.card_id)
        try:
            slots = SlotSet.model_validate(card.slots)
            ctx = TripContext.from_slots(slots)
            _beat(db, task, "searching", 0.1)
            start, days = trip_dates(slots)
            cities = slots.get("destination_cities") or ["东京"]
            if isinstance(cities, str):
                cities = [cities]
            tiers = slots.get("hotel_tier") or ["5star", "luxury", "ryokan"]
            if isinstance(tiers, str):
                tiers = [tiers]
            interests = slots.get("interests")
            pool = build_pool(db, cities, start, start + timedelta(days=days - 1), ctx, tiers,
                              interests=interests if isinstance(interests, list) else ([interests] if interests else []))
            demo_relaxed_cities = expand_demo_hotel_coverage(
                db, pool, cities, start, start + timedelta(days=days - 1), ctx, tiers,
            )
            write_trace(db, step="search", plan_id=task.plan_id, conv_id=card.conv_id,
                        payload={"funnels": pool.funnels, "hotels": len({h.hotel_id for h in pool.hotels}),
                                 "restaurants": len(pool.restaurants), "pois": len(pool.pois), "vehicles": len(pool.vehicles),
                                 "routes": len(pool.routes), "similar_cases": len(pool.references),
                                 "requested_tiers": tiers, "demo_relaxed_cities": demo_relaxed_cities,
                                 "relaxation_hints": {c: [h.model_dump() for h in hs] for c, hs in pool.hotel_hints.items()}})
            missing_hotel_cities = [city for city in cities if not any(hotel.city == city for hotel in pool.hotels)]
            if len({h.hotel_id for h in pool.hotels}) < settings.min_candidates_to_plan or missing_hotel_cities:
                details = candidate_recovery_details(slots, cities, pool, tiers)
                missing_text = "、".join(missing_hotel_cities) if missing_hotel_cities else "当前组合"
                raise AppError(
                    "CANDIDATES_TOO_FEW",
                    f"{missing_text}缺少可用酒店。请选择建议修改后继续生成。",
                    details=details,
                )

            def on_stage(status: str, progress: float, rnd: int) -> None:
                _beat(db, task, status, progress, rnd)

            def trace(step: str, payload: dict) -> None:
                write_trace(db, step=step, plan_id=task.plan_id, conv_id=card.conv_id, payload=payload)

            result = generate_with_validation(db, slots, pool, ctx, on_stage=on_stage, mode=mode, trace=trace)
            if demo_relaxed_cities:
                requested = "、".join(TIER_ZH.get(tier, tier) for tier in tiers)
                cities_zh = "、".join(demo_relaxed_cities)
                result.rendered.assumptions.insert(
                    0,
                    f"DEMO 自动适配：{cities_zh}没有“{requested}”可用住宿，已扩大到其它档次完成演示；实际交付前需由顾问确认。",
                )
            for call in result.llm_calls:
                write_trace(db, step="plan", plan_id=task.plan_id, conv_id=card.conv_id, latency_ms=call["latency_ms"],
                            input_tokens=call["input_tokens"], output_tokens=call["output_tokens"],
                            payload={"round": call["round"], "cache_read_tokens": call["cache_read_tokens"],
                                     "retried": call["retried"], "model": active_model()})
            write_trace(db, step="cost", plan_id=task.plan_id, conv_id=card.conv_id,
                        payload={"total": str(result.cost.total), "total_cny": str(result.cost.total_cny),
                                 "missing_rates": result.cost.missing_rates})
            version = 1
            db.add(PlanVersion(plan_id=task.plan_id, version=version, card_id=card.card_id, status="draft",
                               structure=json.loads(result.rendered.model_dump_json()),
                               cost=json.loads(result.cost.model_dump_json()),
                               violations=[json.loads(v.model_dump_json()) for v in result.violations],
                               checklist=[json.loads(c.model_dump_json()) for c in result.checklist]))
            db.refresh(task)
            if task.status == "failed":          # 已被状态查询判为卡死：结果保留在 plan_version，但不再复活任务
                log.warning("task %s finished after being marked %s; leaving status", task_id, task.error_code)
                return
            task.replan_round = result.rounds - 1
            task.finished_at = datetime.now(timezone.utc)
            _beat(db, task, "done", 1.0)
            write_trace(db, step="render", plan_id=task.plan_id, conv_id=card.conv_id,
                        payload={"rounds": result.rounds, "blocking": result.blocking_count, "unknown": result.unknown_count,
                                 "ref_blocked": result.ref_blocked})
        except AppError as e:
            db.rollback()
            task = db.get(GenerationTask, task_id)
            task.status, task.error_code, task.error_message, task.error_details = "failed", e.code, e.message, e.details or None
            task.finished_at = datetime.now(timezone.utc)
            task.heartbeat_at = task.finished_at
            db.commit()
        except Exception as e:  # noqa: BLE001
            log.exception("generation failed: %s", type(e).__name__)
            db.rollback()
            task = db.get(GenerationTask, task_id)
            task.status, task.error_code, task.error_message, task.error_details = "failed", "INTERNAL", "生成过程发生内部错误，请重试", None
            task.finished_at = datetime.now(timezone.utc)
            task.heartbeat_at = task.finished_at
            db.commit()


STALLED_MESSAGE = "模型调用长时间无响应，任务已终止，请重新生成"


def mark_stalled(db: Session, task: GenerationTask, stall_sec: int | None = None) -> bool:
    """运行中的任务心跳超时 → failed/STALLED（不等服务重启才补偿）。返回是否改了状态。"""
    if task.status in ("done", "failed"):
        return False
    limit = stall_sec if stall_sec is not None else settings.task_stall_timeout_sec
    hb = task.heartbeat_at if task.heartbeat_at.tzinfo else task.heartbeat_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - hb).total_seconds() <= limit:
        return False
    task.status, task.error_code, task.error_message, task.error_details = "failed", "STALLED", STALLED_MESSAGE, None
    task.finished_at = datetime.now(timezone.utc)
    db.commit()
    log.warning("task %s stalled (heartbeat %s), marked failed", task.task_id, hb.isoformat())
    return True


def status_of(db: Session, plan_id: str) -> PlanStatus:
    task = db.execute(select(GenerationTask).where(GenerationTask.plan_id == plan_id)
                      .order_by(GenerationTask.created_at.desc())).scalars().first()
    if task is None:
        raise AppError("PLAN_NOT_FOUND", "方案不存在")
    mark_stalled(db, task)
    if task.status == "failed" and task.error_code == "CANDIDATES_TOO_FEW" and not task.error_details:
        card = db.get(RequirementCard, task.card_id)
        if card is not None:
            try:
                task.error_details = recovery_details_for_card(db, card)
                db.commit()
            except Exception as error:  # 历史数据异常时仍返回原始失败，不让状态接口再次失败
                db.rollback()
                log.warning("failed to backfill recovery details for %s: %s", task.task_id, type(error).__name__)
    version = None
    if task.status == "done":
        pv = db.execute(select(PlanVersion.version).where(PlanVersion.plan_id == plan_id)
                        .order_by(PlanVersion.version.desc())).scalars().first()
        version = pv
    return PlanStatus(plan_id=plan_id, task_id=task.task_id, status=task.status, progress=float(task.progress),
                      replan_round=task.replan_round, version=version,
                      error=ErrorBody(code=task.error_code, message=task.error_message or "", details=task.error_details) if task.error_code else None)
