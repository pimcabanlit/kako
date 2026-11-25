// Small text helpers for the session screen. Pure, tested in text.test.ts.

/** A reply in blocks: paragraphs, and lists where every line starts with "- " or "• ". The texts
 * are the number-checked ones, shown as written: no Markdown beyond that. */
export type Block = { kind: "p"; text: string } | { kind: "ul"; items: string[] };

const BULLET = /^\s*(?:[-•*])\s+/;

export function blocks(text: string): Block[] {
  const out: Block[] = [];
  let para: string[] = [];
  let list: string[] = [];
  const flushPara = () => {
    if (para.length) out.push({ kind: "p", text: para.join(" ") });
    para = [];
  };
  const flushList = () => {
    if (list.length) out.push({ kind: "ul", items: list });
    list = [];
  };
  for (const raw of text.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushPara();
      flushList();
    } else if (BULLET.test(line)) {
      flushPara();
      list.push(line.replace(BULLET, ""));
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();
  return out;
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** "2026-09-15" as "Sep 15, 2026": a household date, read without any time zone. */
export function formatDay(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(isoDate);
  if (!match) return isoDate;
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${month} ${Number(match[3])}, ${match[1]}` : isoDate;
}

/** A new session's title from its first message: whole words, at most `max` characters. */
export function titleFrom(message: string, max = 60): string {
  const flat = message.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat || "New session";
  const cut = flat.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  return `${(space > max / 2 ? cut.slice(0, space) : cut).replace(/[\s,.;:!?-]+$/, "")}…`;
}

/** "US$0.0123" from the API's decimal string; a replayed turn costs nothing. */
export function usd(decimal: string): string {
  const value = Number(decimal);
  if (!Number.isFinite(value)) return `US$${decimal}`;
  if (value === 0) return "US$0";
  return `US$${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

/** 73656 as "73,656". */
export function count(n: number): string {
  return n.toLocaleString("en-US");
}

/** "To revisit: “Should we…” (Session 1, …)" split into its label and the rest. */
export function splitLabel(line: string): { label: string | null; text: string } {
  const match = /^(To revisit|Why):\s*([\s\S]*)$/.exec(line);
  return match ? { label: match[1], text: match[2] } : { label: null, text: line };
}

/** "Take-home pay a month: ₱100,000.00 → ₱116,000.00" in parts, for a "what changed" line. */
export function parseChange(
  line: string,
): { label: string; before: string; after: string } | null {
  const match = /^(.*?):\s+(.+?)\s+→\s+(.+)$/.exec(line);
  return match ? { label: match[1], before: match[2], after: match[3] } : null;
}

/** An option's label "A: all extra on the card" as its letter and its words. */
export function optionParts(label: string): { letter: string | null; words: string } {
  const match = /^([A-Z]):\s*(.*)$/.exec(label);
  return match ? { letter: match[1], words: match[2] } : { letter: null, words: label };
}
