"""检索输入输出（一套三用）。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

TIERS = {"4star", "5star", "luxury", "ryokan", "boutique"}


class HotelQuery(BaseModel):
    city: str
    checkin: date
    checkout: date
    adults: int = Field(ge=1)
    children: int = Field(ge=0, default=0)
    child_ages: list[int] = []
    tiers: list[str] = Field(default_factory=lambda: sorted(TIERS))
    max_price_per_night: Decimal | None = None
    require_tags: list[str] = []
    accessible_required: bool = False

    @model_validator(mode="after")
    def _check(self) -> "HotelQuery":
        if self.checkout <= self.checkin:
            raise ValueError("checkout 必须晚于 checkin")
        if len(self.child_ages) != self.children:
            raise ValueError("child_ages 长度必须等于 children")
        bad = set(self.tiers) - TIERS
        if bad:
            raise ValueError(f"未知档次: {sorted(bad)}")
        return self


class HotelCandidate(BaseModel):
    hotel_id: str
    room_id: str
    rate_id: str | None
    name_zh: str
    name_local: str | None
    city: str
    district: str | None
    tier: str
    tags: list[str]
    lat: float
    lng: float
    room_name: str
    max_occupancy: int
    max_adults: int
    max_children: int
    min_child_age: int | None
    child_age_unknown: bool
    extra_bed: dict | None
    net_price: Decimal | None
    season_uplift: Decimal | None
    confidence: str | None
    rate_updated_at: str | None
    verified_status: str = "verified"     # 数据治理：pending → 约束层判 UNKNOWN（H12）
    hotel_updated_at: str
    score: float = 0.0


class RelaxationHint(BaseModel):
    field: str
    suggestion: str
    would_yield: int


class SearchResult(BaseModel):
    candidates: list[HotelCandidate]
    relaxation_hints: list[RelaxationHint] = []
    total_before_filter: int | None = None
    funnel: dict[str, int] = {}
    cost_visible: bool = True
