"""种子数据生成器（M0）。

设计（PRD-v3 §4.4 的落地，做了一处调整）：
- PRD 建议「用 Claude 批量生成基础合理的资源，再用 Python 注入陷阱」。本脚本改为**确定性生成**
  （手工整理的真实行政区 / 地标 / 坐标 + 固定随机种子）：可复现、离线可跑、不花模型钱，
  结果直接提交到 git。陷阱注入与 assert_traps() 门禁与 PRD 一致，这是种子数据的验收标准。
- 所有资源 is_synthetic=True；酒店 / 餐厅为虚构名称（含日文原名 + 中文译名，为 M1 别名表铺路），
  景点采用真实公共地标与真实坐标（否则地理聚类会算出荒谬结果），休馆日按公开资料近似，仍标注为模拟数据。

用法：python seed/generate.py         → 写入 seed/data/*.json，最后一行输出「约束陷阱校验：12/12 通过」
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "seed" / "data"
rng = random.Random(20260907)

# 「今天」固定，保证 T9 的 90 天判定可复现
TODAY = date(2026, 9, 7)
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(days=20)).isoformat()            # 新鲜价格
STALE = (NOW - timedelta(days=129)).isoformat()           # T9：早于 90 天

CITY_CODE = {"东京": "TYO", "京都": "KYO", "箱根": "HKN"}

# ─────────────────────────── 行政区与坐标（真实） ───────────────────────────
DISTRICTS = {
    "东京": [("丸之内", "丸の内", 35.681, 139.767, "东京站"), ("银座", "銀座", 35.671, 139.765, "银座站"),
           ("六本木", "六本木", 35.662, 139.731, "六本木站"), ("新宿", "新宿", 35.690, 139.700, "新宿站"),
           ("涩谷", "渋谷", 35.658, 139.701, "涩谷站"), ("表参道", "表参道", 35.665, 139.712, "表参道站"),
           ("汐留", "汐留", 35.663, 139.760, "汐留站"), ("日本桥", "日本橋", 35.683, 139.774, "日本桥站"),
           ("赤坂", "赤坂", 35.673, 139.737, "赤坂站"), ("浅草", "浅草", 35.712, 139.797, "浅草站"),
           ("品川", "品川", 35.628, 139.739, "品川站"), ("惠比寿", "恵比寿", 35.647, 139.710, "惠比寿站"),
           ("虎之门", "虎ノ門", 35.667, 139.750, "虎之门站"), ("目黑", "目黒", 35.634, 139.716, "目黑站"),
           ("有乐町", "有楽町", 35.675, 139.763, "有乐町站"), ("台场", "台場", 35.627, 139.775, "台场站"),
           ("神乐坂", "神楽坂", 35.703, 139.736, "饭田桥站"), ("大手町", "大手町", 35.686, 139.765, "大手町站")],
    "京都": [("祇园", "祇園", 35.003, 135.775, "祇园四条站"), ("东山", "東山", 34.998, 135.781, "清水五条站"),
           ("河原町", "河原町", 35.004, 135.769, "京都河原町站"), ("二条", "二条", 35.014, 135.748, "二条城前站"),
           ("岚山", "嵐山", 35.013, 135.677, "岚山站"), ("冈崎", "岡崎", 35.013, 135.783, "东山站"),
           ("乌丸", "烏丸", 35.005, 135.760, "乌丸站"), ("京都站前", "京都駅前", 34.986, 135.759, "京都站"),
           ("御所南", "御所南", 35.017, 135.762, "丸太町站"), ("三条", "三条", 35.009, 135.770, "三条站"),
           ("北山", "北山", 35.050, 135.760, "北山站"), ("宇治", "宇治", 34.889, 135.807, "宇治站"),
           ("伏见", "伏見", 34.937, 135.762, "伏见桃山站"), ("西阵", "西陣", 35.033, 135.745, "今出川站"),
           ("清水", "清水", 34.995, 135.785, "清水五条站"), ("鸭川", "鴨川", 35.011, 135.771, "三条站")],
    "箱根": [("强罗", "強羅", 35.248, 139.045, "强罗站"), ("仙石原", "仙石原", 35.268, 139.008, "仙石原巴士站"),
           ("宫之下", "宮ノ下", 35.244, 139.056, "宫之下站"), ("汤本", "湯本", 35.232, 139.105, "箱根汤本站"),
           ("元箱根", "元箱根", 35.204, 139.028, "元箱根港"), ("小涌谷", "小涌谷", 35.240, 139.049, "小涌谷站"),
           ("塔之泽", "塔ノ沢", 35.237, 139.095, "塔之泽站"), ("芦之湖", "芦ノ湖", 35.212, 139.020, "桃源台")],
}


def jitter(lat: float, lng: float, km: float = 0.4) -> tuple[float, float]:
    d = km / 111.0
    return round(lat + rng.uniform(-d, d), 6), round(lng + rng.uniform(-d, d) / math.cos(math.radians(lat)), 6)


# ─────────────────────────── 供应商 ───────────────────────────
def gen_suppliers() -> list[dict]:
    names = ["樱和地接社", "东瀛尊享 DMC", "京都御用旅馆联盟", "箱根温泉组合", "帝都用车服务", "关西专车株式会社",
             "富士箱根观光巴士", "和食预约平台 Yoyaku", "东京餐饮直签组", "京料理会", "环球豪华酒店集团 APAC",
             "日本国立博物馆联票中心", "岚山观光协会", "箱根周游券事务所", "老铺旅馆直签"]
    out = []
    for i, n in enumerate(names, 1):
        contract_to = date(2027, 3, 31)
        status = "active"
        if i in (9, 15):                       # 两家合约到期（配合 T8）
            contract_to = date(2026, 6, 30)
            status = "expired"
        out.append({"supplier_id": f"SUP-{i:03d}", "name": n, "contract_to": contract_to.isoformat(),
                    "lead_time_days": rng.choice([0, 1, 3, 7]), "status": status})
    return out


# ─────────────────────────── 酒店 + 房型 + 房价 ───────────────────────────
TIER_BASE = {"4star": (26000, 42000), "5star": (55000, 95000), "luxury": (110000, 210000),
             "ryokan": (68000, 160000), "boutique": (38000, 70000)}
TIER_CATEGORY = {"4star": "city_hotel", "5star": "city_hotel", "luxury": "luxury_hotel",
                 "ryokan": "ryokan", "boutique": "boutique_hotel"}

# (中文名, 日文名, 区索引, tier, tags, trap)
HOTELS: dict[str, list[tuple]] = {
    "东京": [
        ("丸之内玄庐", "丸の内 玄廬", 0, "luxury", ["quiet", "city_view", "club_lounge", "family_room"], None),
        ("银座澪 Rei", "銀座 澪", 1, "luxury", ["design", "shopping", "michelin_dining"], None),
        ("六本木天景酒店", "六本木 スカイテラス", 2, "luxury", ["city_view", "art", "family_room", "pool"], None),
        ("虎之门叙 Jo", "虎ノ門 叙", 12, "luxury", ["quiet", "spa", "club_lounge"], None),
        ("汐留云海", "汐留 雲海", 6, "luxury", ["bay_view", "family_room", "pool", "kids_club"], None),
        ("日本桥橘庵", "日本橋 橘庵", 7, "luxury", ["heritage", "quiet", "tea_ceremony"], "T1"),
        ("新宿御苑前格兰", "新宿御苑前 グラン", 3, "5star", ["park_view", "family_room", "connecting_rooms"], None),
        ("涩谷 Hikari 酒店", "渋谷 ヒカリ", 4, "5star", ["shopping", "youth", "city_view"], None),
        ("表参道青木旅居", "表参道 青木", 5, "5star", ["design", "quiet", "shopping"], "T1"),
        ("品川湾岸大酒店", "品川 ベイサイドグランド", 10, "5star", ["family_room", "kids_club", "pool", "shinkansen_access"], None),
        ("赤坂迎宾馆酒店", "赤坂 迎賓ホテル", 8, "5star", ["quiet", "garden", "club_lounge"], None),
        ("大手町松风", "大手町 松風", 17, "5star", ["business", "quiet", "family_room"], "T8"),
        ("神乐坂小路旅宿", "神楽坂 小路の宿", 16, "boutique", ["alley", "local", "quiet"], None),
        ("惠比寿白壁", "恵比寿 白壁", 11, "boutique", ["design", "dining", "quiet"], None),
        ("浅草雷门别邸", "浅草 雷門別邸", 9, "boutique", ["heritage", "family_room", "onsen"], None),
        ("目黑川季", "目黒川 季", 13, "4star", ["value", "river_view", "family_room"], None),
        ("有乐町站前之宿", "有楽町 駅前の宿", 14, "4star", ["value", "central", "family_room"], None),
        ("台场海风", "台場 海風", 15, "4star", ["bay_view", "family_room", "kids_club", "value"], None),
    ],
    "京都": [
        ("御所南 · 一花", "御所南 一花", 8, "luxury", ["quiet", "garden", "tea_ceremony", "family_room"], None),
        ("鸭川宵月", "鴨川 宵月", 15, "luxury", ["river_view", "design", "michelin_dining"], None),
        ("东山翠嵐", "東山 翠嵐", 1, "luxury", ["heritage", "quiet", "garden", "spa"], "T1"),
        ("二条城前雅叙", "二条城前 雅叙", 3, "luxury", ["family_room", "pool", "kids_club", "connecting_rooms"], None),
        ("京都站前格兰 Miyako", "京都駅前 グラン都", 7, "5star", ["shinkansen_access", "family_room", "value"], None),
        ("乌丸凛", "烏丸 凛", 6, "5star", ["design", "central", "quiet"], None),
        ("冈崎疏水苑", "岡崎 疏水苑", 5, "5star", ["park_view", "art", "family_room"], None),
        ("三条木屋町 Sora", "三条木屋町 宙", 9, "5star", ["nightlife", "river_view", "design"], "T8"),
        ("祇园白川旅馆", "祇園白川 旅館", 0, "ryokan", ["kaiseki", "quiet", "geisha_district"], "T2"),
        ("岚山渡月庵", "嵐山 渡月庵", 4, "ryokan", ["river_view", "kaiseki", "onsen", "quiet"], "T2"),
        ("西阵织屋旅馆", "西陣 織屋", 13, "ryokan", ["heritage", "quiet", "craft"], None),
        ("清水坂听雨", "清水坂 聴雨", 14, "ryokan", ["heritage", "kaiseki", "family_room"], None),
        ("宇治茶乡之宿", "宇治 茶郷の宿", 11, "ryokan", ["tea_ceremony", "quiet", "river_view"], None),
        ("河原町 Machiya 别邸", "河原町 町家別邸", 2, "boutique", ["machiya", "local", "family_room"], "T1"),
        ("北山森居", "北山 森居", 10, "boutique", ["design", "quiet", "garden"], None),
        ("伏见酒藏旅居", "伏見 酒蔵の宿", 12, "boutique", ["sake", "local", "value"], None),
    ],
    "箱根": [
        ("强罗花月庵", "強羅 花月庵", 0, "ryokan", ["onsen", "kaiseki", "private_bath", "quiet"], "T2"),
        ("仙石原雾之宿", "仙石原 霧の宿", 1, "ryokan", ["onsen", "kaiseki", "family_room", "private_bath"], None),
        ("宫之下老铺富士屋别馆", "宮ノ下 老舗別館", 2, "ryokan", ["heritage", "onsen", "kaiseki"], "T2"),
        ("汤本溪声", "湯本 渓声", 3, "ryokan", ["onsen", "river_view", "family_room", "value"], None),
        ("元箱根湖畔庵", "元箱根 湖畔庵", 4, "ryokan", ["lake_view", "onsen", "private_bath"], "T1"),
        ("小涌谷森之汤", "小涌谷 森の湯", 5, "ryokan", ["onsen", "family_room", "kids_club", "buffet"], None),
        ("芦之湖天悦", "芦ノ湖 天悦", 7, "luxury", ["lake_view", "onsen", "spa", "family_room", "private_bath"], None),
        ("塔之泽玻璃之家", "塔ノ沢 硝子の家", 6, "luxury", ["design", "onsen", "quiet", "private_bath"], None),
    ],
}

ROOM_TEMPLATES = {
    # (名称, 床型, max_occ, max_adults, max_children, features)
    "std2": ("标准双床房", {"twin": 2}, 2, 2, 0, ["city_view"]),
    "dlx3": ("豪华大床房", {"king": 1, "sofa_bed": 1}, 3, 2, 1, ["bathtub", "sofa"]),
    "fam4": ("家庭房", {"king": 1, "twin": 2}, 4, 3, 2, ["family", "connecting_available"]),
    "suite4": ("套房", {"king": 1, "sofa_bed": 2}, 4, 2, 2, ["living_room", "bathtub"]),
    "tatami3": ("和室（榻榻米）", {"tatami": 1}, 3, 3, 1, ["tatami", "garden_view"]),
    "tatami4": ("和洋室", {"tatami": 1, "twin": 2}, 4, 3, 2, ["tatami", "private_bath"]),
    "std2q": ("精品大床房", {"queen": 1}, 2, 2, 0, ["design"]),
}
ADVISOR_NOTES = {
    "luxury": ["客人要面子、要安静，这家不会出错；行政酒廊下午茶带小孩也不尴尬。", "位置好但房间偏小，住三口人一定要看清房型。",
               "服务是真的细，早餐也好，价格在这一档里不算贵。"],
    "5star": ["性价比选手，家庭房够大，适合带娃。", "商务感重一点，蜜月客人别推。", "新干线过去方便，最后一晚住这里省事。"],
    "ryokan": ["怀石晚餐是亮点，但对小孩不算友好，先问清年龄限制。", "私汤是卖点，老人腿脚不好也能泡。",
               "老板娘讲究，客人不守时会有点尴尬，提前打招呼。"],
    "boutique": ["小而美，情侣和摄影爱好者喜欢；行李多的家庭不方便。", "本地感强，早餐一般，可以外面吃。"],
    "4star": ["预算紧的时候用，位置比设施值钱。", "干净利索，但别对早餐抱期望。"],
}


def gen_hotels() -> tuple[list[dict], list[dict], list[dict]]:
    hotels, rooms, rates = [], [], []
    for city, items in HOTELS.items():
        code = CITY_CODE[city]
        seq = {None: 0, "T1": 0, "T2": 0, "T8": 0}
        null_age_budget = 4          # T11-a：≥3 个房型 min_child_age 为 NULL
        no_extra_budget = 5          # T3：≥4 个房型不允许加床
        for (name_zh, name_local, di, tier, tags, trap) in items:
            seq[trap] += 1
            hid = f"HTL-{code}-{trap}-{seq[trap]:03d}" if trap else f"HTL-{code}-{seq[trap]:04d}"
            d = DISTRICTS[city][di]
            lat, lng = jitter(d[2], d[3], 0.3)
            supplier = rng.choice(["SUP-001", "SUP-002", "SUP-003", "SUP-004", "SUP-011", "SUP-015"] if tier != "ryokan"
                                  else ["SUP-003", "SUP-004", "SUP-015"])
            hotels.append({
                "hotel_id": hid, "name_zh": name_zh, "name_local": name_local, "alias": [name_local],
                "city": city, "district": d[0], "lat": lat, "lng": lng, "tier": tier,
                "category": TIER_CATEGORY[tier], "tags": tags, "nearest_station": d[4],
                "walk_min": rng.choice([2, 3, 5, 6, 8, 10]), "advisor_notes": rng.choice(ADVISOR_NOTES[tier]),
                "supplier_id": supplier, "status": "active", "is_synthetic": True, "updated_at": FRESH,
            })
            # 房型组合
            if trap == "T1":
                keys = ["std2", "std2q", "std2"]            # 全部只能住 2 人
            elif tier == "ryokan":
                keys = ["tatami3", "tatami4", "std2"] if trap != "T2" else ["tatami3", "tatami4"]
            elif tier in ("luxury", "5star"):
                keys = ["std2", "dlx3", "fam4", "suite4"][: rng.choice([3, 4])]
            elif tier == "boutique":
                keys = ["std2q", "dlx3"]
            else:
                keys = ["std2", "dlx3", "fam4"]
            lo, hi = TIER_BASE[tier]
            base = rng.randrange(lo, hi, 500)
            for i, k in enumerate(keys, 1):
                rname, bed, occ, ad, ch, feats = ROOM_TEMPLATES[k]
                rid = f"RM-{hid[4:]}-{i}"
                # 儿童年龄：T2 旅馆 7/12；少量 NULL（未记录）；其余 0（不限）
                if trap == "T2":
                    min_age = 7 if seq["T2"] % 2 == 1 else 12
                elif null_age_budget > 0 and tier in ("5star", "luxury") and k in ("dlx3", "fam4") and rng.random() < 0.5:
                    min_age = None
                    null_age_budget -= 1
                else:
                    min_age = 0
                if no_extra_budget > 0 and k in ("std2", "std2q", "tatami3") and rng.random() < 0.6:
                    extra = {"available": False}
                    no_extra_budget -= 1
                elif occ >= 3:
                    extra = {"available": True, "fee": rng.choice([6000, 8000, 11000]), "min_age": 6}
                else:
                    extra = {"available": False}
                rooms.append({"room_id": rid, "hotel_id": hid, "name_zh": rname, "bed_config": bed,
                              "max_occupancy": occ, "max_adults": ad, "max_children": ch, "min_child_age": min_age,
                              "extra_bed": extra, "features": feats, "updated_at": FRESH})
                price = base + (i - 1) * rng.choice([9000, 14000, 22000])
                rates.extend(gen_room_rates(rid, supplier, price, trap, tier))
    return hotels, rooms, rates


_stale_budget = 10   # T9：≥8 个 reference 且超 90 天


def gen_room_rates(rid: str, supplier: str, price: int, trap: str | None, tier: str) -> list[dict]:
    global _stale_budget
    out = []
    if trap == "T8":                                   # 合约已过期：只有过期档
        out.append(rate(f"RP-{rid[3:]}-X", "room", rid, supplier, date(2025, 10, 1), date(2026, 3, 31), price, 0,
                        "normal", "contracted", FRESH, "per_room_night", "breakfast"))
        return out
    stale = False
    if _stale_budget > 0 and tier in ("boutique", "4star", "5star") and rng.random() < 0.55:
        stale = True
        _stale_budget -= 1
    conf = "reference" if stale else "contracted"
    upd = STALE if stale else FRESH
    blackout = [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)] if rng.random() < 0.15 else []
    # 平季 4–9 月
    out.append(rate(f"RP-{rid[3:]}-N", "room", rid, supplier, date(2026, 4, 1), date(2026, 9, 30), price, 0,
                    "normal", conf, upd, "per_room_night", "breakfast"))
    # 旺季 10–11 月（红叶）
    uplift = 0.18 if rng.random() < 0.7 else 0.12
    out.append(rate(f"RP-{rid[3:]}-P", "room", rid, supplier, date(2026, 10, 1), date(2026, 11, 30), price, uplift,
                    "peak", conf, upd, "per_room_night", "breakfast", blackout))
    # 冬季平季
    if rng.random() < 0.45:
        out.append(rate(f"RP-{rid[3:]}-W", "room", rid, supplier, date(2026, 12, 1), date(2027, 3, 31), price, 0,
                        "normal", conf, upd, "per_room_night", "breakfast"))
    return out


def rate(rate_id, rtype, res_id, supplier, vf, vt, price, uplift, season, conf, upd, basis, meal=None, blackout=None):
    return {"rate_id": rate_id, "resource_type": rtype, "resource_id": res_id, "supplier_id": supplier,
            "valid_from": vf.isoformat(), "valid_to": vt.isoformat(),
            "blackout_dates": [d.isoformat() for d in (blackout or [])], "net_price": price, "currency": "JPY",
            "price_basis": basis, "meal_plan": meal, "season_type": season, "season_uplift": uplift,
            "confidence": conf, "updated_at": upd}


# ─────────────────────────── 车辆 ───────────────────────────
def gen_vehicles() -> tuple[list[dict], list[dict]]:
    specs = [("5座轿车（Crown）", 3, 2, 42000), ("7座商务车（Alphard）", 6, 4, 58000),
             ("9座 Hiace", 8, 8, 72000), ("18座中巴", 18, 20, 120000)]
    vehicles, rates = [], []
    for city, code in CITY_CODE.items():
        sup = {"TYO": "SUP-005", "KYO": "SUP-006", "HKN": "SUP-007"}[code]
        for i, (name, seats, lug, price) in enumerate(specs, 1):
            vid = f"VEH-{code}-{i:03d}"
            vehicles.append({"vehicle_id": vid, "name_zh": name, "city": city, "seats": seats, "luggage_28": lug,
                             "service_hours": 8 if seats < 18 else 10, "supplier_id": sup, "status": "active",
                             "is_synthetic": True, "updated_at": FRESH})
            rates.append(rate(f"RP-{vid}", "vehicle", vid, sup, date(2026, 4, 1), date(2027, 3, 31), price, 0,
                              "normal", "contracted", FRESH, "per_car_day"))
    # T7：座位够但行李不够（7 座、只装 3 箱）— 东京、京都各一台
    for code, city in (("TYO", "东京"), ("KYO", "京都")):
        vid = f"VEH-{code}-T7-001"
        vehicles.append({"vehicle_id": vid, "name_zh": "7座商务车（Noah，短轴）", "city": city, "seats": 7, "luggage_28": 3,
                         "service_hours": 8, "supplier_id": "SUP-005" if code == "TYO" else "SUP-006",
                         "status": "active", "is_synthetic": True, "updated_at": FRESH})
        rates.append(rate(f"RP-{vid}", "vehicle", vid, "SUP-005", date(2026, 4, 1), date(2027, 3, 31), 49000, 0,
                          "normal", "contracted", FRESH, "per_car_day"))
    # 行李容量未记录（空值）— 箱根一台
    vehicles.append({"vehicle_id": "VEH-HKN-U-001", "name_zh": "7座商务车（车型待确认）", "city": "箱根", "seats": 6,
                     "luggage_28": None, "service_hours": 8, "supplier_id": "SUP-007", "status": "active",
                     "is_synthetic": True, "updated_at": FRESH})
    rates.append(rate("RP-VEH-HKN-U-001", "vehicle", "VEH-HKN-U-001", "SUP-007", date(2026, 4, 1), date(2027, 3, 31),
                      55000, 0, "normal", "reference", FRESH, "per_car_day"))
    return vehicles, rates


# ─────────────────────────── 餐厅 ───────────────────────────
# (名称, 日文, 区索引, cuisine, band, closed_days, dietary_support, child_friendly, tags)
RESTAURANTS: dict[str, list[tuple]] = {
    "东京": [
        ("银座鮨一", "銀座 鮨いち", 1, "sushi", "luxury", [0], [], False, ["counter", "omakase"]),
        ("六本木鉄板 炎", "六本木 鉄板 炎", 2, "teppanyaki", "luxury", [1], ["no_raw", "gluten_free"], True, ["wagyu", "show"]),
        ("丸之内 割烹 千", "丸の内 割烹 千", 0, "kappo", "high", [0], ["no_raw", "vegetarian"], True, ["private_room"]),
        ("汐留 天麸罗 白", "汐留 天ぷら 白", 6, "tempura", "high", [2], ["no_raw"], True, ["counter"]),
        ("赤坂 鳗 松", "赤坂 うなぎ 松", 8, "unagi", "high", [2], ["no_raw"], True, ["heritage"]),
        ("神乐坂 荞麦 庵", "神楽坂 蕎麦 庵", 16, "soba", "mid", [3], ["no_raw", "vegetarian", "vegan"], True, ["local"]),
        ("表参道 精进 蓮", "表参道 精進 蓮", 5, "shojin", "high", None, ["vegetarian", "vegan", "no_raw", "halal"], None, ["temple_style"]),
        ("日本桥 寿司 与", "日本橋 鮨 与", 7, "sushi", "high", [1], [], False, ["edomae"]),
        ("涩谷 烧肉 牛心", "渋谷 焼肉 牛心", 4, "yakiniku", "mid", [], ["no_pork"], True, ["family", "late_night", "yukhoe"]),
        ("新宿 怀石 晓", "新宿 懐石 暁", 3, "kaiseki", "luxury", [1], ["no_raw"], None, ["private_room", "view"]),
        ("惠比寿 法餐 Lumière", "恵比寿 リュミエール", 11, "french", "luxury", [1, 2], ["no_raw", "gluten_free", "vegetarian"], False, ["michelin"]),
        ("品川 拉面 潮", "品川 ラーメン 潮", 10, "ramen", "budget", None, ["no_raw", "no_pork"], True, ["quick"]),
        ("浅草 天丼 雷", "浅草 天丼 雷", 9, "tempura", "mid", [2], ["no_raw"], True, ["heritage", "family"]),
        ("目黑 居酒屋 灶", "目黒 居酒屋 竈", 13, "izakaya", "mid", [0], [], True, ["local", "late_night"]),
        ("有乐町 海鲜丼 海", "有楽町 海鮮丼 海", 14, "seafood", "budget", None, [], True, ["market"]),
        ("台场 意餐 Onda", "台場 オンダ", 15, "italian", "mid", [], ["no_raw", "vegetarian", "gluten_free"], True, ["bay_view", "family"]),
        ("大手町 寿喜锅 今", "大手町 すき焼き 今", 17, "sukiyaki", "high", [0], ["no_raw"], True, ["private_room"]),
        ("虎之门 寿司 宙", "虎ノ門 鮨 宙", 12, "sushi", "luxury", [0, 1], [], False, ["omakase"]),
        ("银座 割烹 京味", "銀座 割烹 京味", 1, "kappo", "luxury", [0], ["no_raw"], None, ["counter"]),
        ("六本木 烧鸟 鸟幸", "六本木 焼鳥 鳥幸", 2, "yakitori", "mid", [2], ["no_raw", "no_pork"], True, ["casual"]),
    ],
    "京都": [
        ("祇园 怀石 花见", "祇園 懐石 花見", 0, "kaiseki", "luxury", [2], [], False, ["machiya", "private_room"]),
        ("东山 汤豆腐 顺", "東山 湯豆腐 順", 1, "tofu", "high", [], ["vegetarian", "vegan", "no_raw", "gluten_free"], True, ["garden", "family"]),
        ("岚山 川床 渡", "嵐山 川床 渡", 4, "kyo_ryori", "luxury", [1], ["no_raw"], True, ["river_view", "seasonal"]),
        ("锦市场 寿司 锦", "錦市場 鮨 錦", 2, "sushi", "high", [3], [], False, ["market"]),
        ("乌丸 京料理 松", "烏丸 京料理 松", 6, "kyo_ryori", "high", [2], ["no_raw", "vegetarian"], True, ["private_room"]),
        ("二条 精进 天龄", "二条 精進 天齢", 3, "shojin", "high", [1], ["vegetarian", "vegan", "no_raw", "halal"], True, ["temple_style"]),
        ("河原町 鸭肉 鸭川", "河原町 鴨 鴨川", 15, "kappo", "high", [2], [], None, ["river_view", "duck_sashimi"]),
        ("京都站前 拉面 一乘", "京都駅前 ラーメン 一乗", 7, "ramen", "budget", None, ["no_raw"], True, ["quick"]),
        ("北山 法餐 Kitayama", "北山 キタヤマ", 10, "french", "luxury", [1], ["no_raw", "gluten_free", "vegetarian"], False, ["michelin"]),
        ("清水 荞麦 清", "清水 蕎麦 清", 14, "soba", "mid", [3], ["no_raw", "vegetarian"], True, ["local"]),
        ("宇治 抹茶膳 茶寮", "宇治 抹茶膳 茶寮", 11, "cafe", "mid", None, ["vegetarian", "no_raw"], True, ["dessert", "family"]),
        ("伏见 鮨 伏", "伏見 鮨 伏", 12, "sushi", "high", [0], [], False, ["counter"]),
        ("西阵 御番菜 织", "西陣 おばんざい 織", 13, "obanzai", "mid", [2], ["no_raw", "vegetarian"], True, ["home_style"]),
        ("祇园 铁板 神", "祇園 鉄板 神", 0, "teppanyaki", "luxury", [0], ["no_raw", "gluten_free"], True, ["wagyu"]),
        ("三条 烧肉 弘", "三条 焼肉 弘", 9, "yakiniku", "mid", [], ["no_raw", "no_pork"], True, ["family"]),
        ("御所南 割烹 志", "御所南 割烹 志", 8, "kappo", "luxury", [1], [], None, ["counter", "omakase"]),
        ("冈崎 天麸罗 圆", "岡崎 天ぷら 圓", 5, "tempura", "high", [2], ["no_raw"], True, ["counter"]),
        ("岚山 湯葉 汤叶", "嵐山 湯葉 ゆば", 4, "tofu", "mid", None, ["vegetarian", "vegan", "no_raw"], True, ["family", "garden"]),
        ("鸭川 意餐 Fiume", "鴨川 フィウメ", 15, "italian", "high", [1], ["no_raw", "vegetarian", "gluten_free"], True, ["river_view"]),
        ("京都站前 鮨 京", "京都駅前 鮨 京", 7, "sushi", "mid", None, [], True, ["quick"]),
    ],
    "箱根": [
        ("强罗 怀石 月", "強羅 懐石 月", 0, "kaiseki", "luxury", [2], ["no_raw"], False, ["private_room", "onsen_town"]),
        ("仙石原 荞麦 雾", "仙石原 蕎麦 霧", 1, "soba", "mid", [3], ["no_raw", "vegetarian"], True, ["local"]),
        ("宫之下 洋食 富士", "宮ノ下 洋食 富士", 2, "western", "mid", [], ["no_raw", "vegetarian"], True, ["heritage", "family"]),
        ("汤本 鮨 汤", "湯本 鮨 湯", 3, "sushi", "high", [2], [], False, ["counter"]),
        ("元箱根 湖畔 意餐 Lago", "元箱根 ラーゴ", 4, "italian", "high", [1], ["no_raw", "vegetarian", "gluten_free"], True, ["lake_view"]),
        ("小涌谷 豆腐 森", "小涌谷 豆腐 森", 5, "tofu", "mid", None, ["vegetarian", "vegan", "no_raw"], True, ["family"]),
        ("芦之湖 鳗 芦", "芦ノ湖 うなぎ 芦", 7, "unagi", "high", [2], ["no_raw"], True, ["lake_view"]),
        ("塔之泽 割烹 泽", "塔ノ沢 割烹 沢", 6, "kappo", "high", [0], [], None, ["river_view"]),
        ("强罗 烧肉 火", "強羅 焼肉 火", 0, "yakiniku", "mid", [], ["no_raw", "no_pork"], True, ["family"]),
        ("仙石原 法餐 Brume", "仙石原 ブリューム", 1, "french", "luxury", [1, 2], ["no_raw", "gluten_free"], False, ["michelin"]),
        ("汤本 天麸罗 泷", "湯本 天ぷら 滝", 3, "tempura", "mid", [2], ["no_raw"], True, ["heritage"]),
        ("元箱根 鮨 湖", "元箱根 鮨 湖", 4, "sushi", "high", [3], [], False, ["counter"]),
        ("宫之下 咖啡 老街", "宮ノ下 珈琲 旧街道", 2, "cafe", "budget", None, ["vegetarian", "no_raw"], True, ["dessert"]),
        ("小涌谷 寿喜锅 谷", "小涌谷 すき焼き 谷", 5, "sukiyaki", "high", [0], ["no_raw"], True, ["private_room"]),
        ("芦之湖 荞麦 湖畔", "芦ノ湖 蕎麦 湖畔", 7, "soba", "mid", [3], ["no_raw", "vegetarian", "vegan"], True, ["lake_view", "family"]),
        ("强罗 洋食 花", "強羅 洋食 花", 0, "western", "mid", [], ["no_raw", "vegetarian"], True, ["family"]),
        ("汤本 居酒屋 汤治", "湯本 居酒屋 湯治", 3, "izakaya", "budget", [0], [], True, ["local"]),
        ("塔之泽 怀石 溪", "塔ノ沢 懐石 渓", 6, "kaiseki", "luxury", [1], ["no_raw"], None, ["river_view"]),
        ("仙石原 拉面 原", "仙石原 ラーメン 原", 1, "ramen", "budget", None, ["no_raw"], True, ["quick"]),
        ("元箱根 鉄板 富", "元箱根 鉄板 富", 4, "teppanyaki", "luxury", [2], ["no_raw", "gluten_free"], True, ["lake_view", "wagyu"]),
    ],
}
BAND_PRICE = {"budget": (1500, 3000), "mid": (4500, 9000), "high": (12000, 22000), "luxury": (28000, 55000)}


def gen_restaurants() -> tuple[list[dict], list[dict]]:
    rests, rates = [], []
    for city, items in RESTAURANTS.items():
        code = CITY_CODE[city]
        for i, (zh, jp, di, cuisine, band, closed, diet, kid, tags) in enumerate(items, 1):
            rid = f"RST-{code}-{i:03d}"
            d = DISTRICTS[city][di]
            lat, lng = jitter(d[2], d[3], 0.35)
            rests.append({"rest_id": rid, "name_zh": zh, "name_local": jp, "city": city, "district": d[0],
                          "lat": lat, "lng": lng, "cuisine": cuisine, "price_band": band, "closed_days": closed,
                          "open_from": "11:30:00", "open_to": "22:00:00" if band != "budget" else "23:30:00",
                          "dietary_support": diet, "child_friendly": kid,
                          "lead_time_days": 7 if band == "luxury" else (3 if band == "high" else 0),
                          "tags": tags, "status": "active", "is_synthetic": True, "updated_at": FRESH})
            lo, hi = BAND_PRICE[band]
            sup = "SUP-008" if band in ("luxury", "high") else "SUP-009"
            rates.append(rate(f"RP-{rid}", "restaurant", rid, sup, date(2026, 4, 1), date(2027, 3, 31),
                              rng.randrange(lo, hi, 500), 0, "normal", "contracted" if sup == "SUP-008" else "reference",
                              FRESH, "per_person"))
    return rests, rates


# ─────────────────────────── 景点（真实地标 + 真实坐标） ───────────────────────────
# (中文, 日文, lat, lng, district, category, closed_days, duration, intensity, accessible, tags, ticket_price)
POIS: dict[str, list[tuple]] = {
    "东京": [
        ("东京国立博物馆", "東京国立博物館", 35.7188, 139.7765, "上野", "museum", [1], 150, "easy", True, ["art", "history", "rainy_day"], 1000),
        ("根津美术馆", "根津美術館", 35.6622, 139.7176, "表参道", "museum", [1], 90, "easy", True, ["art", "garden", "quiet"], 1600),
        ("国立西洋美术馆", "国立西洋美術館", 35.7155, 139.7757, "上野", "museum", [1], 120, "easy", True, ["art", "rainy_day"], 500),
        ("上野动物园", "上野動物園", 35.7167, 139.7714, "上野", "experience", [1], 150, "moderate", True, ["kids", "animals"], 600),
        ("新宿御苑", "新宿御苑", 35.6852, 139.7100, "新宿", "nature", [1], 90, "easy", True, ["garden", "picnic", "kids"], 500),
        ("森美术馆", "森美術館", 35.6605, 139.7292, "六本木", "museum", [2], 90, "easy", True, ["art", "city_view", "night"], 2000),
        ("三得利美术馆", "サントリー美術館", 35.6664, 139.7310, "六本木", "museum", [2], 80, "easy", True, ["art", "craft"], 1500),
        ("三鹰之森吉卜力美术馆", "三鷹の森ジブリ美術館", 35.6962, 139.5704, "三鹰", "museum", [2], 120, "easy", False, ["kids", "anime", "reservation"], 1000),
        ("teamLab Planets", "チームラボプラネッツ", 35.6490, 139.7900, "丰洲", "experience", [], 120, "moderate", False, ["kids", "immersive", "rainy_day"], 3800),
        ("明治神宫", "明治神宮", 35.6764, 139.6993, "原宿", "temple", [], 75, "easy", True, ["shrine", "forest", "morning"], 0),
        ("浅草寺", "浅草寺", 35.7148, 139.7967, "浅草", "temple", [], 75, "easy", True, ["heritage", "shopping_street", "crowded"], 0),
        ("皇居东御苑", "皇居東御苑", 35.6858, 139.7573, "丸之内", "nature", [1, 5], 80, "easy", True, ["garden", "history", "quiet"], 0),
        ("东京塔", "東京タワー", 35.6586, 139.7454, "芝公园", "experience", [], 70, "easy", True, ["view", "kids", "night"], 1500),
        ("涩谷天空 SHIBUYA SKY", "渋谷スカイ", 35.6580, 139.7016, "涩谷", "experience", [], 70, "easy", True, ["view", "night", "reservation"], 2500),
        ("筑地场外市场", "築地場外市場", 35.6654, 139.7707, "筑地", "shopping", None, 90, "moderate", None, ["food", "morning", "crowded"], 0),
        ("银座步行街", "銀座", 35.6717, 139.7650, "银座", "shopping", None, 120, "easy", True, ["shopping", "luxury"], 0),
        ("江户东京建筑园", "江戸東京たてもの園", 35.7168, 139.5127, "小金井", "museum", [1], 120, "moderate", True, ["history", "outdoor", "kids"], 400),
        ("滨离宫恩赐庭园", "浜離宮恩賜庭園", 35.6597, 139.7634, "汐留", "nature", [], 70, "easy", True, ["garden", "tea_house", "quiet"], 300),
        ("东京迪士尼海洋", "東京ディズニーシー", 35.6267, 139.8851, "舞滨", "experience", [], 540, "hard", True, ["kids", "theme_park", "full_day"], 9400),
        ("国立科学博物馆", "国立科学博物館", 35.7163, 139.7764, "上野", "museum", [1], 120, "easy", True, ["kids", "science", "rainy_day"], 630),
        ("东京国立近代美术馆", "東京国立近代美術館", 35.6906, 139.7546, "竹桥", "museum", [1], 90, "easy", True, ["art", "quiet"], 500),
        ("东京晴空塔", "東京スカイツリー", 35.7101, 139.8107, "押上", "experience", [], 90, "easy", True, ["view", "kids", "shopping"], 3100),
        ("柴又帝释天参道", "柴又帝釈天", 35.7594, 139.8760, "葛饰", "temple", None, 90, "easy", None, ["retro", "local", "food"], 0),
        ("代代木公园", "代々木公園", 35.6717, 139.6949, "原宿", "nature", [], 60, "easy", True, ["picnic", "kids", "morning"], 0),
        ("目黑川", "目黒川", 35.6400, 139.7000, "中目黑", "nature", None, 60, "easy", True, ["walk", "cafe", "seasonal"], 0),
        ("相扑博物馆·两国国技馆", "相撲博物館", 35.6970, 139.7930, "两国", "museum", [0, 6], 60, "easy", True, ["culture", "sumo"], 0),
        ("和纸体验工房（浅草）", "和紙体験 浅草", 35.7110, 139.7950, "浅草", "experience", [2], 90, "easy", False, ["craft", "kids", "hands_on"], 4500),
        ("日本桥 茶道体验", "日本橋 茶道体験", 35.6830, 139.7745, "日本桥", "experience", [1], 75, "easy", True, ["tea_ceremony", "culture"], 6000),
        ("等等力溪谷", "等々力渓谷", 35.6040, 139.6470, "世田谷", "nature", [], 60, "moderate", False, ["nature", "walk", "quiet"], 0),
        ("Yanaka 谷中银座", "谷中銀座", 35.7280, 139.7660, "谷中", "shopping", None, 75, "easy", None, ["retro", "food", "local"], 0),
    ],
    "京都": [
        ("京都国立博物馆", "京都国立博物館", 34.9900, 135.7730, "东山", "museum", [1], 120, "easy", True, ["art", "history", "rainy_day"], 700),
        ("京都御所", "京都御所", 35.0254, 135.7621, "御所", "museum", [1], 80, "easy", True, ["history", "garden"], 0),
        ("京都国际漫画博物馆", "京都国際マンガミュージアム", 35.0117, 135.7590, "乌丸", "museum", [3], 90, "easy", True, ["kids", "anime", "rainy_day"], 1200),
        ("京都铁道博物馆", "京都鉄道博物館", 34.9871, 135.7420, "梅小路", "museum", [3], 120, "easy", True, ["kids", "trains", "rainy_day"], 1500),
        ("伏见稻荷大社", "伏見稲荷大社", 34.9671, 135.7727, "伏见", "temple", [], 120, "hard", False, ["shrine", "torii", "hike", "crowded"], 0),
        ("清水寺", "清水寺", 34.9949, 135.7850, "东山", "temple", [], 90, "moderate", False, ["heritage", "view", "crowded"], 500),
        ("金阁寺", "金閣寺", 35.0394, 135.7292, "北区", "temple", [], 60, "easy", True, ["heritage", "iconic"], 500),
        ("岚山竹林小径", "嵐山 竹林の小径", 35.0170, 135.6716, "岚山", "nature", [], 60, "easy", True, ["nature", "iconic", "morning"], 0),
        ("天龙寺", "天龍寺", 35.0158, 135.6737, "岚山", "temple", [], 75, "easy", True, ["garden", "heritage"], 800),
        ("二条城", "二条城", 35.0142, 135.7481, "二条", "museum", [], 90, "easy", True, ["heritage", "history"], 1300),
        ("锦市场", "錦市場", 35.0050, 135.7650, "河原町", "shopping", None, 75, "easy", None, ["food", "market", "crowded"], 0),
        ("祇园花见小路", "祇園 花見小路", 35.0035, 135.7752, "祇园", "shopping", None, 60, "easy", True, ["geisha_district", "night", "walk"], 0),
        ("哲学之道", "哲学の道", 35.0230, 135.7950, "左京", "nature", [], 60, "easy", True, ["walk", "quiet", "seasonal"], 0),
        ("银阁寺", "銀閣寺", 35.0270, 135.7982, "左京", "temple", [], 60, "moderate", False, ["garden", "heritage"], 500),
        ("南禅寺", "南禅寺", 35.0113, 135.7935, "冈崎", "temple", [], 60, "easy", True, ["temple", "aqueduct", "quiet"], 600),
        ("三十三间堂", "三十三間堂", 34.9878, 135.7719, "东山", "temple", [], 45, "easy", True, ["heritage", "statues"], 600),
        ("龙安寺", "龍安寺", 35.0345, 135.7183, "右京", "temple", [], 60, "easy", True, ["zen_garden", "quiet"], 600),
        ("平安神宫", "平安神宮", 35.0161, 135.7823, "冈崎", "temple", [], 60, "easy", True, ["shrine", "garden"], 600),
        ("东福寺", "東福寺", 34.9765, 135.7740, "东山", "temple", [], 60, "moderate", False, ["autumn", "garden"], 600),
        ("醍醐寺", "醍醐寺", 34.9510, 135.8194, "伏见", "temple", [], 90, "moderate", False, ["heritage", "garden"], 1000),
        ("宇治平等院", "平等院", 34.8892, 135.8076, "宇治", "temple", [], 60, "easy", True, ["heritage", "iconic"], 700),
        ("嵯峨野观光小火车", "嵯峨野トロッコ列車", 35.0180, 135.6800, "岚山", "experience", [3], 60, "easy", True, ["kids", "scenic", "reservation"], 880),
        ("保津川游船", "保津川下り", 35.0140, 135.5890, "龟冈", "experience", None, 120, "moderate", False, ["river", "kids", "seasonal"], 4500),
        ("京都水族馆", "京都水族館", 34.9880, 135.7455, "梅小路", "experience", [], 100, "easy", True, ["kids", "rainy_day"], 2400),
        ("建仁寺", "建仁寺", 35.0006, 135.7737, "祇园", "temple", [], 45, "easy", True, ["zen", "art", "quiet"], 800),
        ("高台寺", "高台寺", 34.9995, 135.7810, "东山", "temple", [], 60, "moderate", False, ["night_illumination", "garden"], 600),
        ("八坂神社", "八坂神社", 35.0037, 135.7786, "祇园", "temple", [], 40, "easy", True, ["shrine", "night"], 0),
        ("东寺", "東寺", 34.9806, 135.7476, "南区", "temple", [], 60, "easy", True, ["pagoda", "heritage", "market"], 800),
        ("西芳寺（苔寺）", "西芳寺", 34.9922, 135.6835, "西京", "temple", None, 90, "moderate", False, ["moss_garden", "reservation", "quiet"], 4000),
        ("和菓子制作体验（乌丸）", "和菓子作り体験", 35.0060, 135.7600, "乌丸", "experience", [2], 75, "easy", True, ["kids", "hands_on", "sweets"], 3300),
    ],
    "箱根": [
        ("箱根雕刻森林美术馆", "彫刻の森美術館", 35.2453, 139.0508, "二之平", "museum", [], 120, "moderate", True, ["art", "kids", "outdoor"], 2000),
        ("POLA 美术馆", "ポーラ美術館", 35.2596, 139.0207, "仙石原", "museum", [], 100, "easy", True, ["art", "forest", "rainy_day"], 2200),
        ("箱根美术馆", "箱根美術館", 35.2492, 139.0473, "强罗", "museum", [4], 60, "moderate", False, ["moss_garden", "ceramics", "autumn"], 1300),
        ("冈田美术馆", "岡田美術館", 35.2430, 139.0480, "小涌谷", "museum", [], 120, "easy", True, ["art", "footbath", "rainy_day"], 2800),
        ("箱根拉利克美术馆", "箱根ラリック美術館", 35.2620, 139.0130, "仙石原", "museum", [], 80, "easy", True, ["art", "glass", "cafe"], 1500),
        ("成川美术馆", "成川美術館", 35.2060, 139.0280, "元箱根", "museum", [], 70, "easy", True, ["art", "lake_view"], 1500),
        ("箱根神社", "箱根神社", 35.2049, 139.0254, "元箱根", "temple", [], 60, "moderate", False, ["shrine", "lake", "iconic"], 0),
        ("芦之湖海贼观光船", "箱根海賊船", 35.2100, 139.0210, "桃源台", "experience", [], 40, "easy", True, ["lake", "kids", "scenic"], 1200),
        ("箱根空中缆车", "箱根ロープウェイ", 35.2440, 139.0195, "大涌谷", "experience", [], 40, "easy", True, ["view", "kids", "transport"], 1500),
        ("大涌谷", "大涌谷", 35.2440, 139.0190, "大涌谷", "nature", [], 60, "moderate", False, ["volcanic", "black_egg", "view"], 0),
        ("箱根旧街道杉木林", "箱根旧街道 杉並木", 35.1980, 139.0300, "元箱根", "nature", None, 45, "moderate", False, ["history", "walk", "quiet"], 0),
        ("箱根关所", "箱根関所", 35.1932, 139.0262, "箱根町", "museum", [], 50, "easy", True, ["history", "lake"], 500),
        ("箱根强罗公园", "箱根強羅公園", 35.2470, 139.0450, "强罗", "nature", [], 60, "easy", True, ["garden", "kids", "craft"], 650),
        ("箱根玻璃之森美术馆", "箱根ガラスの森美術館", 35.2640, 139.0110, "仙石原", "museum", None, 80, "easy", True, ["glass", "garden", "cafe"], 1800),
        ("箱根汤寮（日归温泉）", "箱根湯寮", 35.2400, 139.0900, "塔之泽", "experience", [], 120, "easy", None, ["onsen", "day_spa", "relax"], 2000),
    ],
}


def gen_pois() -> tuple[list[dict], list[dict]]:
    pois, rates = [], []
    for city, items in POIS.items():
        code = CITY_CODE[city]
        for i, (zh, jp, lat, lng, dist, cat, closed, dur, inten, acc, tags, price) in enumerate(items, 1):
            pid = f"POI-{code}-{i:03d}"
            pois.append({"poi_id": pid, "name_zh": zh, "name_local": jp, "city": city, "district": dist, "lat": lat,
                         "lng": lng, "category": cat, "closed_days": closed,
                         "open_from": "09:00:00" if cat != "shopping" else "10:00:00",
                         "open_to": "17:00:00" if cat in ("museum", "temple") else "20:00:00",
                         "duration_min": dur, "intensity": inten, "accessible": acc,
                         "min_age": None, "tags": tags, "status": "active", "is_synthetic": True, "updated_at": FRESH})
            rates.append(rate(f"RP-{pid}", "ticket", pid, "SUP-012", date(2026, 4, 1), date(2027, 3, 31), price, 0,
                              "normal", "contracted", FRESH, "per_person"))
    return pois, rates


# ─────────────────────────── 门禁：12 类约束陷阱 ───────────────────────────
def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def assert_traps(data: dict) -> list[tuple[str, bool, str]]:
    """种子数据的验收测试——不通过就不许入库。返回 [(陷阱, 通过?, 说明)]。"""
    hotels, rooms, rates = data["hotel"], data["room_type"], data["rate_plan"]
    pois, rests, vehicles = data["poi"], data["restaurant"], data["vehicle"]
    by_hotel: dict[str, list[dict]] = {}
    for r in rooms:
        by_hotel.setdefault(r["hotel_id"], []).append(r)
    checks = []

    t1_hotels = [h for h in hotels if all(r["max_occupancy"] == 2 for r in by_hotel[h["hotel_id"]])]
    checks.append(("T1 房型只能住 2 人的酒店 ≥5", len(t1_hotels) >= 5, f"{len(t1_hotels)} 家"))
    ryokan_ids = {h["hotel_id"] for h in hotels if h["tier"] == "ryokan"}
    t2 = {r["hotel_id"] for r in rooms if r["hotel_id"] in ryokan_ids and r["min_child_age"] in (7, 12)}
    checks.append(("T2 限制儿童年龄(7/12)的 ryokan ≥3", len(t2) >= 3, f"{len(t2)} 家"))
    t3 = [r for r in rooms if r["extra_bed"] == {"available": False}]
    checks.append(("T3 不允许加床的房型 ≥4", len(t3) >= 4, f"{len(t3)} 个"))
    t4 = [p for p in pois if p["closed_days"] == [1]]
    checks.append(("T4 周一休馆的 POI ≥6", len(t4) >= 6, f"{len(t4)} 个"))
    t5 = [r for r in rests if r["closed_days"] == [2]]
    checks.append(("T5 周二定休的餐厅 ≥5", len(t5) >= 5, f"{len(t5)} 家"))
    t6 = [r for r in rests if "no_raw" not in r["dietary_support"]]
    checks.append(("T6 不支持忌生食的餐厅 ≥15", len(t6) >= 15, f"{len(t6)} 家"))
    t7 = [v for v in vehicles if v["seats"] == 7 and v["luggage_28"] == 3]
    checks.append(("T7 座位够行李不够的车(7座/3箱) ≥2", len(t7) >= 2, f"{len(t7)} 台"))
    t8 = [r for r in rates if date.fromisoformat(r["valid_to"]) < date(2026, 10, 1)]
    checks.append(("T8 合约已过期的价格档 ≥4", len(t8) >= 4, f"{len(t8)} 个"))
    cutoff = NOW - timedelta(days=90)
    t9 = [r for r in rates if r["confidence"] == "reference" and datetime.fromisoformat(r["updated_at"]) < cutoff]
    checks.append(("T9 参考价且超 90 天的价格档 ≥8", len(t9) >= 8, f"{len(t9)} 个"))
    t10 = [p for p in pois if p["accessible"] is False]
    checks.append(("T10 不适配无障碍的 POI ≥8", len(t10) >= 8, f"{len(t10)} 个"))
    t11a = [r for r in rooms if r["min_child_age"] is None]
    t11b = [p for p in pois if p["closed_days"] is None]
    checks.append(("T11 空值：closed_days NULL 的 POI ≥5 且 min_child_age NULL 的房型 ≥3",
                   len(t11b) >= 5 and len(t11a) >= 3, f"POI {len(t11b)} 个 / 房型 {len(t11a)} 个"))
    # T12：箱根↔京都同日安排必然超阈值（haversine×1.35÷25km/h > 300 min）
    hk = next(p for p in pois if p["city"] == "箱根")
    ky = next(p for p in pois if p["city"] == "京都")
    minutes = haversine_km(hk["lat"], hk["lng"], ky["lat"], ky["lng"]) * 1.35 / 25 * 60
    checks.append(("T12 箱根↔京都通勤估算 > 300 min", minutes > 300, f"{minutes:.0f} min"))
    # 主键唯一性
    for name, key in (("hotel", "hotel_id"), ("room_type", "room_id"), ("rate_plan", "rate_id"), ("vehicle", "vehicle_id"),
                      ("restaurant", "rest_id"), ("poi", "poi_id"), ("supplier", "supplier_id")):
        ids = [r[key] for r in data[name]]
        if len(ids) != len(set(ids)):
            raise AssertionError(f"{name}.{key} 存在重复主键")
    # 规模断言：核心数据（PRD-v3 §4.2）之上叠加扩充数据，只增不减
    checks_scale = [("hotel≥42", len(hotels) >= 42), ("restaurant≥60", len(rests) >= 60), ("poi≥75", len(pois) >= 75),
                    ("supplier≥15", len(data["supplier"]) >= 15)]
    for name, ok in checks_scale:
        if not ok:
            raise AssertionError(f"规模不符：{name}")
    return checks


CATALOG_TABLES = ("supplier", "hotel", "room_type", "vehicle", "restaurant", "poi", "ticket", "route", "history_plan")
GOVERNED = {"hotel": "hotel_id", "restaurant": "rest_id", "poi": "poi_id", "vehicle": "vehicle_id",
            "ticket": "ticket_id", "route": "route_id"}


def assert_catalog(data: dict) -> list[tuple[str, bool, str]]:
    """知识库规模、类目、标签体系、来源标注与引用完整性的验收（简历口径：约 300 家酒店、40 余家供应商、1,500 余条资料）。"""
    from seed.taxonomy import SOURCE_TYPES, TAGS, VERIFIED_STATUS

    checks = []
    n = {k: len(data.get(k, [])) for k in CATALOG_TABLES}
    total = sum(n.values())
    checks.append(("C1 酒店 300 家", n["hotel"] == 300, f"{n['hotel']} 家"))
    checks.append(("C2 供应商 ≥40 家", n["supplier"] >= 40, f"{n['supplier']} 家"))
    checks.append(("C3 结构化资料 ≥1500 条（不含价格档）", total >= 1500, f"{total} 条"))
    checks.append(("C4 七大类目齐全（酒店/房型/车辆/餐厅/门票/路线/历史方案）",
                   all(n[k] > 0 for k in ("hotel", "room_type", "vehicle", "restaurant", "ticket", "route", "history_plan")),
                   " / ".join(f"{k}={n[k]}" for k in CATALOG_TABLES)))
    used = {t for k in ("hotel", "restaurant", "poi", "route") for r in data[k] for t in r.get("tags", [])}
    unknown = sorted(used - set(TAGS))
    checks.append(("C5 标签全部登记在标签字典", not unknown, f"{len(used)} 个标签" + (f"，未登记：{unknown}" if unknown else "")))
    bad = [f"{k}:{r[key]}" for k, key in GOVERNED.items() for r in data[k]
           if r.get("source_type") not in SOURCE_TYPES or r.get("verified_status") not in VERIFIED_STATUS
           or not r.get("source_ref") or not r.get("review_due")
           or (r["verified_status"] == "verified" and not (r.get("verified_by") and r.get("verified_at")))]
    checks.append(("C6 每条资源有来源标注与校验状态", not bad, f"缺失 {len(bad)} 条" + (f"：{bad[:3]}" if bad else "")))
    today = TODAY.isoformat()
    drift = [r[key] for k, key in GOVERNED.items() for r in data[k]
             if (r["verified_status"] == "expired") != (r["review_due"] < today and r["verified_status"] != "pending")]
    checks.append(("C7 复核过期状态与到期日一致", not drift, f"不一致 {len(drift)} 条"))
    ids = {k: {r[key] for r in data[k]} for k, key in (("hotel", "hotel_id"), ("poi", "poi_id"), ("route", "route_id"),
                                                       ("supplier", "supplier_id"))}
    dangling = ([r["room_id"] for r in data["room_type"] if r["hotel_id"] not in ids["hotel"]]
                + [t["ticket_id"] for t in data["ticket"] if t["poi_id"] and t["poi_id"] not in ids["poi"]]
                + [r["route_id"] for r in data["route"] for p in r["poi_ids"] if p not in ids["poi"]]
                + [h["plan_id"] for h in data["history_plan"] for x in h["hotel_ids"] if x not in ids["hotel"]]
                + [h["plan_id"] for h in data["history_plan"] for x in h["route_ids"] if x not in ids["route"]]
                + [r.get("supplier_id") for k in ("hotel", "vehicle", "ticket") for r in data[k]
                   if r.get("supplier_id") and r["supplier_id"] not in ids["supplier"]])
    checks.append(("C8 引用完整（房型/门票/路线/历史方案/供应商外键）", not dangling, f"悬空 {len(dangling)} 个"))
    priced = [k for k in ("ticket", "route", "history_plan") for r in data[k]
              if any(f in r for f in ("price", "net_price", "price_cny"))]
    checks.append(("C9 价格只存在于价格档表", not priced, "资料表无价格字段" if not priced else f"{priced[:3]}"))
    return checks


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from seed.extend import extend

    suppliers = gen_suppliers()
    hotels, rooms, room_rates = gen_hotels()
    vehicles, veh_rates = gen_vehicles()
    rests, rest_rates = gen_restaurants()
    pois, poi_rates = gen_pois()
    data = {"supplier": suppliers, "hotel": hotels, "room_type": rooms,
            "rate_plan": room_rates + veh_rates + rest_rates + poi_rates,
            "vehicle": vehicles, "restaurant": rests, "poi": pois}
    data = extend(data)          # 核心数据之后再扩充（独立随机种子，核心数据不变）
    checks = assert_traps(data) + assert_catalog(data)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in data.items():
        (DATA_DIR / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {name:<12} {len(rows):>4} 条 → seed/data/{name}.json")
    passed = 0
    for name, ok, note in checks:
        print(f"  [{'✓' if ok else '✗'}] {name}：{note}")
        passed += ok
    print(f"约束陷阱 + 知识库验收：{passed}/{len(checks)} 通过")
    if passed != len(checks):
        sys.exit(1)


if __name__ == "__main__":
    main()
