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
