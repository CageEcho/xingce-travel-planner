/** 与后端 `backend/app/schemas/` 一一对应的手写类型。Decimal 在 JSON 里是字符串。 */

export type SlotSource = "client_verbatim" | "advisor_input" | "system_inferred";
export type SlotPrimitive = string | number | boolean | string[] | number[] | null;

export interface SlotValue {
  value: SlotPrimitive;
  source: SlotSource;
  confidence: number;
}

export const SLOT_NAMES = [
  "destination_cities", "date_start", "date_end", "duration_days", "adults", "children", "child_ages",
  "budget_amount", "budget_basis", "budget_incl_flight", "hotel_tier", "dietary", "accessibility", "interests", "pace",
] as const;
export type SlotName = (typeof SLOT_NAMES)[number];
export type SlotSet = Partial<Record<SlotName, SlotValue | null>>;

export interface Followup { slot: string; question: string; options: string[] }
export interface Conflict { code: string; slots: string[]; message: string; suggestion: string }

export interface RequirementCardView {
  card_id: string;
  conv_id: string;
  version: number;
  slots: SlotSet;
  completeness: number;
  completeness_threshold: number;
  missing_slots: string[];
  conflicts: Conflict[];
  followups: Followup[];
  confirmed: boolean;
  confirmed_at: string | null;
}

export interface NextStep {
  analysis: string;
  followups: Followup[];
  ready: boolean;
  summary: string;
  source: "llm" | "rules";
}

export interface MessageOut {
  extraction: { slots: SlotSet; followups: Followup[]; notes: string };
  card: RequirementCardView;
  warnings: string[];
  next_step: NextStep | null;
}

export type BackendTaskStatus = "queued" | "searching" | "planning" | "validating" | "costing" | "done" | "failed";
export interface RecoveryPatch { slot: SlotName; value: SlotPrimitive }
export interface RecoveryAction { id: string; label: string; description: string; patches: RecoveryPatch[] }
export interface RecoveryDetails {
  kind: "candidate_recovery";
  problem_slots: SlotName[];
  missing_cities: string[];
  candidate_counts: Record<string, number>;
  actions: RecoveryAction[];
}
export interface ErrorBody { code: string; message: string; details?: RecoveryDetails | Record<string, unknown> | null }
export interface PlanStatus {
  plan_id: string;
  task_id: string;
  status: BackendTaskStatus | string;
  progress: number;
  replan_round: number;
  version: number | null;
  error: ErrorBody | null;
}

export type Verdict = "pass" | "fail" | "unknown";
export interface Violation {
  code: string; verdict: Verdict; day_index: number; item_index: number | null; resource_id: string | null;
  message: string; blocking: boolean; verify_hint: string | null;
}
export interface ChecklistItem { code: string; day_index: number; resource_id: string | null; what_to_verify: string; reason: string }

export interface Provenance {
  resource_id: string; resource_type: string; updated_at: string | null; price_source: string | null; rate_id: string | null;
  matched_slots: string[]; satisfied_constraints: string[]; unknown_constraints: string[];
  source_type?: string | null; verified_status?: string | null; verified_at?: string | null; review_due?: string | null;
}
export type ItemSlot = "morning" | "lunch" | "afternoon" | "dinner" | "evening" | "accommodation" | "transport";
export type ItemType = "hotel" | "restaurant" | "poi" | "vehicle" | "transfer" | "free_time";
export interface RenderedItem {
  slot: ItemSlot; type: ItemType; resource_id: string | null; room_id: string | null; nights: number | null; start_time: string | null;
  name_zh: string | null; name_local: string | null; district: string | null; facts: Record<string, unknown>;
  reason_slots: string[]; reason_note: string; provenance: Provenance | null; status: "ok" | "blocked"; block_reason: string | null;
}
export interface RenderedDay {
  day_index: number; date: string; weekday: number; city: string; theme: string; is_transfer: boolean; items: RenderedItem[]; commute_min_est: number | null;
}
export interface RenderError { day_index: number; item_index: number; kind: string; resource_id: string | null; detail: string }
export interface Recommendation {
  kind: "ticket" | "route"; ref_id: string; name_zh: string; city: string; day_index: number | null; reason: string;
  reservation_required: boolean; lead_time_days: number; notes: string | null;
}
export interface RenderedPlan { days: RenderedDay[]; assumptions: string[]; render_errors: RenderError[]; recommendations?: Recommendation[] }

export type CostCategory = "accommodation" | "transport" | "dining" | "tickets" | "service_fee";
export interface CostLine {
  category: CostCategory; day_index: number | null; resource_id: string; rate_id: string; qty: string; unit_price: string;
  season_uplift: string; amount: string; rule_trace: string;
}
export interface CostSummary {
  lines: CostLine[]; breakdown: Record<string, string>; currency: string; total: string; per_person: string;
  budget_target: string | null; total_cny: string | null; variance_pct: string | null; fx_rate: string; fx_time: string;
  service_fee_rate: string; missing_rates: string[];
}

export interface PlanVersionView {
  plan_id: string; version: number; card_id: string; status: string; structure: RenderedPlan; cost: CostSummary | null; cost_visible: boolean;
  violations: Violation[]; checklist: ChecklistItem[]; blocking_count: number; unknown_count: number; replan_rounds: number;
  created_at: string; synthetic_notice: string;
}

export interface TraceStep {
  trace_id: number; step: string; latency_ms: number | null; input_tokens: number | null; output_tokens: number | null;
  payload: Record<string, unknown> | null; created_at: string;
}
export interface TraceResponse { plan_id: string; task: { status: string; replan_round: number; error_code: string | null }; steps: TraceStep[] }

export interface HotelCandidate {
  hotel_id: string; room_id: string; rate_id: string | null; name_zh: string; name_local: string | null; city: string; district: string | null;
  tier: string; tags: string[]; room_name: string; max_occupancy: number; max_children: number; min_child_age: number | null;
  child_age_unknown: boolean; net_price: string | null; season_uplift: string | null; confidence: string | null; score: number;
}
export interface RelaxationHint { field: string; suggestion: string; would_yield: number }
export interface SearchResult { candidates: HotelCandidate[]; relaxation_hints: RelaxationHint[]; total_before_filter: number | null; funnel: Record<string, number>; cost_visible: boolean }

export interface ConversationSummary {
  conv_id: string; title: string; created_at: string; last_activity_at: string; completeness: number; confirmed: boolean;
  plan_id: string | null; plan_status: string | null;
}
export type UserRole = "sales" | "advisor" | "supervisor" | "procurement" | "admin";
export interface MetaInfo {
  provider: string; model: string; planner_mode: string; llm_configured: boolean; milestone: string;
  auth_enabled: boolean; user_id: string; role: UserRole; cost_visible: boolean;
}
export interface CurrentUser { user_id: string; role: UserRole; cost_visible: boolean }
