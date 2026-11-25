// Before and after a plan's options: the pure pieces the session and plan screens share. Every
// value and every change in words is the backend's (planning/compare.py); this only picks which to
// show where and how they look.

import type { CompareCell, CompareRow, Comparison, Direction } from "./types.ts";

/** A change's chip: emerald when the option is better for the household, rose when it is worse,
 * plain when it is the same. A change with no better or worse (what is left unplanned) has none. */
export function changeTone(direction: Direction): string | null {
  if (direction === "better") return "chip-emerald";
  if (direction === "worse") return "chip-rose";
  if (direction === "same") return "";
  return null;
}

/** The option's column in the comparison, by its label; -1 when the comparison doesn't have it. */
export function optionIndex(c: Pick<Comparison, "options">, label: string): number {
  return c.options.findIndex((o) => o.label === label);
}

export type CardRow = { key: string; label: string; before: CompareCell; after: CompareCell };

/** What an option's card shows under "Before → after": the dates and the interest in all. */
export function cardRows(c: Pick<Comparison, "rows" | "options">, label: string): CardRow[] {
  const i = optionIndex(c, label);
  if (i < 0) return [];
  return c.rows
    .filter((r) => r.on_card && r.options[i] !== undefined)
    .map((r) => ({ key: r.key, label: r.label, before: r.before, after: r.options[i] }));
}

/** Whether the value moved at all, so the card can strike through the old one. */
export function moved(row: Pick<CardRow, "before" | "after">): boolean {
  return row.before.value !== row.after.value;
}

/** The comparison table's rows, with each row's line under its label when it is a total. */
export function isTotal(row: Pick<CompareRow, "kind">): boolean {
  return row.kind === "interest_total";
}

/** A month's line where another debt's payment rolls in. */
export function rolledNote(row: { rolled_in: string | null; rolled_from: string | null }): string | null {
  if (!row.rolled_in) return null;
  return row.rolled_from ? `+${row.rolled_in} from the ${row.rolled_from}` : `+${row.rolled_in} rolled in`;
}
