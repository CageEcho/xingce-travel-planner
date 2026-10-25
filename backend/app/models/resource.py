"""资源侧表。DDL 依据 PRD-v3 §3.1；门票 / 路线 / 历史方案 / 标签字典与数据治理字段见 seed/taxonomy.py。

⚠️ 空值语义：min_child_age / closed_days / accessible / child_friendly 允许 NULL，
   NULL 表示「未记录」，不等于「无限制」。约束校验器必须判 UNKNOWN 而非 PASS。
⚠️ 数据治理：verified_status=expired（复核过期）的资源不进候选池；pending（待校验）可用但判 UNKNOWN。
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean, Date, Float, ForeignKey, Index, Integer, Numeric, String, Text, Time, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Governed:
    """来源标注 + 人工校验 + 复核到期（更新机制）。取值口径见 seed/taxonomy.py。"""
    source_type: Mapped[str | None] = mapped_column(Text)          # supplier_contract|official_site|advisor_visit|...
    source_ref: Mapped[str | None] = mapped_column(Text)
    verified_status: Mapped[str] = mapped_column(Text, nullable=False, default="verified", server_default="verified")
    verified_by: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[date | None] = mapped_column(Date)
    review_due: Mapped[date | None] = mapped_column(Date)


class Supplier(Base):
    __tablename__ = "supplier"
    supplier_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)              # hotel_group|ryokan_alliance|dmc|transport|dining|ticket
    contract_to: Mapped[date | None] = mapped_column(Date)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")


class Hotel(Governed, Base):
    __tablename__ = "hotel"
    hotel_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    name_local: Mapped[str | None] = mapped_column(Text)
    alias: Mapped[list[str] | None] = mapped_column(ARRAY(Text), default=list)   # M1 用
    city: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float, nullable=False)   # 铁律①必填
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    tier: Mapped[str] = mapped_column(Text, nullable=False)     # 4star|5star|luxury|ryokan|boutique
    category: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    nearest_station: Mapped[str | None] = mapped_column(Text)
    walk_min: Mapped[int | None] = mapped_column(Integer)
    advisor_notes: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[str | None] = mapped_column(Text, ForeignKey("supplier.supplier_id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # PRD-v3 §4.5
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_hotel_city_tier_status", "city", "tier", "status"),)


class RoomType(Base):
    __tablename__ = "room_type"
    room_id: Mapped[str] = mapped_column(Text, primary_key=True)
    hotel_id: Mapped[str] = mapped_column(Text, ForeignKey("hotel.hotel_id"), nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    bed_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    max_occupancy: Mapped[int] = mapped_column(Integer, nullable=False)  # H1 依据
    max_adults: Mapped[int] = mapped_column(Integer, nullable=False)
    max_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_child_age: Mapped[int | None] = mapped_column(Integer)          # NULL = 未记录
    extra_bed: Mapped[dict | None] = mapped_column(JSONB)
    features: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_room_type_hotel_occ", "hotel_id", "max_occupancy"),)


class RatePlan(Base):
    __tablename__ = "rate_plan"
    rate_id: Mapped[str] = mapped_column(Text, primary_key=True)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)  # room|vehicle|ticket|restaurant
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(Text, ForeignKey("supplier.supplier_id"))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)     # H8 依据
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    blackout_dates: Mapped[list[date] | None] = mapped_column(ARRAY(Date), default=list)
    net_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="JPY")
    price_basis: Mapped[str] = mapped_column(Text, nullable=False)     # per_room_night|per_person|per_car_day|per_use
    meal_plan: Mapped[str | None] = mapped_column(Text)
    season_type: Mapped[str] = mapped_column(Text, nullable=False, default="normal")
    season_uplift: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=0)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)      # contracted|reference|historical
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_rate_plan_resource", "resource_type", "resource_id", "valid_from", "valid_to"),)


class Vehicle(Governed, Base):
    __tablename__ = "vehicle"
    vehicle_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)        # H4 依据①
    luggage_28: Mapped[int | None] = mapped_column(Integer)            # H4 依据②；NULL = 未记录
    service_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    supplier_id: Mapped[str | None] = mapped_column(Text, ForeignKey("supplier.supplier_id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())


class Restaurant(Governed, Base):
    __tablename__ = "restaurant"
    rest_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    name_local: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    cuisine: Mapped[str] = mapped_column(Text, nullable=False)
    price_band: Mapped[str] = mapped_column(Text, nullable=False)      # budget|mid|high|luxury
    closed_days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # 0=周日..6=周六；NULL = 未记录
    open_from: Mapped[time | None] = mapped_column(Time)
    open_to: Mapped[time | None] = mapped_column(Time)
    dietary_support: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)  # H2 依据
    child_friendly: Mapped[bool | None] = mapped_column(Boolean)       # NULL = 未记录
    lead_time_days: Mapped[int | None] = mapped_column(Integer, default=0)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_restaurant_city_band_status", "city", "price_band", "status"),)


class Poi(Governed, Base):
    __tablename__ = "poi"
    poi_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    name_local: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    district: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)        # temple|museum|nature|experience|shopping
    closed_days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # H3 依据；NULL = 未记录
    open_from: Mapped[time | None] = mapped_column(Time)
    open_to: Mapped[time | None] = mapped_column(Time)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    intensity: Mapped[str] = mapped_column(Text, nullable=False, default="moderate")
    accessible: Mapped[bool | None] = mapped_column(Boolean)           # H9 依据；NULL = 未记录
    min_age: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_poi_city_category_status", "city", "category", "status"),)


class Ticket(Governed, Base):
    """门票产品（成人/儿童/预约入场/特别参观/导览/通票）。价格在 rate_plan（resource_type=ticket）。"""
    __tablename__ = "ticket"
    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    poi_id: Mapped[str | None] = mapped_column(Text, ForeignKey("poi.poi_id"))   # 通票为 NULL
    city: Mapped[str] = mapped_column(Text, nullable=False)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_type: Mapped[str] = mapped_column(Text, nullable=False)  # general|timed_entry|priority|special_visit|guided_tour|pass
    reservation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_age_max: Mapped[int | None] = mapped_column(Integer)
    refundable: Mapped[bool | None] = mapped_column(Boolean)
    valid_season: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    supplier_id: Mapped[str | None] = mapped_column(Text, ForeignKey("supplier.supplier_id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_ticket_poi", "poi_id"),)


class Route(Governed, Base):
    """路线模板：按主题聚合、地理就近排序的景点序列，供编排参考与产品推荐。"""
    __tablename__ = "route"
    route_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name_zh: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str] = mapped_column(Text, nullable=False)
    duration_type: Mapped[str] = mapped_column(Text, nullable=False)   # half_day|full_day
    poi_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    intensity: Mapped[str] = mapped_column(Text, nullable=False)
    accessible: Mapped[bool | None] = mapped_column(Boolean)
    suitable_for: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    highlights: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (Index("ix_route_city_theme", "city", "theme"),)


class HistoryPlan(Base):
    """历史方案（脱敏）：客群画像、所用酒店与路线、成交结果、返工轮次与 Bad Case 归因。"""
    __tablename__ = "history_plan"
    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    travel_month: Mapped[str] = mapped_column(Text, nullable=False)
    party_type: Mapped[str] = mapped_column(Text, nullable=False)
    adults: Mapped[int] = mapped_column(Integer, nullable=False)
    children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    child_ages: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, default=list)
    with_elderly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_band: Mapped[str | None] = mapped_column(Text)
    hotel_tier: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    dietary: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    accessibility: Mapped[str | None] = mapped_column(Text)
    hotel_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    route_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)          # 成交|修改后成交|未成交
    rework_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    client_rating: Mapped[int | None] = mapped_column(Integer)
    bad_case_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)  # 知识缺失|检索偏差|行程冲突
    lessons: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="historical_order")
    verified_status: Mapped[str] = mapped_column(Text, nullable=False, default="verified")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    desensitized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TagDict(Base):
    """标签字典（标签体系）：资源上出现的每个标签都必须在此登记。"""
    __tablename__ = "tag_dict"
    tag: Mapped[str] = mapped_column(Text, primary_key=True)
    label_zh: Mapped[str] = mapped_column(Text, nullable=False)
    tag_group: Mapped[str] = mapped_column(Text, nullable=False)
    applies_to: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
