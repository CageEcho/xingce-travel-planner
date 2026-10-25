"""把 seed/data/*.json 载入 PostgreSQL（先清空资源表）。入库前再跑一次 assert_traps() 门禁。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.db import get_sessionmaker  # noqa: E402
from app.models import (  # noqa: E402
    HistoryPlan, Hotel, Poi, RatePlan, Restaurant, RoomType, Route, Supplier, TagDict, Ticket, Vehicle,
)
from seed.generate import assert_catalog, assert_traps  # noqa: E402
from seed.taxonomy import tag_rows  # noqa: E402

TABLES = [("supplier", Supplier), ("hotel", Hotel), ("room_type", RoomType), ("rate_plan", RatePlan),
          ("vehicle", Vehicle), ("restaurant", Restaurant), ("poi", Poi), ("ticket", Ticket), ("route", Route),
          ("history_plan", HistoryPlan)]


def load(data_dir: Path = ROOT / "seed" / "data", quiet: bool = False) -> dict[str, int]:
    data = {name: json.loads((data_dir / f"{name}.json").read_text(encoding="utf-8")) for name, _ in TABLES}
    failed = [c for c in assert_traps(data) + assert_catalog(data) if not c[1]]
    if failed:
        raise SystemExit(f"种子数据验收未通过，拒绝入库：{[c[0] for c in failed]}")
    counts: dict[str, int] = {}
    Session = get_sessionmaker()
    with Session() as db:
        db.execute(text("TRUNCATE history_plan, route, ticket, tag_dict, rate_plan, room_type, hotel, vehicle, "
                        "restaurant, poi, supplier CASCADE"))
        for name, model in TABLES:
            db.bulk_insert_mappings(model, data[name])
            counts[name] = len(data[name])
        db.bulk_insert_mappings(TagDict, tag_rows())
        counts["tag_dict"] = len(tag_rows())
        db.commit()
    if not quiet:
        for name, n in counts.items():
            print(f"  {name:<12} 入库 {n:>4} 条")
    return counts


if __name__ == "__main__":
    load()
