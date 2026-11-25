// How the screen names things the data names by key. Presentation only: an unknown key is shown
// as it is. Pure, tested in words.test.ts.

import type { Proposal, Source } from "./types.ts";

// The attribute catalog (docs/data-model.md, "Attribute catalog") in plain words.
const ATTRIBUTES: Record<string, string> = {
  "income.monthly_net": "take-home pay a month",
  "income.thirteenth_month": "13th-month pay",
  "income.pay_day": "pay day",
  "expense.monthly_amount": "spending a month",
  "expense.essential": "essential",
  "debt.balance": "balance",
  "debt.monthly_rate": "interest a month",
  "debt.annual_rate": "interest a year",
  "debt.minimum_payment": "minimum payment",
  "account.balance": "balance",
  "account.liquid": "can be drawn on",
  "account.purpose": "purpose",
  "goal.target_amount": "target",
  "goal.target_date": "target date",
  "goal.saved_amount": "saved so far",
  "goal.priority": "priority",
  "plan.allocation": "set aside a month",
  "household.emergency_months_target": "emergency fund target, in months",
  "preference.debt_strategy": "debt strategy",
  "preference.note": "preference",
  "constraint.note": "constraint",
};

export function attributeWords(key: string): string {
  return ATTRIBUTES[key] ?? key;
}

/** The colour a source carries: violet only for what came from Meko. */
export type Tone = "emerald" | "gold" | "orange" | "rose" | "meko" | "plain";

const SOURCE_KINDS: Record<string, { label: string; tone: Tone }> = {
  figure: { label: "Engine figure", tone: "plain" },
  fact: { label: "Household fact", tone: "emerald" },
  decision: { label: "Past decision", tone: "plain" },
  memory: { label: "Meko memory", tone: "meko" },
  knowledge: { label: "Meko knowledge", tone: "meko" },
  conversation: { label: "Said in the session", tone: "plain" },
  calculation: { label: "Calculated", tone: "plain" },
  history: { label: "Kako's records", tone: "plain" },
  document: { label: "Document", tone: "plain" },
};

export function sourceKind(source: Source): { label: string; tone: Tone } {
  return SOURCE_KINDS[source.kind] ?? { label: source.kind, tone: "plain" };
}

/** What a source chip shows after its kind: the value, the document's name, or nothing for the
 * household's own words (shown elsewhere) and bare refs such as M1. */
export function sourceDetail(source: Source): string | null {
  if (source.kind === "conversation") return null;
  if (source.kind === "document") return source.ref.replace(/^doc:/, "").replace(/-/g, " ");
  const first = source.shown.split("\n")[0].trim();
  if (!first || /^[A-Z]+\d+$/.test(first)) return null;
  return first;
}

// The kinds of answer (backend agents/answers.py ANSWER_KINDS), as "show the working" names them.
const ANSWER_KINDS: Record<string, string> = {
  inform: "General information",
  explain: "Your numbers explained",
  look_up: "Looked up in your records",
  compute: "A sum, worked out",
  simulate: "A what-if, nothing saved",
  advise: "Pros and cons",
  plan: "A plan with options",
  record: "News held for your yes",
  small_talk: "A short reply",
};

export function answerKindWords(kind: string | null | undefined): string | null {
  if (!kind) return null;
  return ANSWER_KINDS[kind] ?? kind.replace(/_/g, " ");
}

/** A proposal's title on the approval card. */
export function proposalTitle(p: Proposal): string {
  if (p.change)
    return `${p.change.subject}: ${attributeWords(p.change.attribute)}`;
  if (p.kind === "life_event") {
    const kind = String(p.payload.kind ?? "life event").replace(/_/g, " ");
    return `Life event: ${kind}`;
  }
  if (p.kind === "decision") return "A decision";
  return p.kind.replace(/_/g, " ");
}

/** A life event's description and day, from its payload; null for other kinds. */
export function lifeEvent(p: Proposal): { description: string; on: string } | null {
  if (p.kind !== "life_event") return null;
  const description = p.payload.description;
  const on = p.payload.occurs_on;
  return typeof description === "string" && typeof on === "string"
    ? { description, on }
    : null;
}

/** Initials for a person's avatar. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 1)).toUpperCase();
}
