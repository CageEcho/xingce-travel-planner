"""把 seed/data 的演示资源转换成 Dify 知识库文档（Markdown）。

每条资源一个分段，分段之间用「\n\n---\n\n」分隔，Dify 里按该分隔符做自定义分段。
标签中文名、来源与校验口径统一取自 seed/taxonomy.py；每条资源都带「来源 · 校验状态 · 下次复核」。
不写入任何净价 / 价格档 ID / 供应商合同信息——与主系统「模型不输出价格」的原则一致，价格以系统报价为准。

用法：python dify/build_knowledge.py   → 写入 dify/knowledge/01-*.md、04-历史方案库.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from seed.taxonomy import CUISINE_ZH, SOURCE_TYPES, TAGS, VERIFIED_STATUS  # noqa: E402

DATA = ROOT / "seed" / "data"
OUT = ROOT / "dify" / "knowledge"
SEP = "\n\n---\n\n"
CITIES = ["东京", "京都", "箱根"]

TIER = {"4star": "四星", "5star": "五星", "luxury": "奢华", "ryokan": "高端旅馆", "boutique": "精品"}
CATEGORY = {"city_hotel": "城市酒店", "luxury_hotel": "奢华酒店", "ryokan": "日式旅馆", "boutique_hotel": "精品酒店",
            "museum": "博物馆/美术馆", "temple": "寺社", "experience": "体验", "nature": "自然", "shopping": "购物"}
FEATURE = {"city_view": "城景", "bathtub": "浴缸", "sofa": "沙发", "family": "家庭", "connecting_available": "可连通",
           "tatami": "榻榻米", "design": "设计感", "garden_view": "庭园景", "private_bath": "私汤", "living_room": "客厅"}
PRICE = {"luxury": "奢华", "high": "高", "mid": "中", "budget": "平价"}
DIET = {"no_raw": "忌生食", "vegetarian": "素食", "gluten_free": "无麸质", "vegan": "纯素", "no_pork": "不含猪肉", "halal": "清真"}
INTENSITY = {"easy": "轻松", "moderate": "中等", "hard": "高强度"}
WEEK = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
BED = {"king": "大床", "twin": "单人床", "queen": "大床", "sofa_bed": "沙发床", "tatami": "榻榻米铺位", "double": "双人床"}
TICKET_TYPE = {"general": "普通门票", "timed_entry": "按时段预约入场", "priority": "快速通道", "special_visit": "特别参观",
               "guided_tour": "中文导览", "pass": "通票"}
AUDIENCE = {"kids": "儿童", "family": "家庭", "elderly": "长辈", "couple": "情侣", "accessible_route": "轮椅/行动不便"}


def tags_zh(items) -> str:
    return "、".join(TAGS[t][0] if t in TAGS else t for t in (items or [])) or "无"


def zh(mapping: dict, items) -> str:
    return "、".join(mapping.get(x, x) for x in (items or [])) or "无记录"


def closed(days) -> str:
    if days is None:
        return "未记录（需核实）"
    return "、".join(WEEK[d] for d in days) or "无固定休息日"


def governance(r: dict) -> str:
    src = SOURCE_TYPES.get(r.get("source_type"), "未标注")
    status = VERIFIED_STATUS.get(r.get("verified_status"), "未知")
    if r.get("verified_status") == "pending":
        return f"- 资料来源：{src}；状态：{status}（需在 {r['review_due']} 前完成校验，使用前必须核实）"
    if r.get("verified_status") == "expired":
        return f"- 资料来源：{src}；状态：{status}（{r['review_due']} 到期未复核，不得用于方案）"
    return f"- 资料来源：{src}；状态：{status}（{r.get('verified_at')}），下次复核 {r.get('review_due')}"


def load(name: str) -> list[dict]:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def hotel_blocks(hotels, rooms) -> dict[str, list[str]]:
    by_hotel = defaultdict(list)
    for r in rooms:
        by_hotel[r["hotel_id"]].append(r)
    out = defaultdict(list)
    for h in hotels:
        lines = [
            f"## 【酒店】{h['name_zh']}（{h['name_local']}）",
            f"- 资源ID：{h['hotel_id']}",
            f"- 城市/区域：{h['city']} · {h['district']}；最近车站：{h['nearest_station']}，步行约 {h['walk_min']} 分钟",
            f"- 档次：{TIER[h['tier']]}（{CATEGORY[h['category']]}）",
            f"- 特色标签：{tags_zh(h['tags'])}",
            f"- 顾问备注：{h['advisor_notes']}",
            "- 房型：",
        ]
        for r in by_hotel[h["hotel_id"]]:
            beds = "+".join(f"{BED.get(k, k)}×{v}" for k, v in r["bed_config"].items())
            age = "未记录（需核实）" if r["min_child_age"] is None else f"{r['min_child_age']} 岁及以上"
            eb = r["extra_bed"]
            extra = (f"可加床（{eb.get('min_age', 0)} 岁及以上）" if eb.get("available") else "不可加床")
            lines.append(
                f"  - {r['room_id']} {r['name_zh']}：{beds}；最多 {r['max_occupancy']} 人"
                f"（成人≤{r['max_adults']}，儿童≤{r['max_children']}）；儿童最低入住年龄 {age}；{extra}；"
                f"房内：{zh(FEATURE, r['features'])}")
        lines += [governance(h), "- 价格说明：实时房价、季节加价与封房日以行策系统报价为准，知识库不提供价格。"]
        out[h["city"]].append("\n".join(lines))
    return out


def restaurant_blocks(rests) -> dict[str, list[str]]:
    out = defaultdict(list)
    for r in rests:
        kid = {True: "是", False: "否", None: "未记录（需核实）"}[r["child_friendly"]]
        out[r["city"]].append("\n".join([
            f"## 【餐厅】{r['name_zh']}（{r['name_local']}）",
            f"- 资源ID：{r['rest_id']}",
            f"- 城市/区域：{r['city']} · {r['district']}",
            f"- 菜系：{CUISINE_ZH.get(r['cuisine'], r['cuisine'])}；价位档：{PRICE[r['price_band']]}",
            f"- 营业：{r['open_from'][:5]}–{r['open_to'][:5]}；休息日：{closed(r['closed_days'])}",
            f"- 可满足饮食限制：{zh(DIET, r['dietary_support']) if r['dietary_support'] else '未记录（不建议用于有忌口客人）'}",
            f"- 儿童友好：{kid}；需提前 {r['lead_time_days']} 天预订",
            f"- 特色标签：{tags_zh(r['tags'])}",
            governance(r),
        ]))
    return out


def poi_blocks(pois, tickets_by_poi) -> list[str]:
    out = []
    for p in pois:
        age = "无限制" if p["min_age"] is None else f"{p['min_age']} 岁及以上"
        tk = tickets_by_poi.get(p["poi_id"], [])
        need = [t for t in tk if t["ticket_type"] == "timed_entry"]
        out.append("\n".join([
            f"## 【景点】{p['name_zh']}（{p['name_local']}）",
            f"- 资源ID：{p['poi_id']}",
            f"- 城市/区域：{p['city']} · {p['district']}",
            f"- 类别：{CATEGORY.get(p['category'], p['category'])}；体力强度：{INTENSITY[p['intensity']]}；建议游览 {p['duration_min']} 分钟",
            f"- 开放：{(p['open_from'] or '')[:5]}–{(p['open_to'] or '')[:5]}；休息日：{closed(p['closed_days'])}",
            f"- 无障碍：{'可轮椅通行' if p['accessible'] else ('不便轮椅/台阶较多' if p['accessible'] is False else '未记录（需核实）')}；年龄限制：{age}",
            f"- 标签：{tags_zh(p['tags'])}",
            f"- 门票：{'必须按时段预约（至少提前 ' + str(need[0]['lead_time_days']) + ' 天）' if need else ('现场购票' if tk else '免费或无需门票')}",
            governance(p),
        ]))
    return out


def vehicle_blocks(vehicles) -> list[str]:
    return ["\n".join([
        f"## 【用车】{v['city']} · {v['name_zh']}",
        f"- 资源ID：{v['vehicle_id']}",
        f"- 可载乘客：{v['seats']} 人；28 寸行李：{v['luggage_28'] if v['luggage_28'] is not None else '未记录（需核实）'} 件；"
        f"单日服务时长：{v['service_hours']} 小时",
        "- 选车规则：乘客数与 28 寸行李数需同时满足；带婴儿座椅或轮椅需额外占位，需提前确认。",
        governance(v),
    ]) for v in vehicles]


def ticket_blocks(tickets, poi_name) -> list[str]:
    return ["\n".join([
        f"## 【门票】{t['name_zh']}",
        f"- 门票ID：{t['ticket_id']}；对应景点：{poi_name.get(t['poi_id'], '通票（不对应单一景点）')}"
        + (f"（{t['poi_id']}）" if t["poi_id"] else ""),
        f"- 城市：{t['city']}；类型：{TICKET_TYPE[t['ticket_type']]}；适用季节：{t['valid_season']}",
        f"- 预约：{'需要，至少提前 ' + str(t['lead_time_days']) + ' 天' if t['reservation_required'] else '不需要'}；"
        f"儿童票适用：{str(t['child_age_max']) + ' 岁及以下' if t['child_age_max'] is not None else '—'}；"
        f"可退改：{'是' if t['refundable'] else ('否' if t['refundable'] is False else '未记录')}",
        f"- 说明：{t['notes']}",
        governance(t),
    ]) for t in tickets]


def route_blocks(routes, poi_name) -> list[str]:
    return ["\n".join([
        f"## 【路线】{r['name_zh']}",
        f"- 路线ID：{r['route_id']}；城市：{r['city']}；主题：{r['theme']}；时长：{'半日' if r['duration_type'] == 'half_day' else '一日'}"
        f"（含交通约 {r['total_minutes'] // 60} 小时 {r['total_minutes'] % 60} 分钟）",
        "- 景点顺序：" + " → ".join(f"{poi_name[p]}（{p}）" for p in r["poi_ids"]),
        f"- 体力强度：{INTENSITY[r['intensity']]}；全程无障碍：{ {True: '是', False: '否', None: '未记录（需核实）'}[r['accessible']] }",
        f"- 适合人群：{zh(AUDIENCE, r['suitable_for'])}；标签：{tags_zh(r['tags'])}",
        f"- 注意事项：{r['notes']}",
        governance(r),
    ]) for r in routes]


def history_blocks(plans, hotel_name, route_name) -> list[str]:
    out = []
    for h in plans:
        out.append("\n".join([
            f"## 【历史方案】{h['plan_id']} · {h['party_type']}",
            f"- 概况：{h['summary']}",
            f"- 预算区间：{h['budget_band']}；出行月份：{h['travel_month']}",
            "- 所用酒店：" + ("、".join(f"{hotel_name[x]}（{x}）" for x in h["hotel_ids"]) or "—"),
            "- 参考路线：" + ("、".join(route_name[x] for x in h["route_ids"]) or "—"),
            f"- 结果：{h['outcome']}；返工 {h['rework_rounds']} 轮；客户评分：{h['client_rating'] or '—'}",
            f"- Bad Case 归因：{'、'.join(h['bad_case_tags']) or '无'}",
            f"- 复盘：{h['lessons']}",
            "- 说明：脱敏模拟数据，仅供借鉴编排思路，不可作为报价依据。",
        ]))
    return out


def write(name: str, title: str, intro: str, blocks: list[str]) -> None:
    (OUT / name).write_text(f"# {title}\n\n{intro}" + SEP + SEP.join(blocks) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("01-资源库-*.md"):
        old.unlink()
    intro = ("演示用模拟数据，不代表真实供应商库存、价格或可售状态。资源ID与行策系统资源池一致，编排时只能引用资源ID。"
             "「复核过期」的资源不得用于方案，「待校验」的资源使用前必须核实。")
    hotels, rooms, pois = load("hotel"), load("room_type"), load("poi")
    tickets, routes = load("ticket"), load("route")
    poi_name = {p["poi_id"]: p["name_zh"] for p in pois}
    tickets_by_poi = defaultdict(list)
    for t in tickets:
        tickets_by_poi[t["poi_id"]].append(t)
    hb, rb = hotel_blocks(hotels, rooms), restaurant_blocks(load("restaurant"))
    for city in CITIES:
        write(f"01-资源库-酒店-{city}.md", f"行策资源库 · {city}酒店与房型（{len(hb[city])} 家）", intro, hb[city])
        write(f"01-资源库-餐厅-{city}.md", f"行策资源库 · {city}餐厅（{len(rb[city])} 家）", intro, rb[city])
    write("01-资源库-景点.md", f"行策资源库 · 景点（{len(pois)} 处）", intro, poi_blocks(pois, tickets_by_poi))
    write("01-资源库-用车.md", "行策资源库 · 用车", intro, vehicle_blocks(load("vehicle")))
    write("01-资源库-门票.md", f"行策资源库 · 门票与通票（{len(tickets)} 种）", intro, ticket_blocks(tickets, poi_name))
    write("01-资源库-路线.md", f"行策资源库 · 主题路线（{len(routes)} 条）", intro, route_blocks(routes, poi_name))
    plans = load("history_plan")
    write("04-历史方案库.md", f"行策 · 历史方案库（{len(plans)} 份，脱敏）",
          "脱敏模拟的历史定制方案，含客群、所用资源、成交结果、返工轮次与 Bad Case 归因，供编排借鉴。",
          history_blocks(plans, {h["hotel_id"]: h["name_zh"] for h in hotels}, {r["route_id"]: r["name_zh"] for r in routes}))
    print("written:", sorted(p.name for p in OUT.glob("*.md")))


if __name__ == "__main__":
    main()
