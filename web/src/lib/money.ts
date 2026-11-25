// The money screen: where the household's money stands. Pure, tested in money.test.ts. Every
// number comes from GET /api/v1/money, written out by the backend; this only lays it out.

import type { MoneyMilestone, MoneyMoment, PlanLine, ScheduleRow } from "./types.ts";

export type MoneyView = "overview" | "plan" | "debts" | "moments" | "worth";

export const MONEY_VIEWS: readonly { id: MoneyView; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "plan", label: "Monthly plan" },
  { id: "debts", label: "Debts" },
  { id: "moments", label: "Big moments" },
  { id: "worth", label: "Net worth" },
];

/** The view in the address (?view=), or the overview. */
export function viewOf(value: string | null): MoneyView {
  return MONEY_VIEWS.some((v) => v.id === value) ? (value as MoneyView) : "overview";
}

export function moneyHref(view: MoneyView): string {
  return view === "overview" ? "/money" : `/money?view=${view}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const FULL_MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** "2027-01-01" as "Jan 2027": a schedule's month. */
export function monthYear(iso: string): string {
  const [year, month] = iso.split("-");
  return `${MONTHS[Number(month) - 1] ?? month} ${year}`;
}

/** When a big moment falls: a day, or a whole month ("December 2026") for 13th-month pay. */
export function momentWhen(moment: Pick<MoneyMoment, "on" | "month_only">, day: (iso: string) => string): string {
  if (!moment.month_only) return day(moment.on);
  const [year, month] = moment.on.split("-");
  return `${FULL_MONTHS[Number(month) - 1] ?? month} ${year}`;
}

/** A line of the month's plan as it reads in the table: money in as it is, money out with a minus. */
export function signedAmount(line: Pick<PlanLine, "kind" | "amount">): string {
  if (line.amount === null) return "unknown";
  return line.kind === "in" ? line.amount : `−${line.amount}`;
}

/** A milestone in words: "Credit card paid off", "Emergency fund at its target". */
export function milestoneTitle(m: Pick<MoneyMilestone, "kind" | "name">): string {
  if (m.kind === "emergency_fund") return "Emergency fund at its target";
  if (m.kind === "debt_paid") return `${m.name} paid off`;
  return `${m.name} reached`;
}

/** How many months of a schedule show before "Show all": a year. */
export const ROWS_SHOWN = 12;

export function rowsShown<T extends Pick<ScheduleRow, "month">>(rows: readonly T[], all: boolean): readonly T[] {
  return all ? rows : rows.slice(0, ROWS_SHOWN);
}

// --- The donut -----------------------------------------------------------------------------------

export type Arc = { key: string; path: string; start: number; end: number };

function point(cx: number, cy: number, r: number, turn: number): [number, number] {
  const angle = turn * 2 * Math.PI - Math.PI / 2; // 0 is twelve o'clock, clockwise
  return [round(cx + r * Math.cos(angle)), round(cy + r * Math.sin(angle))];
}

function round(n: number): number {
  return Math.round(n * 1000) / 1000;
}

/** One ring segment from `start` to `end` (fractions of a turn), outer radius `r`, inner `inner`. */
function segment(cx: number, cy: number, r: number, inner: number, start: number, end: number): string {
  const large = end - start > 0.5 ? 1 : 0;
  const [x0, y0] = point(cx, cy, r, start);
  const [x1, y1] = point(cx, cy, r, end);
  const [x2, y2] = point(cx, cy, inner, end);
  const [x3, y3] = point(cx, cy, inner, start);
  return `M${x0} ${y0}A${r} ${r} 0 ${large} 1 ${x1} ${y1}L${x2} ${y2}A${inner} ${inner} 0 ${large} 0 ${x3} ${y3}Z`;
}

/** The donut's segments, each its part's share of the whole, clockwise from twelve o'clock in the
 * order given. Parts of zero are left out; a single part is a whole ring (two halves, since one arc
 * can't close on itself). */
export function donutArcs(
  parts: readonly { key: string; amount: number }[],
  size = 200,
  thickness = 34,
): Arc[] {
  const shown = parts.filter((p) => p.amount > 0);
  const total = shown.reduce((sum, p) => sum + p.amount, 0);
  if (total <= 0) return [];
  const c = size / 2;
  const r = c;
  const inner = c - thickness;
  if (shown.length === 1) {
    const only = shown[0]!;
    return [
      {
        key: only.key,
        path: segment(c, c, r, inner, 0, 0.5) + segment(c, c, r, inner, 0.5, 1),
        start: 0,
        end: 1,
      },
    ];
  }
  let at = 0;
  return shown.map((p) => {
    const start = at;
    at += p.amount / total;
    const end = p === shown[shown.length - 1] ? 1 : at;
    return { key: p.key, path: segment(c, c, r, inner, start, end), start, end };
  });
}
