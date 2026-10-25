"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import type { RenderedItem } from "@/lib/api/types";
import { SLOT_LABEL, shortTime } from "@/lib/utils/format";
import type { SlotName } from "@/lib/api/types";

const GAP = 8;
const MARGIN = 12;
const SOURCE_LABEL: Record<string, string> = {
  supplier_contract: "供应商合同/报价单", official_site: "官方网站/公告", advisor_visit: "顾问实地踩线",
  ota_reference: "OTA 公开信息（参考）", historical_order: "历史订单回填",
};

function sourceLine(p: NonNullable<RenderedItem["provenance"]>): string {
  const source = p.source_type ? SOURCE_LABEL[p.source_type] ?? p.source_type : "未标注";
  if (p.verified_status === "pending") return `${source} · 待人工校验（截止 ${p.review_due ?? "—"}）`;
  if (p.verified_status === "verified") return `${source} · 已校验 ${p.verified_at ?? ""}，下次复核 ${p.review_due ?? "—"}`;
  return source;
}

/** ⓘ 溯源：resource_id / 更新时间 / 命中需求 / 满足约束 / 价格来源 / 事实字段。悬停或聚焦显示。
 *  浮层经 Portal 挂到 body 并 fixed 定位，避免被方案面板的滚动容器（overflow）裁切；下方放不下时翻到上方。 */
export function ProvenancePopover({ item }: { item: RenderedItem }) {
  const p = item.provenance;
  const tipId = useId();
  const anchorRef = useRef<HTMLButtonElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState(false);
  const [focus, setFocus] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const open = hover || focus;

  const place = useCallback(() => {
    const a = anchorRef.current?.getBoundingClientRect();
    const t = tipRef.current;
    if (!a || !t) return;
    const w = t.offsetWidth;
    const h = t.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const below = a.bottom + GAP;
    const above = a.top - GAP - h;
    const top = below + h <= vh - MARGIN || above < MARGIN ? below : above;
    const left = Math.max(MARGIN, Math.min(a.right - w, vw - w - MARGIN));
    setPos({ top: Math.max(MARGIN, Math.min(top, vh - h - MARGIN)), left });
  }, []);

  useLayoutEffect(() => {
    if (open) place();
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    const observer = new ResizeObserver(place);
    if (tipRef.current) observer.observe(tipRef.current);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      observer.disconnect();
    };
  }, [open, place]);

  if (!p) return null;
  const facts = Object.entries(item.facts ?? {}).map(([k, v]) => `${k}=${v === null ? "未记录" : JSON.stringify(v)}`).join("，");
  return (
    <span className="inline-block" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button ref={anchorRef} type="button" aria-label={`查看 ${item.name_zh ?? p.resource_id} 的溯源信息`}
        aria-describedby={open ? tipId : undefined}
        onFocus={() => setFocus(true)} onBlur={() => setFocus(false)}
        onKeyDown={(e) => { if (e.key === "Escape") { setHover(false); anchorRef.current?.blur(); } }}
        className="inline-flex size-7 items-center justify-center rounded-full text-info hover:bg-info-soft focus:bg-info-soft">
        <Info className="size-4" aria-hidden="true" />
      </button>
      {open && createPortal(
        <div ref={tipRef} id={tipId} role="tooltip"
          style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden" }}
          className="pointer-events-none fixed z-50 w-[340px] max-w-[calc(100vw-24px)] rounded-2xl bg-ink text-white/90 p-3.5 shadow-(--shadow-float) text-xs leading-5 shadow-xl whitespace-pre-wrap wrap-anywhere text-left">
          <div>资源 ID：<code>{p.resource_id}</code>{item.room_id && <> · 房型 <code>{item.room_id}</code></>}</div>
          <div>数据更新时间：{shortTime(p.updated_at)}</div>
          <div>命中需求：{p.matched_slots.length ? p.matched_slots.map((s) => SLOT_LABEL[s as SlotName] ?? s).join("、") : "—"}</div>
          <div>满足约束：{p.satisfied_constraints.join(" ") || "—"}</div>
          <div>待核实约束：{p.unknown_constraints.join(" ") || "无"}</div>
          <div>价格来源：{p.price_source ?? "—"}{p.rate_id && ` (${p.rate_id})`}</div>
          <div>资料来源：{sourceLine(p)}</div>
          <div className="mt-1 text-white/60">事实字段：{facts || "—"}</div>
        </div>,
        document.body,
      )}
    </span>
  );
}
