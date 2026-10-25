"""资源库扩充：在 generate.py 的 42 家核心酒店（含 12 类约束陷阱）之上，补到简历口径的规模与类目。

- 规模：酒店 300 家（东京 130 / 京都 115 / 箱根 55）、供应商 45 家、餐厅 180 家、车辆 30 台；
- 新类目：门票（ticket）、路线（route）、历史方案（history_plan）；
- 数据治理：每条资源带来源标注（source_type/source_ref）、校验状态（verified_status）、
  校验人与时间（verified_by/verified_at）、复核到期日（review_due）。

使用独立随机种子：核心数据（及依赖它的单测、评测用例里的资源 ID）完全不变。
全部为演示用模拟数据（is_synthetic=true），名称虚构；景点沿用 generate.py 的真实地标。
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from seed.generate import (
    ADVISOR_NOTES, CITY_CODE, DISTRICTS, FRESH, ROOM_TEMPLATES, STALE, TIER_BASE, TIER_CATEGORY, TODAY, rate,
)
from seed.taxonomy import REVIEW_CYCLE_DAYS, REVIEWERS

rng = random.Random(20261025)

# ─────────────────────────── 供应商（+30，按类目） ───────────────────────────
CORE_SUPPLIER_CATEGORY = {
    "SUP-001": "dmc", "SUP-002": "dmc", "SUP-003": "ryokan_alliance", "SUP-004": "ryokan_alliance",
    "SUP-005": "transport", "SUP-006": "transport", "SUP-007": "transport", "SUP-008": "dining", "SUP-009": "dining",
    "SUP-010": "dining", "SUP-011": "hotel_group", "SUP-012": "ticket", "SUP-013": "ticket", "SUP-014": "ticket",
    "SUP-015": "hotel_direct",
}
EXT_SUPPLIERS = [
    ("东京城市酒店联盟", "hotel_group"), ("京阪精品酒店集团", "hotel_group"), ("樱庭酒店管理", "hotel_group"),
    ("富士山麓度假酒店集团", "hotel_group"), ("关东奢华酒店直签组", "hotel_direct"), ("京都御所南酒店合作社", "hotel_group"),
    ("京都町家民宿联盟", "hotel_group"), ("京都老铺旅馆会", "ryokan_alliance"), ("箱根强罗旅馆组合", "ryokan_alliance"),
    ("箱根仙石原温泉会", "ryokan_alliance"), ("芦之湖畔旅馆联盟", "ryokan_alliance"), ("岚山嵯峨野旅馆会", "ryokan_alliance"),
    ("宫之下温泉旅馆组合", "ryokan_alliance"), ("东瀛匠心地接", "dmc"), ("关西礼宾服务", "dmc"), ("雅途日本 DMC", "dmc"),
    ("京都文化体验社", "dmc"), ("东京茶道体验协会", "dmc"), ("东京礼宾专车", "transport"), ("京都御用包车", "transport"),
    ("箱根山岳交通", "transport"), ("无障碍出行服务株式会社", "transport"), ("东京美食预约中心", "dining"),
    ("京料理预约会", "dining"), ("箱根温泉美食组", "dining"), ("米其林餐厅代订平台", "dining"),
    ("东京景点票务中心", "ticket"), ("京都寺社参拜预约所", "ticket"), ("箱根体验票务", "ticket"),
    ("日本美术馆联票事务所", "ticket"),
]


def extend_suppliers(core: list[dict]) -> list[dict]:
    for s in core:
        s["category"] = CORE_SUPPLIER_CATEGORY[s["supplier_id"]]
    out = []
    for i, (name, cat) in enumerate(EXT_SUPPLIERS, 16):
        contract_to = rng.choice([date(2027, 3, 31), date(2027, 6, 30), date(2027, 12, 31)])
        if i in (24, 37):                                   # 两家临近到期，提醒续签
            contract_to = date(2026, 12, 31)
        out.append({"supplier_id": f"SUP-{i:03d}", "name": name, "category": cat,
                    "contract_to": contract_to.isoformat(), "lead_time_days": rng.choice([0, 1, 3, 7]), "status": "active"})
    return out


def suppliers_of(suppliers: list[dict], *cats: str) -> list[str]:
    return [s["supplier_id"] for s in suppliers if s["category"] in cats and s["status"] == "active"]


# ─────────────────────────── 数据治理字段 ───────────────────────────
CORE_SOURCE = {"hotel": "supplier_contract", "restaurant": "advisor_visit", "poi": "official_site",
               "vehicle": "supplier_contract", "ticket": "official_site", "route": "advisor_visit"}
EXT_SOURCE_WEIGHTS = {
    "hotel": [("supplier_contract", 6), ("advisor_visit", 2), ("ota_reference", 1), ("historical_order", 1)],
    "restaurant": [("advisor_visit", 4), ("supplier_contract", 3), ("ota_reference", 2), ("historical_order", 1)],
    "vehicle": [("supplier_contract", 1)],
    "ticket": [("official_site", 6), ("supplier_contract", 3), ("ota_reference", 1)],
    "route": [("advisor_visit", 5), ("historical_order", 3), ("official_site", 2)],
}
SOURCE_REF = {
    "supplier_contract": "{sup} 2026–27 年度合同/报价单",
    "official_site": "官网信息，{d} 采集",
    "advisor_visit": "{adv} 实地踩线记录（{d}）",
    "ota_reference": "OTA 公开页面，{d} 采集（仅参考）",
    "historical_order": "历史订单回填（{d}）",
}


def _pick_weighted(pairs: list[tuple[str, int]]) -> str:
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def govern(row: dict, kind: str, core: bool, supplier: str | None = None) -> dict:
    """写入来源标注与校验状态。核心资源全部已校验；扩充资源约 85% 已校验 / 10% 待校验 / 5% 复核过期。"""
    cycle = REVIEW_CYCLE_DAYS[kind]
    src = CORE_SOURCE[kind] if core else _pick_weighted(EXT_SOURCE_WEIGHTS[kind])
    status = "verified" if core else rng.choices(["verified", "pending", "expired"], weights=[85, 10, 5])[0]
    adv = rng.choice(REVIEWERS)
    if status == "verified":
        verified_at = TODAY - timedelta(days=rng.randint(3, 25) if core else rng.randint(3, cycle - 10))
        review_due = verified_at + timedelta(days=cycle)
    elif status == "expired":
        verified_at = TODAY - timedelta(days=cycle + rng.randint(5, 90))
        review_due = verified_at + timedelta(days=cycle)                  # 已早于 TODAY
    else:
        verified_at = None
        review_due = TODAY + timedelta(days=rng.randint(3, 14))           # 待校验：校验截止日
    collected = (verified_at or TODAY - timedelta(days=rng.randint(1, 20))).isoformat()
    row.update({
        "source_type": src,
        "source_ref": SOURCE_REF[src].format(sup=supplier or row.get("supplier_id") or "供应商", d=collected, adv=adv),
        "verified_status": status,
        "verified_by": adv if verified_at else None,
        "verified_at": verified_at.isoformat() if verified_at else None,
        "review_due": review_due.isoformat(),
    })
    return row


# ─────────────────────────── 酒店 + 房型 + 房价（+258） ───────────────────────────
EXT_HOTEL_PLAN = {
    "东京": {"luxury": 25, "5star": 35, "boutique": 22, "4star": 25, "ryokan": 5},
    "京都": {"luxury": 20, "5star": 25, "ryokan": 28, "boutique": 18, "4star": 8},
    "箱根": {"ryokan": 32, "luxury": 12, "boutique": 3},   # 箱根刻意不设五星：保留「档次不足→可恢复生成」场景
}
NAME_PARTS = [("雅苑", "雅苑"), ("澄庵", "澄庵"), ("月舍", "月舎"), ("枫邸", "楓邸"), ("清流", "清流"), ("松涛", "松濤"),
              ("樱庭", "桜庭"), ("凛阁", "凛閣"), ("云栖", "雲棲"), ("水音", "水音"), ("朝雾", "朝霧"), ("白露", "白露"),
              ("星见", "星見"), ("苔香", "苔香"), ("竹里", "竹里"), ("梅香", "梅香"), ("翠峰", "翠峰"), ("鹤舞", "鶴舞"),
              ("琥珀", "琥珀"), ("紫苑", "紫苑"), ("青岚", "青嵐"), ("暮雪", "暮雪"), ("花筏", "花筏"), ("灯影", "灯影"),
              ("霞居", "霞居"), ("岩清水", "岩清水"), ("木漏日", "木漏れ日"), ("风待", "風待"), ("游心", "遊心"), ("和光", "和光"),
              ("千鸟", "千鳥"), ("若叶", "若葉"), ("初音", "初音"), ("银杏", "銀杏"), ("山茶", "山茶花"), ("瑞云", "瑞雲")]
TIER_SUFFIX = {
    "luxury": [("酒店", "ホテル"), ("公馆", "レジデンス"), (" Reserve", " リザーブ")],
    "5star": [("大饭店", "グランドホテル"), ("酒店", "ホテル"), ("格兰", "グラン")],
    "ryokan": [("旅馆", "旅館"), ("之宿", "の宿"), ("别庄", "別荘")],
    "boutique": [("旅居", "ステイ"), (" Hotel", " ホテル"), ("町家", "町家")],
    "4star": [("酒店", "ホテル"), (" Inn", " イン"), ("站前酒店", "駅前ホテル")],
}
TIER_TAGS = {
    "luxury": ["quiet", "city_view", "club_lounge", "family_room", "spa", "pool", "design", "michelin_dining",
               "connecting_rooms", "kids_club", "art", "garden", "couple", "elderly"],
    "5star": ["family_room", "connecting_rooms", "central", "shinkansen_access", "park_view", "business", "pool", "value",
              "kids_club", "city_view", "elderly"],
    "ryokan": ["onsen", "kaiseki", "private_bath", "quiet", "garden", "heritage", "river_view", "family_room",
               "tea_ceremony", "couple", "elderly"],
    "boutique": ["design", "local", "quiet", "alley", "art", "couple", "dining"],
    "4star": ["value", "central", "family_room", "shinkansen_access", "business"],
}
CITY_EXTRA_TAGS = {"箱根": ["onsen", "lake_view"], "京都": ["garden", "heritage"], "东京": ["city_view", "shopping"]}
EXTRA_NOTES = {
    "luxury": ["行政酒廊的晚间酒水时段适合长辈休息，带娃家庭可提前约儿童餐。", "高层景观房要提前锁，旺季常被团组占满。"],
    "5star": ["早餐自助品类多，挑食的孩子也能吃饱。", "大堂人多但房间隔音好，商务和家庭都能接。"],
    "ryokan": ["晚餐时间固定在 18:00 前后，行程不要排太满。", "部分房间有台阶门槛，腿脚不便的客人要确认房型。"],
    "boutique": ["前台只到 22:00，晚到的客人要提前说明。", "房间面积小，两个大箱子就转不开身。"],
    "4star": ["地铁站出口就在门口，适合自由活动多的客人。", "床偏窄，三人家庭建议订两间。"],
}


def _jitter(lat: float, lng: float, km: float) -> tuple[float, float]:
    d = km / 111.0
    return round(lat + rng.uniform(-d, d), 6), round(lng + rng.uniform(-d, d) / math.cos(math.radians(lat)), 6)


def _next_seq(ids: list[str], prefix: str) -> int:
    nums = [int(i.rsplit("-", 1)[1]) for i in ids if i.startswith(prefix) and i.rsplit("-", 1)[1].isdigit()
            and i.count("-") == prefix.count("-")]
    return max(nums, default=0) + 1


def extend_hotels(core_hotels: list[dict], suppliers: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    used_names = {h["name_zh"] for h in core_hotels}
    hotel_sups = suppliers_of(suppliers, "hotel_group", "hotel_direct", "dmc")
    ryokan_sups = suppliers_of(suppliers, "ryokan_alliance", "hotel_direct")
    hotels, rooms, rates = [], [], []
    for city, plan in EXT_HOTEL_PLAN.items():
        code = CITY_CODE[city]
        seq = _next_seq([h["hotel_id"] for h in core_hotels], f"HTL-{code}-")
        for tier, n in plan.items():
            for _ in range(n):
                d = rng.choice(DISTRICTS[city])
                for _try in range(50):
                    part, part_jp = rng.choice(NAME_PARTS)
                    suf, suf_jp = rng.choice(TIER_SUFFIX[tier])
                    name = f"{d[0]}{part}{suf}"
                    if name not in used_names:
                        break
                used_names.add(name)
                hid = f"HTL-{code}-{seq:04d}"
                seq += 1
                lat, lng = _jitter(d[2], d[3], 0.5)
                pool = TIER_TAGS[tier] + CITY_EXTRA_TAGS[city]
                tags = sorted(set(rng.sample(pool, rng.randint(2, 4))))
                if city == "箱根" and tier != "boutique" and "onsen" not in tags:
                    tags.append("onsen")
                supplier = rng.choice(ryokan_sups if tier == "ryokan" else hotel_sups)
                hotels.append(govern({
                    "hotel_id": hid, "name_zh": name, "name_local": f"{d[1]} {part_jp}{suf_jp}", "alias": [f"{d[1]} {part_jp}"],
                    "city": city, "district": d[0], "lat": lat, "lng": lng, "tier": tier, "category": TIER_CATEGORY[tier],
                    "tags": tags, "nearest_station": d[4], "walk_min": rng.choice([2, 3, 4, 5, 7, 9, 12]),
                    "advisor_notes": rng.choice(ADVISOR_NOTES[tier] + EXTRA_NOTES[tier]),
                    "supplier_id": supplier, "status": "active", "is_synthetic": True, "updated_at": FRESH,
                }, "hotel", core=False, supplier=supplier))
                r, p = _rooms_and_rates(hid, tier, supplier)
                rooms.extend(r)
                rates.extend(p)
    return hotels, rooms, rates


def _rooms_and_rates(hid: str, tier: str, supplier: str) -> tuple[list[dict], list[dict]]:
    if tier == "ryokan":
        keys = ["tatami3", "tatami4", "std2"]
    elif tier in ("luxury", "5star"):
        keys = ["std2", "dlx3", "fam4", "suite4"][: rng.choice([3, 4])]
    elif tier == "boutique":
        keys = ["std2q", "dlx3"]
    else:
        keys = ["std2", "dlx3", "fam4"]
    # 高端旅馆约四分之一限制儿童年龄（7 或 12 岁）
    ryokan_age = rng.choice([7, 12]) if tier == "ryokan" and rng.random() < 0.25 else None
    lo, hi = TIER_BASE[tier]
    base = rng.randrange(lo, hi, 500)
    stale = rng.random() < 0.08
    conf, upd = ("reference", STALE) if stale else ("contracted", FRESH)
    rooms, rates = [], []
    for i, k in enumerate(keys, 1):
        rname, bed, occ, ad, ch, feats = ROOM_TEMPLATES[k]
        rid = f"RM-{hid[4:]}-{i}"
        if ryokan_age:
            min_age = ryokan_age
        elif tier in ("5star", "luxury") and k in ("dlx3", "fam4") and rng.random() < 0.04:
            min_age = None                                   # 未记录
        else:
            min_age = 0
        extra = ({"available": True, "fee": rng.choice([6000, 8000, 11000]), "min_age": 6} if occ >= 3
                 else {"available": False})
        rooms.append({"room_id": rid, "hotel_id": hid, "name_zh": rname, "bed_config": bed, "max_occupancy": occ,
                      "max_adults": ad, "max_children": ch, "min_child_age": min_age, "extra_bed": extra,
                      "features": feats, "updated_at": FRESH})
        price = base + (i - 1) * rng.choice([9000, 14000, 22000])
        blackout = [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)] if rng.random() < 0.12 else []
        rates.append(rate(f"RP-{rid[3:]}-N", "room", rid, supplier, date(2026, 4, 1), date(2026, 9, 30), price, 0,
                          "normal", conf, upd, "per_room_night", "breakfast"))
        rates.append(rate(f"RP-{rid[3:]}-P", "room", rid, supplier, date(2026, 10, 1), date(2026, 11, 30), price,
                          rng.choice([0.12, 0.18, 0.25]), "peak", conf, upd, "per_room_night", "breakfast", blackout))
        rates.append(rate(f"RP-{rid[3:]}-W", "room", rid, supplier, date(2026, 12, 1), date(2027, 3, 31), price, 0,
                          "normal", conf, upd, "per_room_night", "breakfast"))
    return rooms, rates


# ─────────────────────────── 餐厅（+120，每城共 60 家） ───────────────────────────
CUISINE_JP = {"sushi": "鮨", "kappo": "割烹", "tempura": "天ぷら", "soba": "蕎麦", "kaiseki": "懐石", "teppanyaki": "鉄板",
              "yakiniku": "焼肉", "french": "フレンチ", "ramen": "ラーメン", "italian": "イタリアン", "tofu": "豆腐",
              "unagi": "うなぎ", "shojin": "精進", "izakaya": "居酒屋", "sukiyaki": "すき焼き", "kyo_ryori": "京料理",
              "cafe": "カフェ", "western": "洋食", "seafood": "海鮮", "yakitori": "焼鳥", "obanzai": "おばんざい",
              "shabu": "しゃぶしゃぶ", "udon": "うどん", "chinese": "中華", "kushikatsu": "串カツ"}
CUISINE_SHORT = {"sushi": "鮨", "kappo": "割烹", "tempura": "天麸罗", "soba": "荞麦", "kaiseki": "怀石", "teppanyaki": "铁板",
                 "yakiniku": "烧肉", "french": "法餐", "ramen": "拉面", "italian": "意餐", "tofu": "豆腐", "unagi": "鳗",
                 "shojin": "精进", "izakaya": "居酒屋", "sukiyaki": "寿喜锅", "kyo_ryori": "京料理", "cafe": "咖啡",
                 "western": "洋食", "seafood": "海鲜", "yakitori": "烧鸟", "obanzai": "御番菜", "shabu": "涮涮锅",
                 "udon": "乌冬", "chinese": "中华", "kushikatsu": "串炸"}
CHARS = [("和", "和"), ("翠", "翠"), ("鹤", "鶴"), ("梅", "梅"), ("樱", "桜"), ("枫", "楓"), ("岚", "嵐"), ("汐", "汐"),
         ("澄", "澄"), ("凛", "凛"), ("灯", "灯"), ("雅", "雅"), ("朴", "朴"), ("宴", "宴"), ("匠", "匠"), ("吟", "吟"),
         ("萩", "萩"), ("葵", "葵"), ("椿", "椿"), ("萤", "蛍"), ("铃", "鈴"), ("穗", "穂"), ("縁", "縁"), ("舟", "舟")]
CITY_CUISINE_WEIGHTS = {
    "东京": {"sushi": 6, "tempura": 4, "yakitori": 3, "french": 3, "italian": 3, "ramen": 3, "kappo": 3, "sukiyaki": 2,
           "shabu": 2, "yakiniku": 3, "soba": 2, "udon": 1, "chinese": 2, "kushikatsu": 1, "izakaya": 2, "unagi": 2,
           "teppanyaki": 2, "cafe": 1, "shojin": 1, "seafood": 1},
    "京都": {"kyo_ryori": 5, "obanzai": 3, "tofu": 4, "shojin": 3, "kaiseki": 3, "kappo": 3, "sushi": 2, "tempura": 2,
           "soba": 2, "udon": 2, "cafe": 3, "french": 1, "italian": 1, "yakiniku": 1, "ramen": 2, "sukiyaki": 1, "unagi": 1},
    "箱根": {"soba": 5, "tofu": 4, "kaiseki": 3, "western": 4, "unagi": 2, "cafe": 3, "tempura": 2, "italian": 2,
           "french": 1, "sukiyaki": 2, "shabu": 1, "seafood": 2, "ramen": 2, "udon": 1, "izakaya": 1},
}
# (必有, 以一定概率出现的 [(项, 概率)])
CUISINE_DIET = {
    "sushi": ([], []), "seafood": ([], []), "kappo": ([], [("no_raw", 0.5)]), "tempura": (["no_raw"], []),
    "soba": (["no_raw"], [("vegetarian", 0.5), ("vegan", 0.25)]), "kaiseki": ([], [("no_raw", 0.6)]),
    "teppanyaki": (["no_raw"], [("gluten_free", 0.4)]), "yakiniku": ([], [("no_raw", 0.6), ("no_pork", 0.6)]),
    "french": (["no_raw"], [("gluten_free", 0.5), ("vegetarian", 0.5)]), "ramen": (["no_raw"], [("no_pork", 0.3)]),
    "italian": (["no_raw", "vegetarian"], [("gluten_free", 0.5)]), "tofu": (["vegetarian", "vegan", "no_raw"], []),
    "unagi": (["no_raw"], []), "shojin": (["vegetarian", "vegan", "no_raw"], [("halal", 0.3)]),
    "izakaya": ([], [("no_raw", 0.4)]), "sukiyaki": (["no_raw"], []), "kyo_ryori": (["no_raw"], [("vegetarian", 0.5)]),
    "cafe": (["vegetarian", "no_raw"], []), "western": (["no_raw", "vegetarian"], []),
    "yakitori": (["no_raw", "no_pork"], []), "obanzai": (["no_raw", "vegetarian"], []), "shabu": (["no_raw"], [("no_pork", 0.3)]),
    "udon": (["no_raw"], [("vegetarian", 0.5)]), "chinese": (["no_raw"], [("halal", 0.15)]), "kushikatsu": (["no_raw"], []),
}
CUISINE_BAND = {"sushi": ["luxury", "high", "mid"], "kaiseki": ["luxury", "high"], "french": ["luxury", "high"],
                "kappo": ["luxury", "high"], "teppanyaki": ["luxury", "high"], "kyo_ryori": ["luxury", "high", "mid"],
                "shojin": ["high", "mid"], "sukiyaki": ["high", "mid"], "shabu": ["high", "mid"], "unagi": ["high", "mid"],
                "tempura": ["high", "mid"], "italian": ["high", "mid"], "tofu": ["high", "mid"], "yakiniku": ["high", "mid"],
                "chinese": ["high", "mid"], "obanzai": ["mid"], "soba": ["mid", "budget"], "western": ["mid"],
                "izakaya": ["mid", "budget"], "yakitori": ["mid"], "seafood": ["mid", "budget"], "ramen": ["budget"],
                "udon": ["budget", "mid"], "cafe": ["budget", "mid"], "kushikatsu": ["budget", "mid"]}
ADULT_ONLY = {"sushi", "kaiseki", "french", "kappo"}
CUISINE_TAGS = {"sushi": ["counter", "omakase", "edomae"], "kaiseki": ["private_room", "seasonal", "view"],
                "french": ["michelin", "view"], "kappo": ["counter", "seasonal"], "teppanyaki": ["wagyu", "show"],
                "yakiniku": ["wagyu", "late_night"], "ramen": ["quick", "late_night"], "izakaya": ["local", "late_night"],
                "tofu": ["garden"], "shojin": ["temple_style", "garden"], "obanzai": ["home_style", "local"],
                "cafe": ["dessert"], "soba": ["local"], "unagi": ["heritage"], "kyo_ryori": ["private_room", "machiya"],
                "western": ["heritage"], "seafood": ["market"], "udon": ["quick"], "yakitori": ["casual", "counter"],
                "sukiyaki": ["private_room", "wagyu"], "shabu": ["private_room"], "italian": ["casual"],
                "chinese": ["private_room"], "kushikatsu": ["casual"], "tempura": ["counter", "heritage"]}
CLOSED_CHOICES = [([0], 3), ([1], 3), ([2], 4), ([3], 3), ([], 4), ([1, 2], 1), ([0, 1], 1)]
BAND_PRICE = {"budget": (1500, 3000), "mid": (4500, 9000), "high": (12000, 22000), "luxury": (28000, 55000)}


def extend_restaurants(core: list[dict], suppliers: list[dict]) -> tuple[list[dict], list[dict]]:
    used = {r["name_zh"] for r in core}
    dining = suppliers_of(suppliers, "dining")
    rests, rates = [], []
    for city, weights in CITY_CUISINE_WEIGHTS.items():
        code = CITY_CODE[city]
        seq = _next_seq([r["rest_id"] for r in core], f"RST-{code}-")
        for _ in range(40):
            cuisine = rng.choices(list(weights), weights=list(weights.values()))[0]
            d = rng.choice(DISTRICTS[city])
            for _try in range(50):
                ch, ch_jp = rng.choice(CHARS)
                name = f"{d[0]} {CUISINE_SHORT[cuisine]} {ch}"
                if name not in used:
                    break
            used.add(name)
            rid = f"RST-{code}-{seq:03d}"
            seq += 1
            must, maybe = CUISINE_DIET[cuisine]
            diet = list(must) + [x for x, p in maybe if rng.random() < p]
            if rng.random() < 0.05:
                diet = []                                            # 未记录
            band = rng.choice(CUISINE_BAND[cuisine])
            kid = (False if cuisine in ADULT_ONLY and rng.random() < 0.7 else True)
            if rng.random() < 0.08:
                kid = None                                           # 未记录
            closed = None if rng.random() < 0.06 else rng.choices([c[0] for c in CLOSED_CHOICES],
                                                                  weights=[c[1] for c in CLOSED_CHOICES])[0]
            tags = sorted(set(rng.sample(CUISINE_TAGS[cuisine], min(2, len(CUISINE_TAGS[cuisine])))))
            if kid:
                tags.append("family")
            if city == "箱根" and rng.random() < 0.3:
                tags.append(rng.choice(["lake_view", "onsen_town", "river_view"]))
            sup = rng.choice(dining)
            lat, lng = _jitter(d[2], d[3], 0.4)
            rests.append(govern({
                "rest_id": rid, "name_zh": name, "name_local": f"{d[1]} {CUISINE_JP[cuisine]} {ch_jp}", "city": city,
                "district": d[0], "lat": lat, "lng": lng, "cuisine": cuisine, "price_band": band, "closed_days": closed,
                "open_from": "11:30:00" if band != "budget" else "11:00:00",
                "open_to": "22:00:00" if band != "budget" else "23:00:00",
                "dietary_support": diet, "child_friendly": kid,
                "lead_time_days": 7 if band == "luxury" else (3 if band == "high" else 0),
                "tags": tags, "status": "active", "is_synthetic": True, "updated_at": FRESH,
            }, "restaurant", core=False, supplier=sup))
            lo, hi = BAND_PRICE[band]
            rates.append(rate(f"RP-{rid}", "restaurant", rid, sup, date(2026, 4, 1), date(2027, 3, 31),
                              rng.randrange(lo, hi, 500), 0, "normal", "contracted", FRESH, "per_person"))
    return rests, rates


# ─────────────────────────── 车辆（+15） ───────────────────────────
EXT_VEHICLES = [("5座豪华轿车（Lexus LS）", 3, 2, 68000), ("7座商务车（Alphard 行政版）", 5, 3, 78000),
                ("10座 Hiace Grand Cabin", 9, 9, 88000), ("无障碍福祉车（轮椅升降，可载 1 台轮椅）", 5, 3, 82000),
                ("28座中型巴士", 28, 28, 165000)]
CITY_TRANSPORT = {"东京": "东京礼宾专车", "京都": "京都御用包车", "箱根": "箱根山岳交通"}


def extend_vehicles(core: list[dict], suppliers: list[dict]) -> tuple[list[dict], list[dict]]:
    by_name = {s["name"]: s["supplier_id"] for s in suppliers}
    acc_sup = by_name["无障碍出行服务株式会社"]
    vehicles, rates = [], []
    for city, code in CITY_CODE.items():
        seq = _next_seq([v["vehicle_id"] for v in core], f"VEH-{code}-")
        for name, seats, lug, price in EXT_VEHICLES:
            vid = f"VEH-{code}-{seq:03d}"
            seq += 1
            sup = acc_sup if "轮椅" in name else by_name[CITY_TRANSPORT[city]]
            vehicles.append(govern({"vehicle_id": vid, "name_zh": name, "city": city, "seats": seats, "luggage_28": lug,
                                    "service_hours": 10 if seats >= 9 else 8, "supplier_id": sup, "status": "active",
                                    "is_synthetic": True, "updated_at": FRESH}, "vehicle", core=False, supplier=sup))
            rates.append(rate(f"RP-{vid}", "vehicle", vid, sup, date(2026, 4, 1), date(2027, 3, 31), price, 0,
                              "normal", "contracted", FRESH, "per_car_day"))
    return vehicles, rates


# ─────────────────────────── 门票 ───────────────────────────
LEAD_TIME = {"三鹰之森吉卜力美术馆": 30, "西芳寺（苔寺）": 14, "涩谷天空 SHIBUYA SKY": 7, "嵯峨野观光小火车": 7}
PRIORITY = {"东京塔", "东京晴空塔", "涩谷天空 SHIBUYA SKY", "东京迪士尼海洋", "teamLab Planets"}
CITY_TICKET_SUP = {"东京": "东京景点票务中心", "京都": "京都寺社参拜预约所", "箱根": "箱根体验票务"}
PASSES = [  # (城市, 名称, 价格, 说明)
    ("箱根", "箱根周游券（2 日，新宿出发）", 6100, "含小田急往返、登山电车、缆车、海贼船，适合首访经典环线"),
    ("箱根", "箱根周游券（3 日，新宿出发）", 6500, "适合住两晚以上的客人"),
    ("东京", "东京地铁 72 小时通票", 1500, "自由活动多的客人适用；包车客人一般不需要"),
    ("京都", "京都地铁巴士一日券", 1100, "高峰期公交拥挤，带长辈或儿童不建议依赖"),
    ("京都", "京都五大美术馆联票", 3500, "含京都国立博物馆等，需在首次使用后 30 日内用完"),
    ("东京", "东京都美术馆巡游护照", 2500, "可在约 50 家美术馆、博物馆使用，有效期 2 个月"),
]


def gen_tickets(pois: list[dict], poi_rates: list[dict], suppliers: list[dict]) -> tuple[list[dict], list[dict]]:
    by_name = {s["name"]: s["supplier_id"] for s in suppliers}
    price_of = {r["resource_id"]: r["net_price"] for r in poi_rates if r["resource_type"] == "ticket"}
    tickets, rates, seq = [], [], {}

    def add(city: str, poi_id: str | None, name: str, ttype: str, price: int, reservation: bool, lead: int,
            child_max: int | None, refundable: bool | None, season: str, notes: str) -> None:
        code = CITY_CODE[city]
        seq[code] = seq.get(code, 0) + 1
        tid = f"TKT-{code}-{seq[code]:03d}"
        sup = by_name[CITY_TICKET_SUP[city]] if ttype != "guided_tour" else by_name["日本美术馆联票事务所"]
        tickets.append(govern({"ticket_id": tid, "poi_id": poi_id, "city": city, "name_zh": name, "ticket_type": ttype,
                               "reservation_required": reservation, "lead_time_days": lead, "child_age_max": child_max,
                               "refundable": refundable, "valid_season": season, "notes": notes, "supplier_id": sup,
                               "status": "active", "is_synthetic": True, "updated_at": FRESH},
                              "ticket", core=True, supplier=sup))
        rates.append(rate(f"RP-{tid}", "ticket", tid, sup, date(2026, 4, 1), date(2027, 3, 31), price, 0, "normal",
                          "contracted", FRESH, "per_person"))

    for p in pois:
        city, name, tags, price = p["city"], p["name_zh"], p["tags"], int(price_of.get(p["poi_id"], 0))
        if price > 0:
            reservation = "reservation" in tags
            add(city, p["poi_id"], f"{name} · 成人票", "timed_entry" if reservation else "general", price, reservation,
                LEAD_TIME.get(name, 3) if reservation else 0, None, not reservation, "全年",
                "需按入场时段预约" if reservation else "现场购票即可，旺季建议提前买")
            if "kids" in tags or p["category"] in ("museum", "experience"):
                add(city, p["poi_id"], f"{name} · 儿童票", "general", max(price // 2, 100), reservation,
                    LEAD_TIME.get(name, 3) if reservation else 0, 12, not reservation, "全年",
                    "通常小学生及以下适用，学龄前儿童多数免费，以现场规定为准")
        if name in PRIORITY:
            add(city, p["poi_id"], f"{name} · 优先入场/快速通道", "priority", max(price, 1000) + 2500, True, 3, None, False,
                "全年", "节假日排队时间长，带长辈或幼童建议购买")
        if "night_illumination" in tags or "autumn" in tags:
            add(city, p["poi_id"], f"{name} · 特别参观（夜间点灯/秋季特别公开）", "special_visit", max(price, 600) + 400,
                True, 7, None, False, "10–12 月", "仅特别公开期间开放，日期每年公布，需复核")
        if p["category"] == "museum" and rng.random() < 0.3:
            add(city, p["poi_id"], f"{name} · 中文讲解导览套票", "guided_tour", max(price, 500) + 6000, True, 5, None, True,
                "全年", "含中文讲解员 60–90 分钟，需提前 5 天预约")
    for city, name, price, notes in PASSES:
        add(city, None, name, "pass", price, False, 0, 11, True, "全年", notes)
    return tickets, rates


# ─────────────────────────── 路线（按主题聚合景点） ───────────────────────────
# (主题, 过滤条件, 适合人群标签, 时长)
ROUTE_THEMES = [
    ("亲子博物馆", lambda p: "kids" in p["tags"] and p["category"] in ("museum", "experience"), ["kids", "family"], "full_day"),
    ("艺术漫游", lambda p: "art" in p["tags"], ["couple", "elderly"], "half_day"),
    ("寺社古迹", lambda p: p["category"] == "temple" and p["intensity"] != "hard", ["elderly"], "full_day"),
    ("庭园慢游", lambda p: "garden" in p["tags"] or "quiet" in p["tags"], ["elderly", "couple"], "half_day"),
    ("雨天室内", lambda p: "rainy_day" in p["tags"], ["kids", "elderly"], "half_day"),
    ("轻松无障碍", lambda p: p["accessible"] is True and p["intensity"] == "easy", ["accessible_route", "elderly"], "full_day"),
    ("夜景夜游", lambda p: "night" in p["tags"] or "view" in p["tags"], ["couple"], "half_day"),
    ("经典首访", lambda p: "iconic" in p["tags"] or "heritage" in p["tags"], ["couple", "family"], "full_day"),
    ("在地美食与市井", lambda p: "food" in p["tags"] or "market" in p["tags"] or "retro" in p["tags"], ["couple"], "half_day"),
    ("自然与湖景", lambda p: p["category"] == "nature" or "lake" in p["tags"], ["couple", "family"], "half_day"),
]
ROUTE_TAG = {"亲子博物馆": ["kids", "family"], "艺术漫游": ["art"], "寺社古迹": ["temple", "history"],
             "庭园慢游": ["relax", "nature"], "雨天室内": ["rainy_day"], "轻松无障碍": ["accessible_route", "relax"],
             "夜景夜游": ["night"], "经典首访": ["history"], "在地美食与市井": ["food", "shopping"],
             "自然与湖景": ["nature"]}
MAX_HOP_KM = {"东京": 9.0, "京都": 7.0, "箱根": 9.0}
TIME_BUDGET_MIN = {"half_day": 240, "full_day": 480}        # 含景点间交通


def _route_minutes(seq: list[dict], city: str) -> int:
    km = sum(_km(seq[i], seq[i + 1]) for i in range(len(seq) - 1))
    return sum(p["duration_min"] for p in seq) + int(km * 1.35 / (18 if city == "东京" else 20) * 60)
WEEK_ZH = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]


def _km(a: dict, b: dict) -> float:
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def gen_routes(pois: list[dict]) -> list[dict]:
    routes, seen = [], set()
    for city, code in CITY_CODE.items():
        city_pois = [p for p in pois if p["city"] == city]
        n = 0
        for theme, pred, audience, duration in ROUTE_THEMES:
            cands = [p for p in city_pois if pred(p)]
            want = (2, 3) if duration == "half_day" else (3, 5)
            made = 0
            for seed in sorted(cands, key=lambda p: p["poi_id"]):
                if made >= 2:                                  # 每城每主题最多 2 条
                    break
                seq_ = [seed]
                while len(seq_) < want[1]:
                    rest = [p for p in cands if p not in seq_ and _km(seq_[-1], p) <= MAX_HOP_KM[city]
                            and _route_minutes(seq_ + [p], city) <= TIME_BUDGET_MIN[duration]]
                    if not rest:
                        break
                    seq_.append(min(rest, key=lambda p: _km(seq_[-1], p)))
                key = frozenset(p["poi_id"] for p in seq_)
                if len(seq_) < want[0] or key in seen or _route_minutes(seq_, city) > TIME_BUDGET_MIN[duration]:
                    continue
                seen.add(key)
                n += 1
                made += 1
                minutes = _route_minutes(seq_, city)
                closed = sorted({d for p in seq_ for d in (p["closed_days"] or [])})
                unknown = [p["name_zh"] for p in seq_ if p["closed_days"] is None]
                accessible = (True if all(p["accessible"] is True for p in seq_)
                              else (False if any(p["accessible"] is False for p in seq_) else None))
                intensity = max((p["intensity"] for p in seq_), key=["easy", "moderate", "hard"].index)
                suitable = list(audience) + (["accessible_route"] if accessible and "accessible_route" not in audience else [])
                if accessible is not True and "accessible_route" in suitable:
                    suitable.remove("accessible_route")
                notes = []
                if closed:
                    notes.append(f"{'、'.join(WEEK_ZH[d] for d in closed)}有景点休息，排期时避开")
                if unknown:
                    notes.append(f"{'、'.join(unknown)}休息日未记录，需核实")
                if accessible is False:
                    notes.append("含台阶或坡道较多的景点，行动不便的客人需调整")
                routes.append(govern({
                    "route_id": f"RTE-{code}-{n:02d}", "name_zh": f"{city}·{theme}{'半日' if duration == 'half_day' else '一日'}线（{seq_[0]['district']}起）",
                    "city": city, "theme": theme, "duration_type": duration, "poi_ids": [p["poi_id"] for p in seq_],
                    "total_minutes": minutes, "intensity": intensity, "accessible": accessible,
                    "suitable_for": suitable, "tags": sorted(set(ROUTE_TAG[theme])),
                    "highlights": "→".join(p["name_zh"] for p in seq_),
                    "notes": "；".join(notes) or "无特别提示", "status": "active", "is_synthetic": True, "updated_at": FRESH,
                }, "route", core=True))
    return routes


# ─────────────────────────── 历史方案（脱敏，模拟） ───────────────────────────
PROFILES = [  # (客群, adults, children, child_ages 区间, 长辈, 档次, 兴趣, 饮食, 无障碍)
    ("三代同堂", 4, 1, (4, 9), True, ["luxury", "5star"], ["亲子", "动物", "火车"], ["no_raw"], "长辈膝盖不好，少台阶"),
    ("亲子家庭", 2, 2, (3, 12), False, ["5star", "luxury"], ["亲子", "动漫", "主题乐园"], [], None),
    ("蜜月夫妇", 2, 0, None, False, ["ryokan", "luxury"], ["温泉", "摄影", "美食"], [], None),
    ("银发夫妇", 2, 0, None, True, ["luxury", "ryokan"], ["寺社", "庭园", "温泉"], ["no_raw"], "行动较慢，需要多休息"),
    ("闺蜜出游", 3, 0, None, False, ["boutique", "5star"], ["购物", "美食", "咖啡"], [], None),
    ("素食家庭", 2, 1, (8, 14), False, ["5star"], ["艺术", "购物"], ["vegan"], None),
    ("商务+休闲", 2, 0, None, False, ["5star", "luxury"], ["美食", "艺术"], [], None),
    ("轮椅长辈家庭", 3, 0, None, True, ["luxury"], ["温泉", "美术馆"], [], "父亲使用轮椅"),
    ("清真饮食客人", 2, 0, None, False, ["5star"], ["购物", "寺社"], ["halal"], None),
    ("大家庭", 6, 2, (5, 10), True, ["5star"], ["亲子", "经典景点"], [], None),
]
CITY_COMBOS = [(["东京"], (4, 6)), (["京都"], (3, 5)), (["东京", "京都"], (6, 9)), (["东京", "箱根"], (5, 7)),
               (["京都", "箱根"], (5, 7)), (["东京", "箱根", "京都"], (7, 10)), (["箱根"], (2, 3))]
INTEREST_THEMES = {"亲子": "亲子博物馆", "动物": "亲子博物馆", "火车": "亲子博物馆", "动漫": "亲子博物馆",
                   "寺社": "寺社古迹", "庭园": "庭园慢游", "艺术": "艺术漫游", "美术馆": "艺术漫游", "美食": "在地美食与市井",
                   "购物": "在地美食与市井", "温泉": "自然与湖景", "摄影": "夜景夜游", "经典景点": "经典首访", "咖啡": "在地美食与市井"}
DIET_ZH = {"no_raw": "忌生食", "vegan": "纯素", "vegetarian": "素食", "halal": "清真", "no_pork": "不含猪肉"}
LESSONS = {
    "知识缺失": ["旅馆儿童年龄政策未记录，报价前才确认限 12 岁以上，已补录字段并加入必核清单。",
               "餐厅是否支持忌生食未记录，临时电话确认后替换，已要求供应商补全饮食字段。",
               "车辆行李容量未记录，客人 6 个大箱子差点装不下，已补录 28 寸箱容量。"],
    "检索偏差": ["客户说「安静」，召回了商务感重的酒店，已给 quiet 标签与客群标签联合加权。",
               "亲子需求召回了只能住 2 人的精品酒店，已把房型容量提前到硬过滤。",
               "「住好一点」被直接理解为奢华档，超出预算，已改为必须追问档次。"],
    "行程冲突": ["周一安排了国立博物馆（周一闭馆），被约束校验拦截后改为周二。",
               "同一天排了箱根和京都的景点，通勤超过 5 小时，已拆成转场日。",
               "餐厅周二定休但排在周二晚餐，已改为同区域营业的餐厅。"],
}


def gen_history(hotels: list[dict], rooms: list[dict], routes: list[dict], n: int = 80) -> list[dict]:
    rooms_by_hotel: dict[str, list[dict]] = {}
    for r in rooms:
        rooms_by_hotel.setdefault(r["hotel_id"], []).append(r)
    usable = [h for h in hotels if h.get("verified_status", "verified") == "verified"]
    out = []
    for i in range(1, n + 1):
        prof = rng.choice(PROFILES)
        party, adults, children, age_rng, elderly, tiers, interests, diet, access = prof
        cities, (dmin, dmax) = rng.choice(CITY_COMBOS if children == 0 else CITY_COMBOS[:6])
        days = rng.randint(max(dmin, 2 * len(cities)), dmax)
        travel = date(2025, 3, 1) + timedelta(days=rng.randint(0, 470))
        ages = sorted(rng.randint(*age_rng) for _ in range(children)) if children else []
        hotel_ids = []
        for c in cities:
            cand = [h for h in usable if h["city"] == c and h["tier"] in tiers]
            if children:
                cand = [h for h in cand if any(r["max_children"] >= 1 and (r["min_child_age"] or 0) <= min(ages)
                                               for r in rooms_by_hotel[h["hotel_id"]])] or cand
            if elderly:
                cand = sorted(cand, key=lambda h: ("quiet" not in h["tags"], "elderly" not in h["tags"]))[:10] or cand
            if cand:
                hotel_ids.append(rng.choice(cand)["hotel_id"])
        themes = {INTEREST_THEMES.get(x) for x in interests} - {None}
        if access:
            themes.add("轻松无障碍")
        route_ids = [r["route_id"] for r in routes if r["city"] in cities and r["theme"] in themes]
        route_ids = rng.sample(route_ids, min(len(route_ids), rng.randint(1, 3))) if route_ids else []
        rework = rng.choices([0, 1, 2, 3], weights=[45, 30, 17, 8])[0]
        bad = sorted(rng.sample(list(LESSONS), k=min(rework, 2))) if rework else []
        outcome = rng.choices(["成交", "修改后成交", "未成交"],
                              weights=[60, 25, 15] if rework == 0 else [20, 55, 25])[0]
        budget_lo = rng.choice([8, 10, 12, 15, 20, 25, 30, 40])
        out.append({
            "plan_id": f"HIS-{travel:%Y%m}-{i:03d}", "travel_month": f"{travel:%Y-%m}", "party_type": party,
            "adults": adults, "children": children, "child_ages": ages, "with_elderly": elderly,
            "cities": cities, "days": days, "budget_band": f"{budget_lo}–{budget_lo + rng.choice([5, 10])} 万元（全家，不含机票）",
            "hotel_tier": tiers, "interests": interests, "dietary": diet, "accessibility": access,
            "hotel_ids": hotel_ids, "route_ids": route_ids,
            "summary": f"{party}{adults + children}人，{'、'.join(cities)} {days} 天，{travel.month} 月出行；"
                       f"{'住' + '/'.join({'luxury': '奢华', '5star': '五星', 'ryokan': '高端旅馆', 'boutique': '精品'}[t] for t in tiers)}；"
                       f"兴趣：{'、'.join(interests)}" + (f"；饮食：{'、'.join(DIET_ZH[x] for x in diet)}" if diet else "")
                       + (f"；{access}" if access else ""),
            "outcome": outcome, "rework_rounds": rework,
            "client_rating": None if outcome == "未成交" else rng.choices([3, 4, 5], weights=[1, 4, 5])[0],
            "bad_case_tags": bad, "lessons": "；".join(rng.choice(LESSONS[b]) for b in bad) or "一稿通过，无返工。",
            "source_type": "historical_order", "verified_status": "verified",
            "is_synthetic": True, "desensitized": True,
        })
    return out


# ─────────────────────────── 入口 ───────────────────────────
def extend(data: dict) -> dict:
    """在核心数据上原地补治理字段，并追加扩充资源与新类目。返回新的完整数据集。"""
    for kind, key in (("hotel", "hotel"), ("restaurant", "restaurant"), ("poi", "poi"), ("vehicle", "vehicle")):
        for row in data[key]:
            govern(row, kind, core=True)
    suppliers = data["supplier"] + extend_suppliers(data["supplier"])
    hotels, rooms, room_rates = extend_hotels(data["hotel"], suppliers)
    rests, rest_rates = extend_restaurants(data["restaurant"], suppliers)
    vehicles, veh_rates = extend_vehicles(data["vehicle"], suppliers)
    poi_rates = [r for r in data["rate_plan"] if r["resource_type"] == "ticket"]
    tickets, ticket_rates = gen_tickets(data["poi"], poi_rates, suppliers)
    routes = gen_routes(data["poi"])
    all_hotels, all_rooms = data["hotel"] + hotels, data["room_type"] + rooms
    return {
        "supplier": suppliers, "hotel": all_hotels, "room_type": all_rooms,
        "rate_plan": data["rate_plan"] + room_rates + rest_rates + veh_rates + ticket_rates,
        "vehicle": data["vehicle"] + vehicles, "restaurant": data["restaurant"] + rests, "poi": data["poi"],
        "ticket": tickets, "route": routes, "history_plan": gen_history(all_hotels, all_rooms, routes),
    }
