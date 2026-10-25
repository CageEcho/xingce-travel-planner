"""评测跑测脚本。

    python eval/run.py --dry-run     # 跳过 LLM：需求卡直接来自用例 slots，用确定性编排器只测规则层（不花模型钱）
    python eval/run.py               # 真实模型：抽取 + LLM 编排

输出：case_id | family | slots_f1 | blocking_violations | unknown_count | pass，按用例族汇总，
以及五维评分（需求理解 / 资源召回 / 事实准确性 / 行程合理性 / 方案完整度）与 Bad Case 归因（知识缺失 / 检索偏差 / 行程冲突）。
结果写入 eval/report*.json 与 eval/report*.md。
退出码：硬约束陷阱族通过率 < 100% 或 blocking 总数 > 0 时为 1。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db import get_sessionmaker  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.schemas.facts import TripContext  # noqa: E402
from app.schemas.slots import SlotSet, SlotValue  # noqa: E402
from app.services.card import cap_followups, ensure_must_ask, merge_slots  # noqa: E402
from app.services.conflicts import detect_conflicts  # noqa: E402
from app.services.planner import generate_with_validation, trip_dates  # noqa: E402
from app.services.retrieval import build_pool  # noqa: E402
from sqlalchemy import text  # noqa: E402

CASES = ROOT / "eval" / "cases"


def to_slots(d: dict, source: str = "advisor_input") -> SlotSet:
    return SlotSet(**{k: SlotValue(value=v, source=source, confidence=1.0) for k, v in d.items() if v is not None})


# 兴趣 → 景点标签（评「资源召回」里的偏好命中）
DIMENSIONS = ["需求理解", "资源召回", "事实准确性", "行程合理性", "方案完整度"]
BADCASE_RULES = [  # (失败原因前缀, 归因)
    ("LLM_FAILED", "模型服务异常"), ("运行异常", "模型服务异常"),
    ("空值资源未标记", "知识缺失"), ("待校验资源未标记", "知识缺失"), ("预约门票未提醒", "知识缺失"),
    ("UNKNOWN 数不足", "知识缺失"), ("生成失败:CANDIDATES_TOO_FEW", "知识缺失"), ("checklist 缺", "知识缺失"),
    ("陷阱资源出现", "检索偏差"), ("偏好未命中", "检索偏差"), ("档次不符", "检索偏差"), ("推荐为空", "检索偏差"),
    ("blocking=", "行程冲突"), ("FAIL", "行程冲突"), ("无住宿", "行程冲突"), ("空白", "行程冲突"),
    ("天数不足", "行程冲突"), ("不可达景点", "行程冲突"), ("生成失败", "行程冲突"),
    ("slots_f1", "需求理解"), ("缺追问", "需求理解"), ("应为null", "需求理解"), ("委婉表达", "需求理解"),
    ("追问", "需求理解"), ("顾问槽位", "需求理解"), ("缺冲突", "需求理解"),
]


def attribute(reason: str) -> str:
    return next((cat for prefix, cat in BADCASE_RULES if prefix in reason), "其他")


def slots_f1(got: SlotSet, expect: dict) -> float | None:
    if not expect:
        return None
    hit = sum(1 for k, v in expect.items() if got.get(k) == v)
    return round(hit / len(expect), 2)


def run_case(db, case: dict, dry_run: bool) -> dict:
    exp = case.get("expect", {})
    out = {"id": case["id"], "family": case["family"], "slots_f1": None, "blocking": 0, "unknown": 0, "pass": True, "why": [],
           "key_items": None, "scores": {}}
    fails = out["why"]
    sc = out["scores"]

    # ── 抽取（仅真实模式） ──
    slots = to_slots(case.get("slots") or {})
    if not dry_run:
        from app.services.extract import extract_slots
        try:
            ext, _ = extract_slots(case["input"], slots if case.get("slots") else None)
        except AppError as e:
            fails.append(f"LLM_FAILED:{e.code}")
            out["pass"] = False
            out["badcase"] = ["模型服务异常"]
            return out
        ext, _ = cap_followups(ext)
        ext, _ = ensure_must_ask(ext, case["input"], slots if case.get("slots") else None)
        f_slots = [f.slot for f in ext.followups]
        out["slots_f1"] = slots_f1(ext.slots, exp.get("slots", {}))
        # 关键需求项：期望值 + 应留空 + 必须追问；逐项判对错
        items = [ext.slots.get(k) == v for k, v in exp.get("slots", {}).items()]
        items += [ext.slots.get(k) is None for k in exp.get("slots_null", [])]
        items += [k in f_slots or ext.slots.get(k) is not None for k in exp.get("must_have_followup_slots", [])]
        out["key_items"] = [sum(items), len(items)]
        sc["需求理解"] = round(100 * sum(items) / len(items)) if items else None
        for s in exp.get("must_have_followup_slots", []):
            if s not in f_slots and ext.slots.get(s) is None:
                fails.append(f"缺追问:{s}")
        if "max_followups" in exp and len(ext.followups) > exp["max_followups"]:
            fails.append("追问超限")
        if exp.get("followup_slot_must_have_options"):
            f = next((f for f in ext.followups if f.slot == exp["followup_slot_must_have_options"]), None)
            if f is not None and not f.options:
                fails.append("追问无选项")
        for s in exp.get("slots_null", []):
            if ext.slots.get(s) is not None:
                fails.append(f"应为null:{s}")
        if exp.get("inferred_slots_any") and not any(ext.slots.get(s) is not None or s in f_slots for s in exp["inferred_slots_any"]):
            fails.append("委婉表达未识别")
        merged = merge_slots(slots, ext.slots)
        for s in exp.get("locked_slots_unchanged", []):
            if merged.get(s) != slots.get(s):
                fails.append(f"顾问槽位被改写:{s}")
        if out["slots_f1"] is not None and out["slots_f1"] < 0.8:
            fails.append(f"slots_f1={out['slots_f1']}")
        slots = merged if case.get("slots") else merge_slots(to_slots({}), ext.slots)
    elif case["family"] == "slot_extraction":
        out["pass"] = None   # dry-run 下无法评估抽取 → 标记跳过，不冒充通过
        return out
    elif "conflicts" not in exp:
        sc["需求理解"] = None    # dry-run：需求卡直接来自用例，不评需求理解

    # ── 冲突检测 ──
    if "conflicts" in exp:
        codes = [c.code for c in detect_conflicts(slots)]
        missing = [c for c in exp["conflicts"] if c not in codes]
        for c in missing:
            fails.append(f"缺冲突:{c}")
        prev = sc.get("需求理解")
        conflict_score = 0 if missing else 100
        sc["需求理解"] = conflict_score if prev is None else round((prev + conflict_score) / 2)
    if not case.get("generate", True):
        out["pass"] = not fails
        out["badcase"] = sorted({attribute(w) for w in fails})
        return out

    # ── 生成（dry-run 用确定性编排器） ──
    ctx = TripContext.from_slots(slots)
    start, days = trip_dates(slots)
    cities = slots.get("destination_cities") or ["东京"]
    tiers = slots.get("hotel_tier") or ["5star", "luxury"]
    interests = slots.get("interests") or []
    pool = build_pool(db, cities, start, start + timedelta(days=days - 1), ctx, tiers, interests=interests)
    try:
        r = generate_with_validation(db, slots, pool, ctx, mode="heuristic" if dry_run else "llm")
    except AppError as e:
        fails.append(f"生成失败:{e.code}")
        out["pass"] = False
        out["badcase"] = sorted({attribute(w) for w in fails})
        return out
    out["blocking"], out["unknown"] = r.blocking_count, r.unknown_count
    fact_penalty = 0
    used = {it.resource_id for d in r.rendered.days for it in d.items if it.resource_id}
    for rid in exp.get("must_not_contain_resources", []):
        if rid in used:
            fails.append(f"陷阱资源出现:{rid}")
            fact_penalty += 50
    if r.blocking_count > exp.get("max_blocking_violations", 0):
        detail = "; ".join(f"{v.code} D{v.day_index} {v.resource_id or '-'}: {v.message}" for v in r.violations if v.blocking)
        fails.append(f"blocking={r.blocking_count} [{detail}]")
    for code in exp.get("forbid_code_fail", []):
        if any(v.code == code and v.blocking for v in r.violations):
            fails.append(f"{code} FAIL")
    # 空值语义：凡是用到了「字段未记录 / 非合约价」的资源，必须出现在待核实清单；模型没选到陷阱资源则不算失败
    flagged = {c.resource_id for c in r.checklist}
    null_uses: list[str] = []
    null_kinds: set[str] = set()          # 用到了哪类空值：H3 休息日未记录 / H1 最低年龄未记录 / H4 行李未记录 / H11 非合约价
    for d in r.rendered.days:
        for it in d.items:
            if it.status != "ok" or not it.resource_id:
                continue
            f = it.facts or {}
            kinds = set()
            if it.type in ("restaurant", "poi") and f.get("closed_days") is None:
                kinds.add("H3")
            if it.type == "hotel" and f.get("min_child_age") is None and ctx.children > 0:
                kinds.add("H1")
            if it.type == "vehicle" and f.get("luggage_28") is None:
                kinds.add("H4")
            if it.provenance and it.provenance.price_source and it.provenance.price_source != "contracted":
                kinds.add("H11")
            pending = bool(it.provenance and it.provenance.verified_status == "pending")
            if pending:
                kinds.add("H12")
            if kinds:
                null_uses.append(it.resource_id)
                null_kinds |= kinds
                # 酒店的价格档 / 容量约束挂在 room_id 上，待核实清单里记的是 room_id
                if it.resource_id not in flagged and not (it.room_id and it.room_id in flagged):
                    fails.append(f"{'待校验资源未标记' if pending and kinds == {'H12'} else '空值资源未标记'}:{it.resource_id}")
                    fact_penalty += 25
    if r.unknown_count < exp.get("min_unknown", 0) and null_uses:
        fails.append("UNKNOWN 数不足")
    # 只有方案确实用到了对应空值资源时才要求清单出现该代码（扩库后排序会优先合约新鲜价，未必选到陷阱资源）
    want = set(exp.get("checklist_codes_any") or [])
    if want and (want & null_kinds) and not any(c.code in want for c in r.checklist):
        fails.append("checklist 缺预期代码")
    if want and not (want & null_kinds):
        out["note"] = f"未选用 {'/'.join(sorted(want))} 类陷阱资源"
    elif not null_uses and exp.get("min_unknown"):
        out["note"] = "未选用陷阱资源"
    if exp.get("checklist_has_verify_hint") and not all(c.what_to_verify for c in r.checklist):
        fails.append("checklist 缺核实说明")
    if exp.get("min_days") and len(r.rendered.days) < exp["min_days"]:
        fails.append("天数不足")
    if exp.get("every_day_has_hotel"):
        for d in r.rendered.days[:-1]:
            if not any(it.type == "hotel" and it.status == "ok" for it in d.items):
                fails.append(f"Day{d.day_index} 无住宿")
    for d in r.rendered.days:
        if not d.items:
            fails.append(f"Day{d.day_index} 空白")
    # ── 知识库相关断言（门票预约 / 数据治理 / 偏好命中 / 无障碍 / 档次） ──
    plan_pois = [it for d in r.rendered.days for it in d.items if it.type == "poi" and it.status == "ok"]
    poi_ids = [it.resource_id for it in plan_pois]
    reserve = set(db.execute(text("SELECT DISTINCT poi_id FROM ticket WHERE ticket_type='timed_entry' AND poi_id = ANY(:p)"),
                             {"p": poi_ids}).scalars()) if poi_ids else set()
    tkt = {c.resource_id for c in r.checklist if c.code == "TKT"}
    unflagged_tkt = sorted(reserve - tkt)
    if unflagged_tkt:
        fails.append(f"预约门票未提醒:{','.join(unflagged_tkt)}")
    if exp.get("pending_resources_flagged") and not any(c.code == "H12" for c in r.checklist) and "H12" in null_kinds:
        fails.append("待校验资源未标记:H12")
    tag_hit = None
    if exp.get("interest_tags_any"):
        tags = {t for it in plan_pois for t in (it.facts or {}).get("tags", [])}
        tag_hit = bool(tags & set(exp["interest_tags_any"]))
        if not tag_hit:
            fails.append("偏好未命中:" + "/".join(exp["interest_tags_any"]))
    if exp.get("min_recommendations") and len(r.rendered.recommendations) < exp["min_recommendations"]:
        fails.append("推荐为空")
    if exp.get("no_inaccessible_poi"):
        bad = [it.resource_id for it in plan_pois if (it.facts or {}).get("accessible") is False]
        if bad:
            fails.append(f"不可达景点:{','.join(bad)}")
    if exp.get("hotel_tier_respected"):
        off = [it.resource_id for d in r.rendered.days for it in d.items
               if it.type == "hotel" and it.status == "ok" and (it.facts or {}).get("tier") not in tiers]
        if off:
            fails.append(f"档次不符:{','.join(sorted(set(off)))}")
            fact_penalty += 0
    # ── 五维评分（0–100，规则化自动打分） ──
    covered = []
    for c in cities:
        covered += [len({h.hotel_id for h in pool.hotels if h.city == c}) >= 3,
                    sum(x["city"] == c for x in pool.restaurants) >= 3, sum(x["city"] == c for x in pool.pois) >= 3]
    sc["资源召回"] = round(70 * sum(covered) / len(covered) + (30 if tag_hit in (None, True) else 0))
    ref = sum(1 for v in r.violations if v.code == "REF")
    price_leak = sum(1 for d in r.rendered.days for it in d.items if any(ch.isdigit() for ch in (it.reason_note or "")))
    sc["事实准确性"] = 0 if ref else max(0, 100 - fact_penalty - 25 * min(price_leak, 2))
    sc["行程合理性"] = max(0, 100 - 25 * r.blocking_count - 10 * len([w for w in fails if w.startswith("不可达景点")]))
    expect_days = slots.get("duration_days") or len(r.rendered.days)
    thin = sum(1 for d in r.rendered.days[:-1] if sum(it.type not in ("transfer",) for it in d.items) < 3)
    no_hotel = sum(1 for d in r.rendered.days[:-1] if not any(it.type == "hotel" and it.status == "ok" for it in d.items))
    sc["方案完整度"] = max(0, 100 - (30 if len(r.rendered.days) < expect_days else 0) - 20 * no_hotel - 10 * thin
                       - 20 * bool(unflagged_tkt) - (10 if not r.rendered.recommendations else 0)
                       - (10 if not all(c.what_to_verify for c in r.checklist) else 0))
    out["pass"] = not fails
    out["rounds"] = r.rounds - 1
    out["first_pass"] = r.rounds == 1 and r.blocking_count == 0
    out["recommendations"] = len(r.rendered.recommendations)
    out["badcase"] = sorted({attribute(w) for w in fails})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="跳过 LLM，只测规则层")
    ap.add_argument("--only", help="只跑某个 case id")
    args = ap.parse_args()
    cases = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(CASES.glob("*.yaml"))]
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    Session = get_sessionmaker()
    results = []
    with Session() as db:
        for c in cases:
            try:
                results.append(run_case(db, c, args.dry_run))
            except Exception as e:  # noqa: BLE001 — 单条用例异常记为失败，不中断整批评测
                db.rollback()
                results.append({"id": c["id"], "family": c["family"], "slots_f1": None, "blocking": 0, "unknown": 0,
                                "pass": False, "why": [f"运行异常:{type(e).__name__}"], "scores": {}, "badcase": [attribute("运行异常")]})
    print(f"{'case_id':<28}{'family':<22}{'slots_f1':>9}{'blocking':>9}{'unknown':>8}  pass")
    for r in results:
        p = "SKIP(LLM)" if r["pass"] is None else ("PASS" if r["pass"] else "FAIL " + "; ".join(r["why"]))
        print(f"{r['id']:<28}{r['family']:<22}{str(r['slots_f1'] if r['slots_f1'] is not None else '-'):>9}{r['blocking']:>9}{r['unknown']:>8}  {p}")
    fam: dict[str, list] = {}
    for r in results:
        fam.setdefault(r["family"], []).append(r)
    print("\n按陷阱族汇总：")
    for f, rs in fam.items():
        scored = [r for r in rs if r["pass"] is not None]
        ok = sum(1 for r in scored if r["pass"])
        rate = f"{ok}/{len(scored)} = {ok / len(scored):.0%}" if scored else "待验（需真实模型）"
        print(f"  {f:<22} {rate}")
    total_blocking = sum(r["blocking"] for r in results)
    print(f"\nblocking 违规总数：{total_blocking}")
    summary = summarize(results, args.dry_run)
    for k, v in summary["metrics"].items():
        print(f"  {k}：{v}")
    print("  五维均分：" + " / ".join(f"{d} {summary['dimensions'][d]}" for d in DIMENSIONS))
    print("  Bad Case 归因：" + (" / ".join(f"{k} {v}" for k, v in summary["badcase"].items()) or "无"))
    hard = [r for r in results if r["family"] == "hard_constraint_trap"]
    hard_ok = all(r["pass"] for r in hard)
    if not args.only:
        stem = "report_dry_run" if args.dry_run else "report"
        (ROOT / "eval" / f"{stem}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        (ROOT / "eval" / f"{stem}.md").write_text(render_md(results, summary, args.dry_run), encoding="utf-8")
    return 0 if hard_ok and total_blocking == 0 else 1


def summarize(results: list[dict], dry_run: bool) -> dict:
    scored = [r for r in results if r["pass"] is not None]
    gen = [r for r in results if "first_pass" in r]
    keys = [r["key_items"] for r in results if r.get("key_items")]
    metrics = {
        "用例数": f"{len(results)}（评分 {len(scored)}，dry-run 跳过 {len(results) - len(scored)}）",
        "通过率": f"{sum(r['pass'] for r in scored)}/{len(scored)} = {sum(r['pass'] for r in scored) / max(len(scored), 1):.0%}",
        "硬约束违规（blocking）总数": sum(r["blocking"] for r in results),
        "方案一次通过率（首轮即零硬约束违规）": (f"{sum(r['first_pass'] for r in gen)}/{len(gen)} = "
                                         f"{sum(r['first_pass'] for r in gen) / max(len(gen), 1):.0%}") if gen else "—",
    }
    if keys:
        hit, tot = sum(k[0] for k in keys), sum(k[1] for k in keys)
        metrics["关键需求项识别准确率"] = f"{hit}/{tot} = {hit / tot:.0%}"
    elif dry_run:
        metrics["关键需求项识别准确率"] = "—（dry-run 不调用模型）"
    dims = {}
    for d in DIMENSIONS:
        vals = [r["scores"][d] for r in results if r.get("scores", {}).get(d) is not None]
        dims[d] = round(sum(vals) / len(vals), 1) if vals else "—"
    bad: dict[str, int] = {}
    for r in results:
        for c in r.get("badcase", []):
            bad[c] = bad.get(c, 0) + 1
    return {"metrics": metrics, "dimensions": dims, "badcase": dict(sorted(bad.items(), key=lambda x: -x[1]))}


def render_md(results: list[dict], summary: dict, dry_run: bool) -> str:
    mode = "dry-run（规则层，确定性编排，不调用模型）" if dry_run else "真实模型（抽取 + LLM 编排）"
    lines = [f"# 评测报告 · {mode}", "", "由 `eval/run.py` 自动生成，数字均为本次实际跑测结果。", "", "## 核心指标", "",
             "| 指标 | 结果 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in summary["metrics"].items()]
    lines += ["", "## 五维评分（0–100，规则化自动打分）", "", "| 维度 | 均分 | 评分口径 |", "| --- | --- | --- |"]
    rubric = {
        "需求理解": "抽取用例：期望槽位 + 应留空槽位 + 必须追问项的逐项命中率；冲突用例：预期冲突是否全部检出",
        "资源召回": "每城酒店/餐厅/景点候选 ≥3 的覆盖率 ×70 + 方案景点命中客户兴趣标签 ×30",
        "事实准确性": "引用校验拦截即 0 分；陷阱资源 −50、空值或待校验资源未进清单 −25、推荐理由含数字 −25",
        "行程合理性": "最终硬约束违规每项 −25；轮椅客人用到不可达景点 −10",
        "方案完整度": "天数不足 −30、缺住宿每天 −20、内容过少每天 −10、预约门票未提醒 −20、无产品推荐 −10、清单缺核实说明 −10",
    }
    lines += [f"| {d} | {summary['dimensions'][d]} | {rubric[d]} |" for d in DIMENSIONS]
    lines += ["", "## Bad Case 归因", ""]
    if summary["badcase"]:
        lines += ["| 归因 | 用例数 |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in summary["badcase"].items()]
    else:
        lines.append("本次无失败用例。")
    lines += ["", "## 逐条结果", "", "| 用例 | 用例族 | 结果 | 重排轮次 | 待核实 | " + " | ".join(DIMENSIONS) + " | 失败原因 |",
              "| --- | --- | --- | --- | --- | " + " | ".join("---" for _ in DIMENSIONS) + " | --- |"]
    for r in results:
        res = "跳过" if r["pass"] is None else ("通过" if r["pass"] else "失败")
        dims = " | ".join(str(r.get("scores", {}).get(d, "—") if r.get("scores", {}).get(d) is not None else "—")
                          for d in DIMENSIONS)
        why = "；".join(r["why"])[:160].replace("|", "/") or "—"
        lines.append(f"| {r['id']} | {r['family']} | {res} | {r.get('rounds', '—')} | {r['unknown']} | {dims} | {why} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
