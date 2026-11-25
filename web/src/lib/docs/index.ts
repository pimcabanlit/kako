// Every documentation page, and the menu down the left of the documentation screen
// (laid out like Meko's own docs: docs/architecture.md, "The documentation screen").

import { AGENTS } from "./pages/agents.ts";
import { DREAMING } from "./pages/dreaming.ts";
import { ENGINE } from "./pages/engine.ts";
import { GUARDRAILS } from "./pages/guardrails.ts";
import { MEKO } from "./pages/meko.ts";
import { RULE } from "./pages/rule.ts";
import { STORY } from "./pages/story.ts";
import type { DocPage, NavGroup } from "./types.ts";

export const PAGES: readonly DocPage[] = [MEKO, STORY, RULE, ENGINE, AGENTS, DREAMING, GUARDRAILS];

/** The page the documentation opens on. */
export const FIRST_PAGE = MEKO.slug;

export const NAV: readonly NavGroup[] = [
  { title: "Start here", kind: "pages", slugs: [MEKO.slug, STORY.slug, RULE.slug] },
  { title: "Meko in Kako", kind: "sections", slug: MEKO.slug },
  { title: "Under the hood", kind: "pages", slugs: [ENGINE.slug, AGENTS.slug, DREAMING.slug, GUARDRAILS.slug] },
];

export function docPage(slug: string): DocPage | undefined {
  return PAGES.find((p) => p.slug === slug);
}

/** The group a page is listed under, for its breadcrumb. */
export function groupOf(slug: string): string {
  const sections = NAV.find((g) => g.kind === "sections" && g.slug === slug);
  const pages = NAV.find((g) => g.kind === "pages" && g.slugs.includes(slug));
  return (sections ?? pages)?.title ?? "";
}

export function docHref(slug: string): string {
  return `/docs/${slug}`;
}
