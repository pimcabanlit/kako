// The small Markdown subset the documentation's text uses: `code`, **bold** and [label](href).
// Pure, so the page and its Markdown copy read the same text the same way.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "code"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "link"; text: string; href: string };

const PATTERN = /`([^`]+)`|\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;

/** The text as runs of plain text, code, bold and links, in order. */
export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  let at = 0;
  for (const match of source.matchAll(PATTERN)) {
    const start = match.index ?? 0;
    if (start > at) out.push({ kind: "text", text: source.slice(at, start) });
    const [, code, bold, label, href] = match;
    if (code !== undefined) out.push({ kind: "code", text: code });
    else if (bold !== undefined) out.push({ kind: "bold", text: bold });
    else if (label !== undefined && href !== undefined) out.push({ kind: "link", text: label, href });
    at = start + match[0].length;
  }
  if (at < source.length) out.push({ kind: "text", text: source.slice(at) });
  return out;
}

/** The text with its markup taken out: what a heading's anchor or a search reads. */
export function plainText(source: string): string {
  return parseInline(source)
    .map((run) => run.text)
    .join("");
}
