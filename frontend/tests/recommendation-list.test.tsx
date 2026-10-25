import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecommendationList } from "@/features/plan/components/recommendation-list";
import type { Recommendation } from "@/lib/api/types";

const ticket: Recommendation = {
  kind: "ticket", ref_id: "TKT-TYO-010", name_zh: "三鹰之森吉卜力美术馆 · 成人票", city: "东京", day_index: 2,
  reason: "该景点按时段预约入场，需提前锁定", reservation_required: true, lead_time_days: 30, notes: null,
};
const route: Recommendation = {
  kind: "route", ref_id: "RTE-TYO-01", name_zh: "东京·亲子博物馆一日线（上野起）", city: "东京", day_index: null,
  reason: "与「亲子博物馆」偏好匹配", reservation_required: false, lead_time_days: 0, notes: null,
};

describe("RecommendationList", () => {
  it("分组展示门票与备选路线，并标出预约提前量", () => {
    render(<RecommendationList items={[ticket, route]} />);
    expect(screen.getByRole("region", { name: "产品推荐" })).toBeInTheDocument();
    expect(screen.getByText("需提前 30 天预约")).toBeInTheDocument();
    expect(screen.getByText("东京·亲子博物馆一日线（上野起）")).toBeInTheDocument();
  });

  it("没有推荐时不渲染", () => {
    const { container } = render(<RecommendationList items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
