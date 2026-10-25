"use client";

import { useState } from "react";
import { ArrowRight, Eye, PencilLine, RefreshCw } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import type { PlanTask } from "../hooks/use-plan-task";
import { ChecklistView } from "./checklist-view";
import { CostView } from "./cost-view";
import { DayCard } from "./day-card";
import { RecommendationList } from "./recommendation-list";
import { TaskProgress } from "./task-progress";
import { TraceView } from "./trace-view";
import { cn } from "@/lib/utils/cn";
import { needsCardFix } from "@/lib/api/problem-slots";
import type { RecoveryAction, RecoveryDetails, RequirementCardView } from "@/lib/api/types";
import { ProposalDialog } from "./proposal-dialog";

export type PlanTab = "plan" | "cost" | "check" | "trace";
const TABS: { value: PlanTab; label: string }[] = [
  { value: "plan", label: "方案" }, { value: "cost", label: "成本" }, { value: "check", label: "待核实清单" }, { value: "trace", label: "检索过程" },
];

export function PlanPanel({ task, card, hasPlanId, tab, onTab, onRegenerate, onFixCard, onRecover, recovering, canRegenerate, className }: {
  task: PlanTask; hasPlanId: boolean; tab: PlanTab; onTab: (t: PlanTab) => void; onRegenerate: () => void;
  card: RequirementCardView | null;
  /** 回到需求卡并定位到有问题的槽位 */
  onFixCard: () => void; onRecover: (action: RecoveryAction) => void; recovering: boolean; canRegenerate: boolean; className?: string;
}) {
  const { view, plan, trace, loading, error, disconnected } = task;
  const [proposalOpen, setProposalOpen] = useState(false);
  const counts = plan ? { check: plan.checklist.length } : {};
  return (
    <Card className={cn("flex flex-col min-h-0", className)}>
      <Tabs ariaLabel="方案面板" value={tab} onChange={onTab}
        items={TABS.filter((t) => t.value !== "cost" || !plan || plan.cost_visible)
          .map((t) => ({ ...t, count: t.value === "check" ? counts.check : undefined }))} />
      <div key={tab} className="flex-1 min-h-0 overflow-auto p-4 fade-enter">
        {!hasPlanId && <p className="text-sm text-muted">确认需求卡并生成后，这里显示按天行程、成本结构与待核实清单。悬停 ⓘ 查看每个条目的溯源。</p>}
        {hasPlanId && loading && <div className="space-y-3" aria-busy="true"><Skeleton className="h-10 w-full" /><Skeleton className="h-32 w-full" /><Skeleton className="h-32 w-full" /></div>}
        {error && <Alert tone="danger">{error.userMessage}</Alert>}
        {disconnected && (
          <Alert tone="warning" className="mb-3" action={<Button size="sm" variant="secondary" onClick={task.refresh}><RefreshCw className="size-3" aria-hidden="true" />重试</Button>}>
            与服务端的连接中断。任务未必已停止，正在自动重连。
          </Alert>
        )}
        {view && view.state !== "succeeded" && view.state !== "failed" && <TaskProgress view={view} />}
        {view?.state === "failed" && view.errorCode === "CANDIDATES_TOO_FEW" && view.errorDetails ? (
          <RecoveryPanel details={view.errorDetails} message={view.errorMessage ?? "当前条件没有足够候选资源"}
            onRecover={onRecover} onManual={onFixCard} loading={recovering} />
        ) : view?.state === "failed" && (
          <Alert tone="danger" className="mb-3"
            action={needsCardFix(view.errorCode)
              ? <Button size="sm" onClick={onFixCard}>回到需求卡修改</Button>
              : canRegenerate ? <Button size="sm" onClick={onRegenerate}>重新生成</Button> : undefined}>
            <b>{view.headline}</b>
            <div className="text-xs">{needsCardFix(view.errorCode) ? "条件不改，重试结果不会变。请调整出发日期、酒店档次或目的地后再生成" : `${view.action} · ${view.next}`}</div>
          </Alert>
        )}
        {plan && view?.state === "succeeded" && (
          <>
            <section className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-[#dfe7e1] bg-[#f5faf6] px-4 py-3">
              <div className="min-w-0 flex-1">
                <b className="block text-[13px] text-[#172019]">客户交付版本已就绪</b>
                <span className="text-[11px] leading-5 text-[#66716a]">图文排版会隐藏内部成本轨迹、资源 ID 与模型信息，可导出 PDF 或长图。</span>
              </div>
              <Button size="sm" onClick={() => setProposalOpen(true)} disabled={plan.blocking_count > 0}>
                <Eye className="size-3.5" />客户版预览与导出
              </Button>
              {plan.blocking_count > 0 && <span className="w-full text-[11px] text-danger">存在硬约束违规，修正后才能导出客户版本。</span>}
            </section>
            <Alert tone={plan.blocking_count > 0 ? "danger" : "success"} className="mb-3">
              {plan.blocking_count > 0
                ? <>硬约束 <b>{plan.blocking_count}</b> 项违反，已回退重排 {plan.replan_rounds} 轮仍未消除，需人工处理 · 待核实 {plan.unknown_count} 项</>
                : <>硬约束 <b>0</b> 项违反 · 待核实 {plan.unknown_count} 项 · 回退重排 {plan.replan_rounds} 轮</>}
            </Alert>
            {tab === "plan" && (
              <>
                {plan.structure.assumptions.length > 0 && <p className="mb-3 rounded border-l-[3px] border-warning bg-warning-soft px-3 py-2 text-xs"><b>编排假设：</b>{plan.structure.assumptions.join("；")}</p>}
                {plan.structure.days.map((d) => <DayCard key={d.day_index} day={d} blocking={plan.violations.filter((v) => v.blocking && v.day_index === d.day_index)} />)}
                <RecommendationList items={plan.structure.recommendations ?? []} />
                <p className="text-[11px] text-muted mt-2">{plan.synthetic_notice}</p>
              </>
            )}
            {tab === "cost" && (plan.cost ? <CostView cost={plan.cost} /> : <Alert tone="warning">当前账号没有查看净价与成本明细的权限。</Alert>)}
            {tab === "check" && <ChecklistView items={plan.checklist} />}
            {tab === "trace" && <TraceView trace={trace} />}
          </>
        )}
      </div>
      {plan && <ProposalDialog open={proposalOpen} onClose={() => setProposalOpen(false)} plan={plan} card={card} />}
    </Card>
  );
}

function RecoveryPanel({ details, message, onRecover, onManual, loading }: {
  details: RecoveryDetails;
  message: string;
  onRecover: (action: RecoveryAction) => void;
  onManual: () => void;
  loading: boolean;
}) {
  const counts = Object.entries(details.candidate_counts).map(([city, count]) => `${city} ${count} 家`).join(" · ");
  return (
    <section className="mb-3 rounded-xl border border-[#efc9c9] bg-[#fff7f7] p-4" role="alert">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-[#fbe3e3] text-[13px] font-bold text-danger">!</span>
        <div className="min-w-0">
          <h3 className="text-[14px] font-bold text-[#8f2929]">当前条件需要调整后才能继续</h3>
          <p className="mt-1 text-[12px] leading-5 text-[#9a4b4b]">{message}</p>
          {counts && <p className="mt-1 text-[11px] text-[#a56a6a]">本次酒店候选：{counts}</p>}
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {details.actions.map((action, index) => (
          <button key={action.id} type="button" onClick={() => onRecover(action)} disabled={loading}
            className={cn("group rounded-xl border px-3 py-2.5 text-left transition disabled:cursor-wait disabled:opacity-55",
              index === 0 ? "border-primary bg-primary text-white hover:bg-primary-hover" : "border-[#e5d8d8] bg-white hover:border-primary/40 hover:bg-primary-soft")}>
            <span className="flex items-center justify-between gap-2 text-[12px] font-bold">{action.label}<ArrowRight className="size-3.5 shrink-0 transition-transform group-hover:translate-x-0.5" /></span>
            <span className={cn("mt-1 block text-[10.5px] leading-4", index === 0 ? "text-white/72" : "text-muted")}>{action.description}</span>
          </button>
        ))}
      </div>
      <button type="button" onClick={onManual} disabled={loading} className="mt-3 inline-flex min-h-8 items-center gap-1.5 text-[11px] font-semibold text-[#7a4d4d] underline underline-offset-4">
        <PencilLine className="size-3.5" />手动修改需求卡
      </button>
      <p className="mt-2 text-[10.5px] text-[#a16a6a]">选择建议后，系统会自动更新需求卡并重新生成，不需要重复填写其它信息。</p>
    </section>
  );
}
