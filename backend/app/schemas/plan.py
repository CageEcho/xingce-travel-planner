"""行程结构。

⚠️ PlannedItem 是 LLM 的输出边界：没有 name / price / duration / opening_hours 等任何事实字段。
   它想编也没有字段可以编（PRD-v2 决策 D2 + 防线①）。事实字段由 render.py 从 DB 回填。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ChecklistItem, Violation
from app.schemas.cost import CostSummary

Slot = Literal["morning", "lunch", "afternoon", "dinner", "evening", "accommodation", "transport"]
ItemType = Literal["hotel", "restaurant", "poi", "vehicle", "transfer", "free_time"]


# 解析器要宽容（手册 §九.3）：模型偶尔用同义词，归一化到枚举而不是整份重试。JSON Schema 仍只暴露枚举值。
TYPE_ALIASES: dict[str, str] = {
    "hotel": "hotel", "accommodation": "hotel", "lodging": "hotel", "stay": "hotel", "ryokan": "hotel",
    "restaurant": "restaurant", "dining": "restaurant", "meal": "restaurant", "lunch": "restaurant", "dinner": "restaurant", "food": "restaurant",
    "poi": "poi", "attraction": "poi", "sight": "poi", "sightseeing": "poi", "activity": "poi", "experience": "poi", "museum": "poi", "temple": "poi",
    "vehicle": "vehicle", "transport": "vehicle", "transportation": "vehicle", "car": "vehicle", "charter": "vehicle", "transfer_car": "vehicle",
    "transfer": "transfer", "train": "transfer", "shinkansen": "transfer",
    "free_time": "free_time", "free": "free_time", "rest": "free_time", "leisure": "free_time", "freetime": "free_time",
}
SLOT_ALIASES: dict[str, str] = {
    "morning": "morning", "am": "morning", "breakfast": "morning",
    "lunch": "lunch", "noon": "lunch", "midday": "lunch",
    "afternoon": "afternoon", "pm": "afternoon",
    "dinner": "dinner", "supper": "dinner",
    "evening": "evening", "night": "evening",
    "accommodation": "accommodation", "hotel": "accommodation", "stay": "accommodation", "lodging": "accommodation",
    "transport": "transport", "transfer": "transport", "transportation": "transport", "travel": "transport",
}


class PlannedItem(BaseModel):
    slot: Slot
    type: ItemType
    resource_id: str | None = None      # free_time / transfer 时可为 None；hotel 时填 hotel_id
    room_id: str | None = None          # type=hotel 时必填
    nights: int | None = None
    start_time: str | None = None       # "09:30"
    reason_slots: list[str] = []        # 命中了哪些需求槽位
    reason_note: str = ""               # 一句话理由（自然语言，但不含事实数字）

    @field_validator("type", mode="before")
    @classmethod
    def _norm_type(cls, v: object) -> object:
        if isinstance(v, str):
            return TYPE_ALIASES.get(v.strip().lower().replace("-", "_").replace(" ", "_"), v)
        return v

    @field_validator("slot", mode="before")
    @classmethod
    def _norm_slot(cls, v: object) -> object:
        if isinstance(v, str):
            return SLOT_ALIASES.get(v.strip().lower().replace("-", "_").replace(" ", "_"), v)
        return v

    @field_validator("reason_slots", mode="before")
    @classmethod
    def _norm_reason_slots(cls, v: object) -> object:
        if isinstance(v, str):                       # 模型偶尔给逗号分隔字符串
            return [x.strip() for x in v.split(",") if x.strip()]
        return v


class PlannedDay(BaseModel):
    day_index: int
    date: str
    city: str
    theme: str
    is_transfer: bool = False
    items: list[PlannedItem]


class ItineraryPlan(BaseModel):
    days: list[PlannedDay]
    assumptions: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _unwrap(cls, data: object) -> object:
        """模型偶尔多包一层（{"plan": {...}} / {"itinerary": {...}}）：只有一个 dict 值且里面有 days 时解包。"""
        if isinstance(data, dict) and "days" not in data:
            inner = [v for v in data.values() if isinstance(v, dict) and "days" in v]
            if len(inner) == 1:
                return inner[0]
        return data


# ───────────── 渲染后（事实回填）的结构，落 plan_version.structure ─────────────

class Provenance(BaseModel):
    """ⓘ 溯源浮层的数据源。"""
    resource_id: str
    resource_type: str
    updated_at: str | None = None
    price_source: str | None = None     # contracted|reference|historical
    rate_id: str | None = None
    matched_slots: list[str] = []
    satisfied_constraints: list[str] = []
    unknown_constraints: list[str] = []
    source_type: str | None = None      # 来源标注：supplier_contract|official_site|advisor_visit|ota_reference|historical_order
    verified_status: str | None = None  # verified|pending
    verified_at: str | None = None
    review_due: str | None = None


class Recommendation(BaseModel):
    """产品推荐（确定性规则，不经过模型）：方案用到的景点对应的门票/预约产品，以及可替换的主题路线。"""
    kind: Literal["ticket", "route"]
    ref_id: str
    name_zh: str
    city: str
    day_index: int | None = None
    reason: str
    reservation_required: bool = False
    lead_time_days: int = 0
    notes: str | None = None


class RenderedItem(BaseModel):
    slot: Slot
    type: ItemType
    resource_id: str | None = None
    room_id: str | None = None
    nights: int | None = None
    start_time: str | None = None
    # ↓ 全部来自 DB 回填，不来自模型
    name_zh: str | None = None
    name_local: str | None = None
    district: str | None = None
    facts: dict = Field(default_factory=dict)   # 结构化事实（容量 / 营业日 / 座位 …）
    reason_slots: list[str] = []
    reason_note: str = ""
    provenance: Provenance | None = None
    status: Literal["ok", "blocked"] = "ok"
    block_reason: str | None = None


class RenderedDay(BaseModel):
    day_index: int
    date: str
    weekday: int                        # 0=周日..6=周六
    city: str
    theme: str
    is_transfer: bool = False
    items: list[RenderedItem]
    commute_min_est: int | None = None  # H5 估算


class RenderedPlan(BaseModel):
    days: list[RenderedDay]
    assumptions: list[str] = []
    render_errors: list["RenderError"] = []
    recommendations: list[Recommendation] = []


class RenderError(BaseModel):
    day_index: int
    item_index: int
    kind: Literal["id_not_in_pool", "id_not_found", "field_mismatch", "type_mismatch"]
    resource_id: str | None = None
    detail: str


class PlanCreate(BaseModel):
    card_id: str


class PlanAccepted(BaseModel):
    plan_id: str
    task_id: str


class PlanVersionView(BaseModel):
    plan_id: str
    version: int
    card_id: str
    status: str
    structure: RenderedPlan
    cost: CostSummary | None
    cost_visible: bool = True
    violations: list[Violation]
    checklist: list[ChecklistItem]
    blocking_count: int
    unknown_count: int
    replan_rounds: int
    created_at: str
    synthetic_notice: str = "资源数据为模拟数据集，非真实供应商信息。"
