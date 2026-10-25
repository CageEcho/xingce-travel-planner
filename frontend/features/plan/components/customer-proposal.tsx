import Image from "next/image";
import { BedDouble, CalendarDays, CarFront, Check, Clock3, Coffee, FileCheck2, MapPin, Sparkles, Utensils, UsersRound, type LucideIcon } from "lucide-react";
import type { ItemSlot, PlanVersionView, RenderedDay, RenderedItem, RequirementCardView, SlotPrimitive } from "@/lib/api/types";
import { ITEM_SLOT_LABEL, WEEKDAY, money } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";

const ITEM_ICONS: Record<ItemSlot, LucideIcon> = {
  morning: Coffee,
  lunch: Utensils,
  afternoon: MapPin,
  dinner: Utensils,
  evening: MapPin,
  accommodation: BedDouble,
  transport: CarFront,
};

export function CustomerProposal({ plan, card }: { plan: PlanVersionView; card: RequirementCardView | null }) {
  const days = plan.structure.days;
  const cities = unique(days.map((day) => day.city).filter(Boolean));
  const first = days[0];
  const last = days.at(-1);
  const adults = numberSlot(card, "adults");
  const children = numberSlot(card, "children");
  const people = [adults ? `${adults} 位成人` : "", children ? `${children} 位儿童` : ""].filter(Boolean).join(" · ") || "专属出行人";
  const duration = days.length ? `${days.length} 天${Math.max(days.length - 1, 0)}晚` : "定制行程";
  const title = `${cities.join(" · ") || "日本"}定制旅行方案`;
  const reference = `BDT-${first?.date?.replaceAll("-", "") || "JOURNEY"}-${String(plan.version).padStart(2, "0")}`;
  const confirmations = clientChecklist(plan);

  return (
    <div data-proposal-document className="flex w-[794px] flex-col gap-6 bg-[#eef0f3] text-[#17202a]">
      <ProposalPage className="relative overflow-hidden p-0">
        <div className="relative h-[525px] overflow-hidden">
          <Image src="/images/hero.webp" alt="定制旅程封面" fill priority sizes="794px" className="object-cover" />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(8,15,14,.12),rgba(8,15,14,.76))]" />
          <div className="absolute inset-x-0 top-0 flex items-center justify-between px-12 py-9 text-white">
            <Brand light />
            <span className="text-[10px] font-semibold tracking-[0.22em] text-white/75">PRIVATE JOURNEY PROPOSAL</span>
          </div>
          <div className="absolute inset-x-12 bottom-12 text-white">
            <p className="mb-4 text-[12px] font-semibold tracking-[0.2em] text-[#8df59b]">BEYOND THE ORDINARY</p>
            <h1 className="max-w-[650px] text-[42px] font-semibold leading-[1.18] tracking-[-0.035em]">{title}</h1>
            <p className="mt-4 text-[15px] text-white/78">为你精心设计的专属旅程 · Proposal v{plan.version}</p>
          </div>
        </div>
        <div className="px-12 py-11">
          <div className="grid grid-cols-3 divide-x divide-[#e5e8eb] rounded-xl border border-[#e5e8eb] bg-[#fafbfc] py-5">
            <CoverFact icon={CalendarDays} label="出行日期" value={first && last ? `${first.date} — ${last.date}` : "待确认"} />
            <CoverFact icon={MapPin} label="目的地" value={cities.join(" · ") || "待确认"} />
            <CoverFact icon={UsersRound} label="旅程成员" value={people} />
          </div>
          <div className="mt-9 grid grid-cols-[1fr_210px] gap-10">
            <div>
              <p className="text-[11px] font-bold tracking-[0.18em] text-[#2a9b45]">JOURNEY OVERVIEW</p>
              <h2 className="mt-3 text-[27px] font-semibold tracking-[-0.025em]">一段从容、可靠且值得期待的旅程</h2>
              <p className="mt-4 text-[13px] leading-7 text-[#66707d]">我们根据你的出行成员、节奏与住宿偏好，从在地资源中完成筛选与校验。以下行程保留适度弹性，并将在预订前由旅行顾问完成最终确认。</p>
            </div>
            <div className="rounded-xl bg-[#122018] p-6 text-white">
              <span className="text-[11px] text-white/60">行程长度</span>
              <strong className="mt-2 block text-[30px] font-semibold">{duration}</strong>
              <span className="mt-5 block text-[11px] text-white/60">行程编号</span>
              <code className="mt-1 block text-[11px] text-[#8df59b]">{reference}</code>
            </div>
          </div>
        </div>
        <ProposalFooter page="01" notice={plan.synthetic_notice} />
      </ProposalPage>

      {days.map((day, index) => <DayProposalPage key={day.day_index} day={day} page={String(index + 2).padStart(2, "0")} notice={plan.synthetic_notice} />)}

      <ProposalPage>
        <ProposalHeader eyebrow="YOUR JOURNEY" title="报价与预订说明" />
        <div className="mt-8 grid grid-cols-[1.08fr_.92fr] gap-7">
          <section className="rounded-2xl bg-[#142119] p-8 text-white">
            <p className="text-[11px] font-semibold tracking-[0.16em] text-[#8df59b]">REFERENCE PRICE</p>
            {plan.cost_visible && plan.cost ? (
              <>
                <p className="mt-5 text-[13px] text-white/65">旅程参考总价（JPY，含服务费）</p>
                <strong className="mt-1 block text-[38px] font-semibold tracking-[-0.035em]">¥{money(plan.cost.total, 0)}</strong>
                <div className="mt-5 border-t border-white/12 pt-5 text-[13px] leading-6 text-white/75">
                  <p>约合人民币 ￥{money(plan.cost.total_cny, 0)}</p>
                  <p>人均参考 ¥{money(plan.cost.per_person, 0)}</p>
                </div>
              </>
            ) : <p className="mt-6 text-[15px] leading-7 text-white/75">价格将由你的旅行顾问单独提供。</p>}
            <p className="mt-7 text-[10px] leading-5 text-white/48">汇率、房态与供应商价格可能随预订时间调整，最终金额以正式确认单为准。</p>
          </section>
          <section className="rounded-2xl border border-[#e5e8eb] p-7">
            <h3 className="text-[17px] font-semibold">本方案包含</h3>
            <div className="mt-4 space-y-3 text-[13px] text-[#596574]">
              {['按天图文行程', '住宿、体验与用车安排', '参考报价与服务费', '预订前人工复核', '行程顾问持续支持'].map((item) => (
                <div key={item} className="flex items-center gap-3"><span className="inline-flex size-6 items-center justify-center rounded-full bg-[#eaf8ed]"><Check className="size-3.5 text-[#239744]" /></span>{item}</div>
              ))}
            </div>
          </section>
        </div>

        <section className="mt-8">
          <div className="flex items-end justify-between border-b border-[#dfe4e8] pb-3">
            <div><p className="text-[10px] font-bold tracking-[0.18em] text-[#2a9b45]">BEFORE BOOKING</p><h3 className="mt-1 text-[22px] font-semibold">预订前确认</h3></div>
            <span className="text-[11px] text-[#87909c]">{confirmations.length} 项待顾问复核</span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {confirmations.map((item, index) => (
              <div key={`${item}-${index}`} className="flex gap-3 rounded-xl bg-[#f6f8f9] p-4 text-[12px] leading-5 text-[#5f6b78]"><FileCheck2 className="mt-0.5 size-4 shrink-0 text-[#293746]" />{item}</div>
            ))}
          </div>
        </section>

        <div className="mt-10 rounded-2xl border border-[#dfe7e1] bg-[#f3f8f4] p-7 text-center">
          <Sparkles className="mx-auto size-5 text-[#2ba44a]" />
          <h3 className="mt-3 text-[20px] font-semibold">期待与你一起完成这段旅程</h3>
          <p className="mt-2 text-[12px] leading-6 text-[#68736d]">请将希望调整的节奏、住宿或体验告诉旅行顾问，我们会在确认资源后提供正式预订版本。</p>
        </div>
        <ProposalFooter page={String(days.length + 2).padStart(2, "0")} notice={plan.synthetic_notice} />
      </ProposalPage>
    </div>
  );
}

function DayProposalPage({ day, page, notice }: { day: RenderedDay; page: string; notice: string }) {
  return (
    <ProposalPage>
      <ProposalHeader eyebrow={`DAY ${String(day.day_index).padStart(2, "0")} · ${day.date} ${WEEKDAY[day.weekday]}`} title={day.theme || `${day.city}精选体验`} aside={day.city} />
      <div className="mt-6 flex items-center gap-5 rounded-xl bg-[#f4f7f5] px-5 py-4 text-[12px] text-[#5e6963]">
        <span className="inline-flex items-center gap-2"><MapPin className="size-4 text-[#2b9947]" />{day.city}{day.is_transfer ? " · 城市转场" : ""}</span>
        <span className="inline-flex items-center gap-2"><Clock3 className="size-4 text-[#2b9947]" />预计通勤 {day.commute_min_est ?? "—"} 分钟</span>
      </div>
      <div className="relative mt-7 pl-[116px]">
        <div className="absolute bottom-5 left-[91px] top-3 w-px bg-[#dfe5e1]" />
        <div className="space-y-4">
          {day.items.filter((item) => item.status === "ok").map((item, index) => <ProposalItem key={`${item.slot}-${item.resource_id}-${index}`} item={item} />)}
        </div>
      </div>
      <ProposalFooter page={page} notice={notice} />
    </ProposalPage>
  );
}

function ProposalItem({ item }: { item: RenderedItem }) {
  const Icon = ITEM_ICONS[item.slot];
  const detail = itemDetail(item);
  return (
    <article className="relative min-h-[84px] rounded-xl border border-[#e7eaed] bg-white px-5 py-4 shadow-[0_5px_18px_rgba(28,39,49,.035)]">
      <div className="absolute -left-[116px] top-4 w-[84px] text-right">
        <p className="text-[11px] font-semibold text-[#5a6674]">{ITEM_SLOT_LABEL[item.slot] ?? item.slot}</p>
        <p className="mt-0.5 text-[10px] tabular-nums text-[#9aa2ac]">{item.start_time || "灵活安排"}</p>
      </div>
      <span className="absolute -left-[36px] top-4 inline-flex size-8 items-center justify-center rounded-full border-4 border-white bg-[#e8f6eb] text-[#289746]"><Icon className="size-3.5" /></span>
      <div className="flex items-start justify-between gap-5">
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold text-[#182028]">{item.type === "free_time" ? "自由活动" : item.name_zh || "待确认安排"}</h3>
          {item.name_local && <p className="mt-0.5 text-[10px] text-[#9a7b57]">{item.name_local}</p>}
          {detail && <p className="mt-2 text-[11px] leading-5 text-[#66717e]">{detail}</p>}
        </div>
        {item.district && <span className="shrink-0 rounded-full bg-[#f3f5f7] px-2.5 py-1 text-[10px] text-[#687482]">{item.district}</span>}
      </div>
      {item.reason_note && <p className="mt-2 border-t border-[#edf0f2] pt-2 text-[11px] leading-5 text-[#738078]">推荐理由：{item.reason_note}</p>}
    </article>
  );
}

function ProposalPage({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section data-proposal-page className={cn("relative h-[1123px] w-[794px] overflow-hidden bg-white px-12 pb-16 pt-10", className)}>{children}</section>;
}

function ProposalHeader({ eyebrow, title, aside }: { eyebrow: string; title: string; aside?: string }) {
  return (
    <header className="flex items-start justify-between border-b border-[#dde2e5] pb-6">
      <div><p className="text-[10px] font-bold tracking-[0.18em] text-[#2a9b45]">{eyebrow}</p><h2 className="mt-2 max-w-[580px] text-[28px] font-semibold leading-tight tracking-[-0.03em]">{title}</h2></div>
      {aside ? <span className="rounded-full bg-[#132019] px-4 py-2 text-[11px] font-semibold text-white">{aside}</span> : <Brand />}
    </header>
  );
}

function ProposalFooter({ page, notice }: { page: string; notice: string }) {
  return (
    <footer className="absolute inset-x-12 bottom-7 flex items-center justify-between border-t border-[#e5e8eb] pt-3 text-[8px] tracking-[0.04em] text-[#9aa2aa]">
      <span>{notice}</span><span>BEYOND DREAM TRAVEL · {page}</span>
    </footer>
  );
}

function Brand({ light = false }: { light?: boolean }) {
  return <div className={cn("flex items-center gap-2.5 text-[13px] font-bold", light ? "text-white" : "text-[#151a20]")}><Image src="/brand/bdt-icon.png" alt="" width={28} height={28} className="brand-icon-clip size-7 object-contain" /><span>BEYOND DREAM TRAVEL</span></div>;
}

function CoverFact({ icon: Icon, label, value }: { icon: typeof CalendarDays; label: string; value: string }) {
  return <div className="px-5"><div className="flex items-center gap-2 text-[10px] font-semibold text-[#8a939f]"><Icon className="size-3.5" />{label}</div><p className="mt-2 text-[12px] font-semibold text-[#25303b]">{value}</p></div>;
}

function itemDetail(item: RenderedItem): string {
  const facts = item.facts ?? {};
  const pieces: string[] = [];
  if (typeof facts.room_name === "string") pieces.push(`房型：${facts.room_name}`);
  if (item.nights) pieces.push(`连住 ${item.nights} 晚`);
  if (typeof facts.cuisine === "string") pieces.push(`餐饮：${facts.cuisine}`);
  if (typeof facts.duration_min === "number") pieces.push(`建议停留约 ${facts.duration_min} 分钟`);
  if (typeof facts.service_hours === "string") pieces.push(`服务时段：${facts.service_hours}`);
  return pieces.join(" · ");
}

function numberSlot(card: RequirementCardView | null, name: "adults" | "children") {
  const value = card?.slots[name]?.value;
  return typeof value === "number" ? value : 0;
}

function unique(values: string[]) { return Array.from(new Set(values)); }

function clientChecklist(plan: PlanVersionView): string[] {
  const fallback = ["核对最终入住人与儿童年龄", "确认房态、价格与取消条款", "确认餐饮禁忌已同步供应商", "出发前复核营业时间与交通情况"];
  if (!plan.checklist.length) return fallback;
  const names = new Map<string, string>();
  for (const day of plan.structure.days) {
    for (const item of day.items) if (item.resource_id && item.name_zh) names.set(item.resource_id, item.name_zh);
  }
  // 需预约的门票排在最前：漏订当天无法入场，客户最需要提前知道
  const ordered = [...plan.checklist].sort((a, b) => Number(b.code === "TKT") - Number(a.code === "TKT"));
  return unique(ordered.slice(0, 6).map((item) => {
    const name = (item.resource_id && names.get(item.resource_id)) || "相关资源";
    if (item.code === "H2") return `确认${name}可提供符合饮食要求的菜单`;
    if (item.code === "H3") return `确认${name}当日营业及预约时间`;
    if (item.code === "H8") return `确认${name}在出行日期可正常预订`;
    if (item.code === "H9") return `确认${name}的无障碍设施与现场协助`;
    if (item.code === "H11") return `确认${name}的最新价格与有效期`;
    if (item.code === "H12") return `确认${name}的最新营业与设施信息`;
    return item.what_to_verify
      .replace(/\b(?:HTL|RST|POI|VEH|RM|RP|RATE)-[A-Z0-9-]+\b/gi, name)
      .replace(/\bno_raw\b/gi, "忌生食")
      .replace(/\s+/g, " ")
      .trim();
  }));
}

// 保留给后续客户称呼/兴趣模块扩展，确保 SlotPrimitive 在本组件边界仍受约束。
export function proposalSlotValue(card: RequirementCardView | null, name: keyof RequirementCardView["slots"]): SlotPrimitive | undefined {
  return card?.slots[name]?.value;
}
