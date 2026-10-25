import type { Recommendation } from "@/lib/api/types";

/** 产品推荐（规则生成）：方案用到的景点对应的门票 / 预约产品 + 备选主题路线。 */
export function RecommendationList({ items }: { items: Recommendation[] }) {
  if (items.length === 0) return null;
  const tickets = items.filter((x) => x.kind === "ticket");
  const routes = items.filter((x) => x.kind === "route");
  return (
    <section className="mt-3 rounded-xl border border-[#dfe7e1] bg-white px-4 py-3" aria-label="产品推荐">
      <h3 className="text-[13px] font-bold text-[#172019]">产品推荐</h3>
      <p className="text-[11px] text-muted">按方案中的景点与客户偏好自动匹配，需预约的门票已同步到待核实清单。</p>
      {tickets.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {tickets.map((x) => (
            <li key={x.ref_id} className="text-xs leading-5">
              <b>{x.name_zh}</b>
              {x.day_index !== null && <span className="text-muted"> · Day {x.day_index}</span>}
              {x.reservation_required && <span className="ml-1 rounded bg-warning-soft px-1.5 text-[10.5px]">需提前 {x.lead_time_days} 天预约</span>}
              <div className="text-muted">{x.reason}{x.notes ? `；${x.notes}` : ""}</div>
            </li>
          ))}
        </ul>
      )}
      {routes.length > 0 && (
        <div className="mt-2 border-t border-[#eef2ef] pt-2">
          <p className="text-[11px] font-semibold text-[#3d4a41]">备选主题路线</p>
          <ul className="mt-1 space-y-1.5">
            {routes.map((x) => (
              <li key={x.ref_id} className="text-xs leading-5"><b>{x.name_zh}</b><div className="text-muted">{x.reason}</div></li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
