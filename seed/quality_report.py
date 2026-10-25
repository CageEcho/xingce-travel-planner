"""知识库数据质量巡检（更新机制的执行入口）。

    python seed/quality_report.py            # 读 seed/data/*.json，打印巡检结果
    python seed/quality_report.py --md out.md

巡检项：各类目规模、校验状态分布、30 天内到期待复核、来源分布、关键字段空值率（空值 = 未记录，必须进待核实清单）。
「今天」与种子数据一致固定为 2026-09-07，保证结果可复现。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seed.generate import TODAY  # noqa: E402
from seed.taxonomy import SOURCE_TYPES, VERIFIED_STATUS  # noqa: E402

DATA = ROOT / "seed" / "data"
GOVERNED = {"hotel": "酒店", "restaurant": "餐厅", "poi": "景点", "vehicle": "用车", "ticket": "门票", "route": "路线"}
# 关键字段：空值即「未记录」，约束层判 UNKNOWN
NULLABLE = {"room_type": [("min_child_age", "儿童最低入住年龄")], "restaurant": [("closed_days", "休息日"),
            ("child_friendly", "儿童友好")], "poi": [("closed_days", "休息日"), ("accessible", "无障碍")],
            "vehicle": [("luggage_28", "行李容量")]}


def load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def build() -> list[str]:
    today, soon = TODAY.isoformat(), (TODAY + timedelta(days=30)).isoformat()
    lines = [f"# 知识库数据质量巡检（基准日 {today}）", "", "## 规模", "", "| 类目 | 条数 |", "| --- | --- |"]
    names = {"supplier": "供应商", "hotel": "酒店", "room_type": "房型", "restaurant": "餐厅", "poi": "景点",
             "vehicle": "用车", "ticket": "门票", "route": "路线", "history_plan": "历史方案"}
    total = 0
    for k, zh in names.items():
        n = len(load(k))
        total += n
        lines.append(f"| {zh} | {n} |")
    lines += [f"| **合计（不含价格档）** | **{total}** |", f"| 价格档 rate_plan | {len(load('rate_plan'))} |", "",
              "## 校验状态与复核", "", "| 类目 | 已校验 | 待校验 | 复核过期 | 30 天内到期 | 已校验占比 |",
              "| --- | --- | --- | --- | --- | --- |"]
    src: Counter = Counter()
    for k, zh in GOVERNED.items():
        rows = load(k)
        c = Counter(r["verified_status"] for r in rows)
        due = sum(1 for r in rows if r["verified_status"] == "verified" and today <= r["review_due"] <= soon)
        src.update(r["source_type"] for r in rows)
        lines.append(f"| {zh} | {c['verified']} | {c['pending']} | {c['expired']} | {due} | {c['verified'] / len(rows):.1%} |")
    lines += ["", "## 来源分布", "", "| 来源 | 条数 |", "| --- | --- |"]
    lines += [f"| {SOURCE_TYPES[s]} | {n} |" for s, n in src.most_common()]
    lines += ["", "## 关键字段空值率（未记录 → 约束层判「待核实」）", "", "| 类目 | 字段 | 未记录 | 占比 |", "| --- | --- | --- | --- |"]
    for k, fields in NULLABLE.items():
        rows = load(k)
        for f, zh in fields:
            n = sum(1 for r in rows if r.get(f) is None)
            lines.append(f"| {names[k]} | {zh} | {n} | {n / len(rows):.1%} |")
    rests = load("restaurant")
    empty_diet = sum(1 for r in rests if not r["dietary_support"])
    lines.append(f"| 餐厅 | 可满足饮食限制 | {empty_diet} | {empty_diet / len(rests):.1%} |")
    lines += ["", "状态口径：" + "；".join(f"{k}={v}" for k, v in VERIFIED_STATUS.items())
              + "。复核过期的资源检索时直接排除，待校验的资源可用但约束层判 H12 待核实。"]
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", help="把巡检结果写成 Markdown 文件")
    args = ap.parse_args()
    lines = build()
    if args.md:
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
