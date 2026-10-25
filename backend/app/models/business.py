"""业务侧 6 张表：conversation / message / requirement_card / plan_version / generation_task / trace_log。

generation_task 是本文档相对 PRD-v3 新增的表：长时间任务状态必须持久化可恢复（手册 [A]）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Conversation(Base):
    __tablename__ = "conversation"
    conv_id: Mapped[str] = mapped_column(Text, primary_key=True)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="local-advisor", index=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())


class Message(Base):
    __tablename__ = "message"
    msg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conv_id: Mapped[str] = mapped_column(Text, ForeignKey("conversation.conv_id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # advisor|ai|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())


class RequirementCard(Base):
    __tablename__ = "requirement_card"
    card_id: Mapped[str] = mapped_column(Text, primary_key=True)
    conv_id: Mapped[str] = mapped_column(Text, ForeignKey("conversation.conv_id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    slots: Mapped[dict] = mapped_column(JSONB, nullable=False)          # SlotSet 序列化
    completeness: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    conflicts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    followups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 最近一轮追问
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))  # 人工节点① 凭证
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    __table_args__ = (UniqueConstraint("conv_id", "version", name="uq_card_conv_version"),)


class PlanVersion(Base):
    __tablename__ = "plan_version"
    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[str] = mapped_column(Text, ForeignKey("requirement_card.card_id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")  # M0 只有 draft
    structure: Mapped[dict] = mapped_column(JSONB, nullable=False)      # RenderedPlan
    cost: Mapped[dict] = mapped_column(JSONB, nullable=False)           # CostSummary
    violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    checklist: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # 待人工核实
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())


class GenerationTask(Base):
    __tablename__ = "generation_task"
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    plan_id: Mapped[str] = mapped_column(Text, nullable=False)
    card_id: Mapped[str] = mapped_column(Text, ForeignKey("requirement_card.card_id"), nullable=False)
    # queued|searching|planning|validating|costing|done|failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    replan_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict | None] = mapped_column(JSONB)
    heartbeat_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                   server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    __table_args__ = (Index("ix_generation_task_status_hb", "status", "heartbeat_at"),)


class TraceLog(Base):
    __tablename__ = "trace_log"
    trace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conv_id: Mapped[str | None] = mapped_column(Text)
    plan_id: Mapped[str | None] = mapped_column(Text)
    step: Mapped[str] = mapped_column(Text, nullable=False)  # extract|search|plan|validate|cost|render
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False,
                                                 server_default=func.now())


class LLMUsageBudget(Base):
    __tablename__ = "llm_usage_budget"
    bucket: Mapped[str] = mapped_column(Text, primary_key=True)
    tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
