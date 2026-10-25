import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CustomerProposal } from "@/features/plan/components/customer-proposal";
import { proposalFilename } from "@/features/plan/export-proposal";
import type { PlanVersionView, RequirementCardView } from "@/lib/api/types";

const card: RequirementCardView = {
  card_id: "CRD-1",
  conv_id: "CNV-1",
  version: 3,
  completeness: 1,
  completeness_threshold: 0.85,
  missing_slots: [],
  conflicts: [],
  followups: [],
  confirmed: true,
  confirmed_at: "2026-09-10T00:00:00Z",
  slots: {
    adults: { value: 2, source: "client_verbatim", confidence: 1 },
    children: { value: 1, source: "client_verbatim", confidence: 1 },
  },
};

const plan: PlanVersionView = {
  plan_id: "PLN-secret-internal-id",
  version: 2,
  card_id: "CRD-1",
  status: "draft",
  structure: {
    assumptions: [],
    render_errors: [],
    days: [{
      day_index: 1,
      date: "2026-10-15",
      weekday: 4,
      city: "东京",
      theme: "城市初见",
      is_transfer: false,
      commute_min_est: 35,
      items: [{
        slot: "afternoon",
        type: "poi",
        resource_id: "POI-INTERNAL-001",
        room_id: null,
        nights: null,
        start_time: "14:00",
        name_zh: "根津美术馆",
        name_local: "根津美術館",
        district: "表参道",
        facts: { duration_min: 90 },
        reason_slots: ["interests"],
        reason_note: "安静的艺术与庭园体验",
        provenance: {
          resource_id: "POI-INTERNAL-001",
          resource_type: "poi",
          updated_at: "2026-09-01T00:00:00Z",
          price_source: "contracted",
          rate_id: "RATE-INTERNAL-1",
          matched_slots: ["interests"],
          satisfied_constraints: ["H3"],
          unknown_constraints: [],
        },
        status: "ok",
        block_reason: null,
      }],
    }],
  },
  cost: {
    lines: [],
    breakdown: { tickets: "120000" },
    currency: "JPY",
    total: "120000",
    per_person: "40000",
    budget_target: "150000",
    total_cny: "5760",
    variance_pct: "-0.1",
    fx_rate: "0.048",
    fx_time: "2026-09-10T00:00:00Z",
    service_fee_rate: "0.1",
    missing_rates: [],
  },
  cost_visible: true,
  violations: [],
  checklist: [{
    code: "H11",
    day_index: 1,
    resource_id: "POI-INTERNAL-001",
    what_to_verify: "核对 POI-INTERNAL-001 的价格档 RATE-INTERNAL-1",
    reason: "内部价格档待核实",
  }],
  blocking_count: 0,
  unknown_count: 0,
  replan_rounds: 0,
  created_at: "2026-09-10T00:00:00Z",
  synthetic_notice: "资源数据为模拟数据集，非真实供应商信息。",
};

describe("CustomerProposal", () => {
  it("生成封面、逐日页和报价页，且不泄露资源与价格档 ID", () => {
    const { container } = render(<CustomerProposal plan={plan} card={card} />);
    expect(screen.getByRole("heading", { name: "东京定制旅行方案" })).toBeInTheDocument();
    expect(screen.getByText("2 位成人 · 1 位儿童")).toBeInTheDocument();
    expect(screen.getByText("根津美术馆")).toBeInTheDocument();
    expect(screen.getByText("¥120,000")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-proposal-page]")).toHaveLength(3);
    expect(container).not.toHaveTextContent("POI-INTERNAL-001");
    expect(container).not.toHaveTextContent("RATE-INTERNAL-1");
    expect(container).not.toHaveTextContent("contracted");
  });

  it("没有成本权限时不显示报价数字", () => {
    const restricted = { ...plan, cost: null, cost_visible: false };
    render(<CustomerProposal plan={restricted} card={card} />);
    expect(screen.getByText("价格将由你的旅行顾问单独提供。")).toBeInTheDocument();
    expect(screen.queryByText("¥120,000")).not.toBeInTheDocument();
  });
});

describe("proposalFilename", () => {
  it("需预约的门票排在预订前确认的最前面", () => {
    const many = Array.from({ length: 6 }, (_, i) => ({ ...plan.checklist[0], code: "H11", resource_id: `X-${i}` }));
    const withTicket = { ...plan, checklist: [...many, { code: "TKT", day_index: 1, resource_id: "POI-INTERNAL-001",
      what_to_verify: "至少提前 30 天预约「三鹰之森吉卜力美术馆 · 成人票」", reason: "按时段预约" }] };
    render(<CustomerProposal plan={withTicket} card={card} />);
    expect(screen.getByText("至少提前 30 天预约「三鹰之森吉卜力美术馆 · 成人票」")).toBeInTheDocument();
  });

  it("生成不含空格和非法路径字符的文件名", () => {
    expect(proposalFilename(["东京", "箱根"], "2026-10-15", 2)).toBe("BDT-东京-箱根-2026-10-15-v2");
  });
});
