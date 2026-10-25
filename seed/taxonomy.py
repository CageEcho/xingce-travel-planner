"""知识库标签体系与数据治理口径（唯一来源）。

- TAGS：标签字典。tag → (中文名, 分组, 适用资源类型)。种子数据里出现的每个标签都必须在这里登记，
  generate.assert_catalog() 会校验；入库后写入 tag_dict 表，Dify 知识库文档也从这里取中文名。
- SOURCE_TYPES / REVIEW_CYCLE_DAYS：来源标注与复核周期（更新机制）。
"""
from __future__ import annotations

# 适用资源类型缩写
H, R, P, T, RT = "hotel", "restaurant", "poi", "ticket", "route"

TAG_GROUPS = {
    "facility": "设施", "style": "风格", "audience": "客群", "dining": "餐饮", "scene": "场景",
    "experience": "体验", "location": "区位", "constraint": "约束提示",
}

TAGS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    # 设施
    "family_room": ("家庭房", "facility", (H,)), "connecting_rooms": ("连通房", "facility", (H,)),
    "kids_club": ("儿童俱乐部", "facility", (H,)), "pool": ("泳池", "facility", (H,)),
    "spa": ("SPA", "facility", (H,)), "onsen": ("温泉", "facility", (H, P)),
    "private_bath": ("私汤", "facility", (H,)), "club_lounge": ("行政酒廊", "facility", (H,)),
    "private_room": ("包间", "facility", (R,)), "counter": ("吧台座", "facility", (R,)),
    "buffet": ("自助早餐", "facility", (H,)), "footbath": ("足汤", "facility", (P,)),
    "day_spa": ("日归温泉", "facility", (P,)),
    # 风格
    "quiet": ("安静", "style", (H, P)), "design": ("设计感", "style", (H,)), "heritage": ("历史建筑", "style", (H, R, P)),
    "garden": ("庭园", "style", (H, R, P)), "machiya": ("京町家", "style", (H, R)), "alley": ("小巷", "style", (H,)),
    "luxury": ("奢华", "style", (P,)), "retro": ("复古", "style", (P,)), "zen": ("禅", "style", (P,)),
    "temple_style": ("寺院风格", "style", (R,)), "casual": ("休闲", "style", (R,)), "home_style": ("家常", "style", (R,)),
    # 客群
    "value": ("性价比", "audience", (H,)), "youth": ("年轻客群", "audience", (H,)), "business": ("商务", "audience", (H,)),
    "family": ("亲子友好", "audience", (R, RT)), "kids": ("适合儿童", "audience", (P, RT)),
    "couple": ("情侣蜜月", "audience", (H, RT)), "elderly": ("长辈友好", "audience", (H, RT)),
    "accessible_route": ("无障碍线路", "audience", (RT,)),
    # 餐饮
    "kaiseki": ("怀石料理", "dining", (H,)), "michelin_dining": ("米其林餐厅", "dining", (H,)), "dining": ("餐饮出色", "dining", (H,)),
    "michelin": ("米其林", "dining", (R,)), "omakase": ("主厨发办", "dining", (R,)), "wagyu": ("和牛", "dining", (R,)),
    "edomae": ("江户前", "dining", (R,)), "yukhoe": ("生拌牛肉", "dining", (R,)), "duck_sashimi": ("鸭刺身", "dining", (R,)),
    "dessert": ("甜品", "dining", (R,)), "quick": ("出餐快", "dining", (R,)), "late_night": ("营业到深夜", "dining", (R,)),
    "seasonal": ("季节限定", "dining", (R, P)), "sake": ("清酒", "dining", (H,)), "sweets": ("和果子", "dining", (P,)),
    "food": ("美食", "dining", (P, RT)), "market": ("市场", "dining", (R, P)), "tea_ceremony": ("茶道", "experience", (H, P)),
    # 场景
    "city_view": ("城景", "scene", (H, P)), "river_view": ("河景", "scene", (H, R)), "bay_view": ("海湾景", "scene", (H, R)),
    "lake_view": ("湖景", "scene", (H, R, P)), "park_view": ("公园景", "scene", (H,)), "view": ("景观", "scene", (R, P)),
    "night": ("夜游", "scene", (P, RT)), "night_illumination": ("夜间点灯", "scene", (P,)), "morning": ("宜早去", "scene", (P,)),
    "rainy_day": ("雨天可去", "scene", (P, RT)), "autumn": ("秋季", "scene", (P,)), "scenic": ("风景", "scene", (P,)),
    "lake": ("湖", "scene", (P,)), "river": ("河畔", "scene", (P,)), "forest": ("森林", "scene", (P,)),
    "nature": ("自然", "scene", (P, RT)), "outdoor": ("户外", "scene", (P,)), "picnic": ("野餐", "scene", (P,)),
    "walk": ("步行", "scene", (P,)), "volcanic": ("火山地貌", "scene", (P,)), "moss_garden": ("苔庭", "scene", (P,)),
    "zen_garden": ("枯山水", "scene", (P,)), "tea_house": ("茶屋", "scene", (P,)), "onsen_town": ("温泉街", "scene", (R,)),
    "relax": ("放松", "scene", (P, RT)),
    # 体验
    "art": ("艺术", "experience", (H, P, RT)), "history": ("历史", "experience", (P, RT)), "culture": ("文化", "experience", (P,)),
    "craft": ("手作工艺", "experience", (H, P)), "hands_on": ("动手体验", "experience", (P,)), "anime": ("动漫", "experience", (P,)),
    "animals": ("动物", "experience", (P,)), "trains": ("火车", "experience", (P,)), "science": ("科学", "experience", (P,)),
    "sumo": ("相扑", "experience", (P,)), "immersive": ("沉浸式", "experience", (P,)), "theme_park": ("主题乐园", "experience", (P,)),
    "shopping": ("购物", "experience", (H, P, RT)), "shopping_street": ("商店街", "experience", (P,)),
    "shrine": ("神社", "experience", (P,)), "temple": ("寺院", "experience", (P, RT)), "torii": ("鸟居", "experience", (P,)),
    "pagoda": ("五重塔", "experience", (P,)), "statues": ("雕塑", "experience", (P,)), "aqueduct": ("水路阁", "experience", (P,)),
    "glass": ("玻璃艺术", "experience", (P,)), "ceramics": ("陶艺", "experience", (P,)), "black_egg": ("黑玉子", "experience", (P,)),
    "cafe": ("咖啡", "experience", (P,)), "iconic": ("地标", "experience", (P,)), "show": ("表演", "experience", (R,)),
    "geisha_district": ("花街", "experience", (H, P)), "hike": ("徒步", "experience", (P,)), "transport": ("交通体验", "experience", (P,)),
    "local": ("在地感", "experience", (H, R, P)), "nightlife": ("夜生活", "experience", (H,)), "onsen_tour": ("温泉巡游", "experience", (RT,)),
    # 区位
    "central": ("市中心", "location", (H,)), "shinkansen_access": ("近新干线", "location", (H,)),
    # 约束提示
    "crowded": ("人多", "constraint", (P,)), "reservation": ("需预约", "constraint", (P, T)), "full_day": ("需一整天", "constraint", (P,)),
}

CUISINE_ZH = {"sushi": "寿司", "kappo": "割烹", "tempura": "天妇罗", "soba": "荞麦面", "kaiseki": "怀石", "teppanyaki": "铁板烧",
              "yakiniku": "烧肉", "french": "法餐", "ramen": "拉面", "italian": "意大利菜", "tofu": "豆腐料理", "unagi": "鳗鱼",
              "shojin": "精进料理", "izakaya": "居酒屋", "sukiyaki": "寿喜烧", "kyo_ryori": "京料理", "cafe": "咖啡简餐",
              "western": "洋食", "seafood": "海鲜", "yakitori": "烧鸟", "obanzai": "京都家常菜", "shabu": "涮涮锅",
              "kushikatsu": "串炸", "chinese": "中餐", "udon": "乌冬"}

# ───────────── 来源标注 + 复核周期（更新机制） ─────────────
SOURCE_TYPES = {
    "supplier_contract": "供应商合同/报价单",
    "official_site": "官方网站/公告",
    "advisor_visit": "顾问实地踩线",
    "ota_reference": "OTA 公开信息（参考）",
    "historical_order": "历史订单回填",
}
VERIFIED_STATUS = {"verified": "已人工校验", "pending": "待校验", "expired": "复核过期"}
# 每类资源的复核周期（天）：营业信息变化快的类目周期短
REVIEW_CYCLE_DAYS = {"hotel": 180, "restaurant": 90, "poi": 180, "vehicle": 365, "ticket": 90, "route": 180}
# 校验人（顾问编号，脱敏）
REVIEWERS = ["ADV-01", "ADV-02", "ADV-03", "ADV-04", "ADV-05", "ADV-06", "ADV-07", "ADV-08"]


def tag_rows() -> list[dict]:
    return [{"tag": k, "label_zh": v[0], "tag_group": v[1], "applies_to": list(v[2])} for k, v in TAGS.items()]
