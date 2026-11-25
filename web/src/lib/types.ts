// The shapes the session screen reads, as the backend's response models define them
// (backend/src/kako/api/sessions.py, agents/shown.py, api/household.py, api/proposals.py).
// Keep the two in step.

export type Person = {
  id: string;
  display_name: string;
  role: "adult" | "child" | string;
};

export type Household = {
  id: string;
  name: string;
  currency: string;
  as_of_date: string; // YYYY-MM-DD
  people: Person[];
};

export type SessionSummary = {
  id: string;
  title: string;
  household_date: string; // YYYY-MM-DD: the household's date in the session
  started_at: string;
  ended_at: string | null;
  turns: number;
  last_at: string;
};

export type Allocation = {
  entity: string; // a stable ref, such as debt:credit-card
  name: string;
  centavos: number;
  shown: string; // ₱4,000.00
  spec: string;
};

export type Source = {
  kind: "figure" | "fact" | "decision" | "memory" | "knowledge" | "conversation" | string;
  ref: string;
  shown: string;
};

export type Option = {
  label: string;
  summary: string;
  what_if: string;
  recommended: boolean;
  allocations: Allocation[];
  sources: Source[];
  specialists: string[];
  recommendation_ids: string[];
};

export type Resolution = {
  conflicts: string[];
  described: string[];
  together: string;
  splits: string[]; // "<what-if>: fits" or "<what-if>: refused"
  chosen: string | null;
  rejected: string | null;
  reason: string;
  reconciliation_ids: string[];
};

export type Flagged = { text: string; where: string };

export type SpecialistProposal = {
  specialist: string;
  what_if: string | null;
  summary: string;
};

export type Change = { proposal_id: string; kind: string; shown: string };

export type Replan = {
  since: string;
  what_changed: string[];
  why: string | null;
  because: string[];
  before_run_id: string | null;
  revisit_decision_ids: string[];
};

export type TurnAnswer = {
  session_id: string;
  seed: string;
  reply: string;
  options: Option[];
  recommended: string | null;
  resolution: Resolution | null;
  flagged: Flagged[];
  proposals: SpecialistProposal[];
  changes: Change[];
  not_proposed: string[];
  replan: Replan | null;
  plan: { id: string; version: number; status: string } | null;
  calc_run_id: string | null;
  meko: {
    conversation_id: string | null;
    message_id: string | null;
    error: string | null;
    trace_url: string | null;
  };
  cost: {
    model_calls: number;
    input_tokens: number;
    output_tokens: number;
    usd: string;
    brief_tokens?: number | null; // the brief's size, kept on turns since Nov 25
    brief_budget?: number | null;
  };
};

export type Step = {
  seq: number;
  agent: string;
  tool: string;
  input_summary: string;
  result_summary: string;
  outcome: "ok" | "rejected" | "error" | string;
  at: string;
};

export type KeptTurn = {
  seed: string;
  said_by: { id: string; display_name: string } | null;
  message: string;
  at: string;
  answer: TurnAnswer;
  steps: Step[];
};

export type RunningTurn = {
  seed: string;
  said_by: string | null;
  message: string;
  started_at: string;
  steps: Step[];
};

export type SessionTurns = {
  session: SessionSummary;
  turns: KeptTurn[];
  running: RunningTurn | null;
};

export type ProposalChange = {
  subject: string;
  attribute: string;
  before: string | null;
  after: string | null;
  from_day: string | null;
};

export type Proposal = {
  id: string;
  kind: string;
  status: "pending" | "approved" | "rejected" | "expired" | string;
  shown: string;
  change: ProposalChange | null;
  explanation: string;
  payload: Record<string, unknown>;
  from_dreaming: boolean;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  evidence: { kind: string; ref: string; quote: string; said_by: string | null }[];
  written: { table: string; id: string }[];
};

// The plan screen (backend/src/kako/api/plans.py).

export type PlanSummary = {
  id: string;
  version: number;
  status: "proposed" | "accepted" | "replaced" | string;
  session_id: string;
  session_title: string;
  created_at: string;
  as_of: string; // YYYY-MM-DD: the household's date the plan is for
  recommended_option: string | null;
  options: number;
};

export type FigureWhy = {
  id: string;
  title: string;
  value: string;
  flag: string | null;
  formula: string; // F-DEBT-2
  formula_words: string;
  what_if: string | null; // the option's amounts, when the figure comes from its what-if
  facts: string[];
  inputs: string[]; // the figures it was built from
};

export type FactWhy = {
  id: string;
  title: string;
  value: string;
  valid_from: string;
  valid_to: string | null;
  status: string;
  source: string; // where it came from and who approved it, in words
  shared: string | null; // when it was shared with every agent in Meko
  replaced: string | null; // the value it replaced
};

export type DecisionWhy = {
  id: string;
  question: string;
  chosen: string;
  reasoning: string;
  session_title: string;
  on: string;
  status: string;
  rejected: { label: string; reason: string }[];
};

export type MemoryWhy = {
  kind: "memory" | "knowledge" | string;
  source_id: string;
  quote: string | null;
  fact_id: string | null; // the fact the memory is kept for, if any
};

export type Words = { quote: string; said_by: string | null };

export type PlanAllocation = {
  recommendation_id: string;
  entity_id: string | null;
  name: string;
  area: string;
  specialist: string;
  centavos: number | null;
  shown: string;
};

export type CheckedNumber = { text: string; matched: string | null };

export type Check = {
  text: string;
  result: "pass" | "fail" | string; // fail: a number matched nothing, and it was flagged
  numbers: CheckedNumber[];
};

export type PlanOption = {
  label: string;
  recommended: boolean;
  summary: string;
  specialists: string[];
  allocations: PlanAllocation[];
  why: {
    figures: string[];
    facts: string[];
    decisions: DecisionWhy[];
    memories: MemoryWhy[];
    words: Words[];
  };
  checks: Check[];
};

export type Reconciliation = {
  kind: string;
  specialists: string[];
  resolution: string;
  rejected: string | null;
  attempts: number;
};

export type MekoCall = {
  tool: string;
  agent_id: string;
  ms: number | null;
  results: number | null;
  outcome: string;
  at: string;
};

export type PlanTurn = {
  session_id: string;
  seed: string | null;
  message: string | null;
  said_by: string | null;
  kept_at: string | null;
  in_meko: boolean;
  trace_url: string | null;
  meko_calls: MekoCall[];
};

export type ChangedFact = {
  label: string; // replaced, corrected, the plan's amount, new, ended
  title: string;
  before: string | null;
  after: string | null;
  from_day: string | null;
};

export type Revisit = {
  decision_id: string;
  question: string;
  chosen: string;
  session_title: string;
  decided_on: string;
  because: ChangedFact[];
};

export type PlanChanged = {
  since: string;
  since_plan: string | null;
  figures: { title: string; before: string; after: string; headline: boolean }[];
  facts: ChangedFact[];
  revisit: Revisit[];
};

export type Plan = {
  plan: PlanSummary;
  summary: string;
  options: PlanOption[];
  reconciliations: Reconciliation[];
  turn: PlanTurn;
  changed: PlanChanged | null;
  figures: Record<string, FigureWhy>;
  facts: Record<string, FactWhy>;
};

// --- The timeline and decisions screens (api/history.py) -----------------------------------

export type EventKind =
  | "start"
  | "life_event"
  | "correction"
  | "decision"
  | "change"
  | "plan"
  | "session";

/** One thing that happened, on the day it took effect. */
export type TimelineEvent = {
  kind: EventKind | string;
  on: string;
  ahead: boolean; // after the household's date: told now, true from then
  title: string;
  detail: string | null;
  source: string | null; // who told it and who approved it, in words
  changes: ChangedFact[];
  ref: string | null; // the decision, plan or session it opens
  revisit: boolean; // a decision whose facts have moved since
  by: string | null; // who approved it, or for a decision who decided
};

export type ValueState = "current" | "coming" | "past" | "corrected";

export type ValueAt = {
  id: string;
  value: string;
  valid_from: string;
  valid_to: string | null; // the first day it no longer holds
  state: ValueState | string;
  source: string;
  shared_on: string | null; // the day it was shared with every agent in Meko
  reason: string | null; // why it was corrected
};

export type AttributeHistory = {
  attribute: string;
  words: string;
  values: ValueAt[]; // newest first
};

export type Thing = {
  id: string | null; // null: the household itself
  name: string;
  kind: string; // household, income, expense, debt, account, goal
  opened_on: string | null;
  closed_on: string | null;
  attributes: AttributeHistory[];
};

export type Timeline = {
  as_of: string;
  events: TimelineEvent[]; // newest first
  things: Thing[];
};

export type DecisionOption = {
  label: string;
  chosen: boolean;
  reason: string | null; // why it wasn't chosen
  leans: string[]; // "keeps cash on hand", "pays debt off faster"
};

export type RestsOn = {
  title: string; // "Mara's salary (take-home pay a month)"
  thing: string; // "Mara's salary", or "The household" for its own rules
  kind: string; // income, expense, debt, account, goal, household
  words: string; // what the value is: "take-home pay a month"
  value: string;
  valid_from: string;
  moved: boolean; // replaced or corrected since
};

export type Decision = {
  id: string;
  question: string;
  chosen: string;
  reasoning: string;
  quote: string | null; // the household's words when they chose
  said_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  session_id: string;
  session_title: string;
  on: string;
  status: "active" | "revised" | "reversed" | string;
  valid_to: string | null;
  replaced_by: string | null;
  outcome: string | null;
  plan_id: string | null;
  options: DecisionOption[]; // the chosen one first
  rests_on: RestsOn[];
  revisit: ChangedFact[]; // what moved under it since; empty when nothing did
};

export type Decisions = { as_of: string; decisions: Decision[] };

// GET /api/v1/metrics (api/metrics.py): every figure worked out in the backend; decimals as strings.
export type MetricsGroup = "household" | "specialists" | "single";

export type Spread = {
  average: string;
  worst: string;
  worst_session_id: string;
  worst_seed: string;
  worst_title: string;
};

export type NumberChecks = {
  texts: number;
  passed: number;
  failed: number;
  regenerated: number;
  pass_pct: string | null;
};

export type TurnGroup = {
  group: MetricsGroup;
  turns: number;
  replayed: number;
  model_calls: Spread | null;
  tokens: Spread | null;
  cached_pct: string | null;
  cost_usd: Spread | null;
  seconds: Spread | null;
  brief_tokens: Spread | null;
  brief_turns: number;
  checks: NumberChecks;
};

export type TestSetRun = {
  architecture: string;
  mode: string;
  run_at: string;
  deployments: Record<string, string>;
  questions: number;
  answered: number;
  score_pct: string;
  checks_passed: number;
  checks_total: number;
  model_calls: number;
  tokens: number;
  cost_usd: string;
  meko_calls: number;
};

export type EffectSide = {
  run_at: string;
  mode: string;
  model_calls: number;
  cost_usd: string;
  score_pct: string;
  behaviour_pct: string;
};

export type EffectQuestion = {
  id: string;
  message: string | null;
  score_with_pct: string;
  score_without_pct: string;
  behaviour_with_pct: string;
  behaviour_without_pct: string;
  cited_with: boolean | null;
  cited_without: boolean | null;
};

export type Metrics = {
  measured_at: string;
  brief_budget: number;
  turns: TurnGroup[];
  test_set: { specialists: TestSetRun | null; single: TestSetRun | null; error: string | null };
  preference: {
    measured: boolean;
    preference: string | null;
    with_side: EffectSide | null;
    without_side: EffectSide | null;
    questions: EffectQuestion[];
    error: string | null;
  };
  dreaming: {
    runs_done: number;
    runs_failed: number;
    runs_waiting: number;
    proposals: number;
    eval_at: string | null;
    eval_mode: string | null;
    expected: number | null;
    found: number | null;
    score_pct: string | null;
    wrong: number | null;
    unquoted: number | null;
    passed: boolean | null;
    error: string | null;
  };
  gaps: {
    total: number;
    by_status: Record<string, number>;
    replayed: number;
    improved: number;
    gaps: {
      query: string;
      band_before: string;
      score_before: string;
      status: string;
      verify_outcome: string | null;
      score_after: string | null;
    }[];
  };
  meko_calls: {
    target: "local" | "cloud";
    allowances: {
      name: string;
      tools: string[];
      free: number;
      local_used: number;
      cloud_used: number;
      cloud_ceiling: number;
      cloud_left: number;
    }[];
  };
};

// GET /api/v1/metrics/meko: Meko's own datapack_metrics, read live.
export type DatapackMetrics = {
  target: "local" | "cloud";
  datapack_id: string | null;
  datapack_name: string | null;
  days: number;
  searches: number;
  context_tokens: number;
  knowledge: { count: number; tokens: number };
  memories: { count: number; tokens: number };
  conversations: { count: number; tokens: number };
  tokens_sent: number | null;
  tokens_saved: number | null;
  saved_pct: number | null;
  relevance_high: number | null;
  relevance_mid: number | null;
  relevance_low: number | null;
  relevant_pct: number | null;
  brief_tokens: string | null;
  brief_pct_of_context: string | null;
};

// GET /api/v1/money: where the household's money stands on its date (api/money.py).
export type MoneyTile = { label: string; value: string; negative: boolean };

export type SplitPart = {
  key: "needs" | "wants" | "debt" | "savings" | "unplanned";
  label: string;
  amount: number; // centavos, for the chart
  text: string;
  share: string;
};

export type PlanLineKind = "in" | "need" | "want" | "debt" | "savings";

export type PlanLine = {
  kind: PlanLineKind;
  name: string;
  amount: string | null;
  left: string | null;
  fill: number; // what is left after it, as a share of the pay
  change: string | null; // "was ₱4,000.00", "new"
};

export type PlanVersion = {
  label: string;
  on: string;
  lines: PlanLine[];
  unplanned: string | null;
};

export type ScheduleRow = {
  month: number;
  on: string;
  owed: string;
  interest: string;
  payment: string;
  principal: string;
  left: string;
  fill: number; // what is left as a share of today's balance
  rolled_in: string | null;
  rolled_from: string | null;
};

export type MoneyDebt = {
  id: string;
  name: string;
  order: number | null;
  balance: string;
  since: string | null;
  rate: string | null;
  minimum: string | null;
  extra: string | null;
  paying: string | null;
  payoff_on: string | null;
  payoff_in: string | null;
  interest_left: string | null;
  why_not: string | null;
  rows: ScheduleRow[];
  paid_total: string | null;
  interest_total: string | null;
  principal_total: string | null;
};

export type Holding = { name: string; kind: string; amount: string | null; since: string | null };

export type MoneyMilestone = {
  kind: "emergency_fund" | "debt_paid" | "goal_reached";
  on: string;
  within: string;
  name: string;
  on_track: boolean | null;
};

export type MoneyMoment = {
  kind: "thirteenth_month" | "ahead";
  on: string;
  month_only: boolean;
  title: string;
  value: string;
};

export type Money = {
  as_of: string;
  tiles: MoneyTile[];
  split: { total: string; parts: SplitPart[]; over: string | null } | null;
  plan: PlanVersion;
  before: PlanVersion | null;
  debts: MoneyDebt[];
  standing: {
    owns: Holding[];
    owes: Holding[];
    owned: string | null;
    owed: string | null;
    net: string | null;
    negative: boolean;
  };
  milestones: MoneyMilestone[];
  moments: MoneyMoment[];
  decisions: {
    id: string;
    question: string;
    chosen: string;
    on: string;
    session_title: string;
    revisit: number;
  }[];
};

// --- Before and after a plan's options (api/plans.py, GET /plans/{id}/compare) -------------------

export type Direction = "better" | "worse" | "same" | "none";

export type CompareCell = {
  value: string; // "Aug 15, 2030", "₱111,635.47", "never"
  note: string | null; // "in 47 months", or why there is no value
  change: string | null; // against today's plan: "38 months sooner", "₱99,175.37 less"
  direction: Direction;
};

export type CompareRow = {
  key: string;
  kind:
    | "debt_paid"
    | "debt_interest"
    | "interest_total"
    | "emergency_fund"
    | "goal_reached"
    | "unplanned";
  label: string;
  on_card: boolean;
  before: CompareCell;
  options: CompareCell[]; // in the order of the plan's options
};

export type CompareMonthRow = {
  month: number;
  on: string;
  payment: string;
  interest: string;
  principal: string;
  left: string;
  fill: number;
  before_left: string | null;
  before_fill: number | null;
  rolled_in: string | null;
  rolled_from: string | null;
};

export type CompareDebt = {
  name: string;
  paid_off: string | null;
  change: string | null;
  direction: Direction;
  rows: CompareMonthRow[];
  paid_total: string;
  interest_total: string;
  principal_total: string;
  closing: string;
  before_closing: string | null;
};

export type CompareFund = {
  name: string;
  target: string;
  reached_on: string;
  closing: string;
  before_closing: string;
  rows: { month: number; on: string; added: string; balance: string; to_go: string | null; fill: number }[];
};

export type Comparison = {
  plan_id: string;
  as_of: string;
  baseline: string; // today's plan in words
  each_month: string; // what today's plan puts in each month: "the minimums only"
  options: { label: string; each_month: string }[];
  rows: CompareRow[];
  months: { label: string; debts: CompareDebt[]; fund: CompareFund | null }[];
};
