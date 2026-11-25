// A documentation page as Markdown, for "Copy page as Markdown": the same words as the screen.

import type { Block, DocPage, Section, Status } from "./types.ts";

export const STATUS_WORDS: Record<Status, string> = {
  built: "Built",
  "in-part": "In part",
  planned: "Planned",
};

function cell(text: string): string {
  return text.replaceAll("|", "\\|");
}

function block(b: Block): string {
  switch (b.kind) {
    case "p":
      return b.text;
    case "list":
      return b.items.map((item) => `- ${item}`).join("\n");
    case "story":
      return `> **In the story${b.when ? ` · ${b.when}` : ""}.** ${b.text}`;
    case "note":
      return `> **${b.label}.** ${b.text}`;
    case "placeholder":
      return `> **${b.label ?? "Not built yet"}.** ${b.text}`;
    case "pack":
      return [
        `**${b.label}**`,
        ...b.parts.map((part) => `- **${part.title}** (${STATUS_WORDS[part.status].toLowerCase()}): ${part.text}`),
      ].join("\n");
    case "flow":
      return b.nodes
        .map((node, i) => {
          const arrow = i < b.arrows.length ? ` → *${b.arrows[i]}*` : "";
          return `${i + 1}. **${node.title}**: ${node.text}${arrow}`;
        })
        .join("\n");
    case "table":
      return [
        `| ${b.head.map(cell).join(" | ")} |`,
        `| ${b.head.map(() => "---").join(" | ")} |`,
        ...b.rows.map((row) => `| ${row.map(cell).join(" | ")} |`),
      ].join("\n");
    case "steps":
      return b.items.map((step, i) => `${i + 1}. **${step.title}.** ${step.text}`).join("\n");
    case "timeline":
      return b.items.map((item) => `- **${item.when}, ${item.title}.** ${item.text}`).join("\n");
    case "see":
      return `See it in Kako: ${b.links.map((l) => `[${l.label}](${l.href})`).join(", ")}.`;
  }
}

function section(s: Section, depth: number): string {
  const heading = `${"#".repeat(depth)} ${s.title}`;
  const status = s.status ? `\n\n*${STATUS_WORDS[s.status]}*` : "";
  const body = s.blocks.map(block);
  const children = (s.children ?? []).map((c) => section(c, depth + 1));
  return [heading + status, ...body, ...children].join("\n\n");
}

/** The page as Markdown: its title, its lead, then each section with its blocks. */
export function pageMarkdown(page: DocPage): string {
  const next = page.next?.length
    ? ["## Next steps", page.next.map((n) => `- [${n.label}](${n.href}) ${n.text}`).join("\n")]
    : [];
  return (
    [
      `# ${page.title}`,
      page.lead,
      ...(page.intro ?? []).map(block),
      ...page.sections.map((s) => section(s, 2)),
      ...next,
    ].join("\n\n") + "\n"
  );
}

export type TocEntry = { id: string; title: string; depth: 2 | 3 };

/** "On this page": each section, then its sub-sections. */
export function tableOfContents(page: DocPage): TocEntry[] {
  return page.sections.flatMap((s) => [
    { id: s.id, title: s.title, depth: 2 as const },
    ...(s.children ?? []).map((c) => ({ id: c.id, title: c.title, depth: 3 as const })),
  ]);
}
