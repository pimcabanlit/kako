import assert from "node:assert/strict";
import { test } from "node:test";

import type { HealthReport } from "../health.ts";
import { mekoHere } from "./here.ts";
import { docPage, groupOf, NAV, PAGES } from "./index.ts";
import { parseInline, plainText } from "./inline.ts";
import { pageMarkdown, tableOfContents } from "./markdown.ts";
import type { Block, DocPage, Section } from "./types.ts";

// The app's own screens a page may link to (src/app/).
const SCREENS = new Set(["/", "/money", "/plans", "/timeline", "/decisions", "/metrics", "/system"]);

function sectionsOf(page: DocPage): Section[] {
  return page.sections.flatMap((s) => [s, ...(s.children ?? [])]);
}

function textsOf(block: Block): string[] {
  switch (block.kind) {
    case "p":
    case "story":
    case "note":
    case "placeholder":
      return [block.text];
    case "list":
      return block.items;
    case "table":
      return [...block.head, ...block.rows.flat()];
    case "steps":
      return block.items.map((s) => s.text);
    case "timeline":
      return block.items.map((s) => s.text);
    case "pack":
      return block.parts.map((p) => p.text);
    case "flow":
      return block.nodes.map((n) => n.text);
    case "see":
      return [];
  }
}

function linksOf(page: DocPage): string[] {
  const blocks = [...(page.intro ?? []), ...sectionsOf(page).flatMap((s) => s.blocks)];
  const inText = blocks
    .flatMap(textsOf)
    .flatMap((t) => parseInline(t))
    .flatMap((run) => (run.kind === "link" ? [run.href] : []));
  const see = blocks.flatMap((b) => (b.kind === "see" ? b.links.map((l) => l.href) : []));
  return [...inText, ...see, ...(page.next ?? []).map((n) => n.href)];
}

test("inline text: code, bold and links, in order, with the text between", () => {
  assert.deepEqual(parseInline("Run `kako demo upload`, **once**, then see [Metrics](/metrics)."), [
    { kind: "text", text: "Run " },
    { kind: "code", text: "kako demo upload" },
    { kind: "text", text: ", " },
    { kind: "bold", text: "once" },
    { kind: "text", text: ", then see " },
    { kind: "link", text: "Metrics", href: "/metrics" },
    { kind: "text", text: "." },
  ]);
  assert.deepEqual(parseInline("plain"), [{ kind: "text", text: "plain" }]);
  assert.equal(plainText("**Built** with `memory_add`"), "Built with memory_add");
});

test("every page has a slug of its own and section ids unique within it", () => {
  assert.equal(new Set(PAGES.map((p) => p.slug)).size, PAGES.length);
  for (const page of PAGES) {
    const ids = sectionsOf(page).map((s) => s.id);
    assert.equal(new Set(ids).size, ids.length, page.slug);
    for (const id of ids) assert.match(id, /^[a-z][a-z0-9-]*$/, `${page.slug}#${id}`);
  }
});

test("the menu lists every page once, and the Meko page's parts", () => {
  const listed = NAV.flatMap((g) => (g.kind === "pages" ? g.slugs : []));
  assert.deepEqual([...listed].sort(), PAGES.map((p) => p.slug).sort());
  for (const g of NAV) if (g.kind === "sections") assert.ok(docPage(g.slug), g.slug);
  assert.equal(groupOf("meko"), "Meko in Kako");
  assert.equal(groupOf("engine"), "Under the hood");
});

test("every link inside Kako leads to a screen, a page or a section that exists", () => {
  for (const page of PAGES) {
    for (const href of linksOf(page)) {
      if (href.startsWith("https://")) continue;
      const [path = "", anchor] = href.split("#");
      if (path.startsWith("/docs/")) {
        const target = docPage(path.slice("/docs/".length));
        assert.ok(target, `${page.slug}: ${href}`);
        if (anchor) assert.ok(sectionsOf(target).some((s) => s.id === anchor), `${page.slug}: ${href}`);
      } else {
        assert.ok(SCREENS.has(path), `${page.slug}: ${href}`);
      }
    }
  }
});

test("How Kako uses Meko covers every part of Meko's context, each with its status", () => {
  const meko = docPage("meko");
  assert.ok(meko);
  const status = Object.fromEntries(meko.sections.map((s) => [s.id, s.status]));
  assert.deepEqual(status, {
    datapack: "built",
    conversations: "built",
    traces: "built",
    memory: "built",
    learning: "built",
    knowledge: "built",
    "self-learning": "built",
    artifacts: "planned",
    postgres: "planned",
    sharing: "in-part",
    metrics: "built",
    where: undefined,
  });
  // A part not built says so in a placeholder, never only in its chip.
  for (const s of meko.sections.filter((s) => s.status === "planned")) {
    assert.ok(s.blocks.some((b) => b.kind === "placeholder"), s.id);
  }
});

test("Markdown: the title, every section as a heading, and nothing left undefined", () => {
  for (const page of PAGES) {
    const md = pageMarkdown(page);
    assert.ok(md.startsWith(`# ${page.title}\n\n${page.lead}`), page.slug);
    for (const s of page.sections) assert.ok(md.includes(`\n## ${s.title}`), `${page.slug}: ${s.title}`);
    for (const c of page.sections.flatMap((s) => s.children ?? []))
      assert.ok(md.includes(`\n### ${c.title}`), `${page.slug}: ${c.title}`);
    assert.ok(!md.includes("undefined"), page.slug);
  }
  const meko = pageMarkdown(docPage("meko")!);
  assert.ok(meko.includes("*Planned*"));
  assert.ok(meko.includes("> **In the story · Session 2, Sep 15.**"));
  assert.ok(meko.includes("| Part of Meko |") || meko.includes("| Kept in |"));
});

test("On this page: each section, then its sub-sections", () => {
  const toc = tableOfContents(docPage("meko")!);
  assert.deepEqual(toc.slice(0, 3), [
    { id: "datapack", title: "The household's datapack", depth: 2 },
    { id: "isolation", title: "Isolation", depth: 3 },
    { id: "conversations", title: "Conversations", depth: 2 },
  ]);
  assert.equal(toc.at(-1)?.id, "story-through-meko");
});

function health(meko: Partial<HealthReport["meko"]>): HealthReport {
  const service = { ok: true, detail: "ok", latency_ms: 3, version: null };
  return { status: "ok", postgres: service, meko: { ...service, target: "local", ...meko } };
}

test("Meko on this machine: off, local, Cloud or out of reach, from the health check", () => {
  // The backend's own words when KAKO_MEKO_OFF is set (backend/src/kako/meko/health.py).
  const off = health({ detail: "off here (KAKO_MEKO_OFF): sessions are kept in Kako only", latency_ms: null });
  assert.equal(mekoHere(off), "off");
  assert.equal(mekoHere(health({})), "local");
  assert.equal(mekoHere(health({ target: "cloud" })), "cloud");
  assert.equal(mekoHere(health({ ok: false, detail: "connection refused" })), "unreachable");
});
