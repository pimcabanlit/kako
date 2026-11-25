"use client";

// The documentation screen, laid out like Meko's own docs: the pages down the left, the page in the
// middle, "On this page" on the right (docs/architecture.md, "The documentation screen"). Each page
// is data (src/lib/docs/), so the screen and "Copy page as Markdown" say the same words.

import { ArrowUpRight, BookOpen, Check, ChevronDown, Copy, Hash } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useState, type ReactNode } from "react";

import { TopBar } from "@/components/top-bar";
import { fetchHealth } from "@/lib/health";
import { HERE_WORDS, mekoHere, type MekoHere } from "@/lib/docs/here";
import { docHref, docPage, groupOf, NAV } from "@/lib/docs/index";
import { parseInline } from "@/lib/docs/inline";
import { pageMarkdown, STATUS_WORDS, tableOfContents } from "@/lib/docs/markdown";
import type { Block, DocPage, Section, Status } from "@/lib/docs/types";

export function DocsView({ page }: { page: DocPage }) {
  const toc = tableOfContents(page);
  const active = useActiveSection(toc.map((t) => t.id));

  return (
    <>
      <TopBar phoneOnly>
        <h1 className="truncate text-[15px] font-semibold">Documentation</h1>
      </TopBar>
      <main id="docs-scroll" className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-[1280px] grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)] xl:grid-cols-[220px_minmax(0,1fr)_210px]">
          <aside className="hidden border-r border-line lg:block">
            <div className="sticky top-0 max-h-dvh overflow-y-auto px-4 py-7">
              <DocsNav page={page} />
            </div>
          </aside>

          <article className="min-w-0 px-4 pt-6 pb-24 md:px-10 md:pt-10">
            <PhoneNav page={page} />
            <p className="text-[13px] text-muted">
              Documentation
              {groupOf(page.slug) && <> / {groupOf(page.slug)}</>}
            </p>
            <h1 className="display mt-2 text-[28px] leading-[1.1] md:text-[36px]">{page.title}</h1>
            <p className="mt-3 max-w-3xl text-[17px] text-muted">{page.lead}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              <CopyMarkdown page={page} />
              {page.external && (
                <a href={page.external.href} target="_blank" rel="noreferrer" className="btn px-3 py-1.5 text-[13px]">
                  {page.external.label}
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </a>
              )}
            </div>

            <div className="doc-body mt-8 max-w-3xl">
              {(page.intro ?? []).map((b, i) => (
                <BlockView key={i} block={b} />
              ))}
              {page.live === "meko" && <MekoHereNote />}
              {page.sections.map((s) => (
                <SectionView key={s.id} section={s} depth={2} />
              ))}
              {page.next && page.next.length > 0 && (
                <footer className="mt-12 border-t border-line pt-5">
                  <p className="eyebrow">Next steps</p>
                  <ul className="mt-2 list-disc space-y-1.5 pl-5">
                    {page.next.map((n) => (
                      <li key={n.href}>
                        <DocLink href={n.href}>{n.label}</DocLink> {n.text}
                      </li>
                    ))}
                  </ul>
                </footer>
              )}
            </div>
          </article>

          <aside className="hidden border-l border-line xl:block" aria-label="On this page">
            <nav className="sticky top-0 max-h-dvh overflow-y-auto px-4 py-10 text-[13.5px]">
              <p className="eyebrow mb-2">On this page</p>
              <ul>
                {toc.map((t) => (
                  <li key={t.id}>
                    <a
                      href={`#${t.id}`}
                      aria-current={active === t.id ? "location" : undefined}
                      className={`block border-l-2 py-1 transition-colors ${t.depth === 3 ? "pl-5" : "pl-2.5"} ${
                        active === t.id
                          ? "border-teal text-fg"
                          : "border-transparent text-muted hover:border-line-strong hover:text-fg"
                      }`}
                    >
                      {t.title}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          </aside>
        </div>
      </main>
    </>
  );
}

/** The documentation's menu: the pages by group, and the Meko page's parts with their status. */
function DocsNav({ page, onNavigate }: { page: DocPage; onNavigate?: () => void }) {
  return (
    <nav aria-label="Documentation" className="text-[14px]">
      <p className="eyebrow flex items-center gap-2">
        <BookOpen className="size-3.5" aria-hidden />
        Documentation
      </p>
      {NAV.map((group) => (
        <div key={group.title} className="mt-5">
          <p className="eyebrow mb-1.5 px-2.5">{group.title}</p>
          <ul className="space-y-0.5">
            {group.kind === "pages"
              ? group.slugs.map((slug) => {
                  const p = docPage(slug);
                  if (!p) return null;
                  const here = p.slug === page.slug;
                  return (
                    <li key={slug}>
                      <Link
                        href={docHref(slug)}
                        onClick={onNavigate}
                        aria-current={here ? "page" : undefined}
                        className={`block rounded-lg px-2.5 py-1.5 transition-colors ${
                          here ? "bg-meko-soft font-semibold text-meko" : "text-fg/90 hover:bg-raised"
                        }`}
                      >
                        {p.title}
                      </Link>
                    </li>
                  );
                })
              : (docPage(group.slug)?.sections ?? []).map((s) => (
                  <li key={s.id}>
                    <Link
                      href={`${docHref(group.slug)}#${s.id}`}
                      onClick={onNavigate}
                      className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-fg/90 transition-colors hover:bg-raised"
                    >
                      <StatusDot status={s.status} />
                      {s.title}
                    </Link>
                  </li>
                ))}
          </ul>
        </div>
      ))}
      <ul className="mt-5 flex flex-wrap gap-x-4 gap-y-1 px-2.5 text-[12.5px] text-muted" aria-label="What the dots mean">
        {(["built", "in-part", "planned"] as const).map((s) => (
          <li key={s} className="flex items-center gap-1.5">
            <StatusDot status={s} />
            {STATUS_WORDS[s].toLowerCase()}
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** On a phone or a narrow window, the menu folds into one line above the page. */
function PhoneNav({ page }: { page: DocPage }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mb-5 lg:hidden">
      <button
        type="button"
        className="btn w-full justify-between"
        aria-expanded={open}
        aria-controls="docs-phone-nav"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="flex items-center gap-2">
          <BookOpen className="size-4" aria-hidden />
          Pages
        </span>
        <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div id="docs-phone-nav" className="panel mt-2">
          <DocsNav page={page} onNavigate={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}

function StatusDot({ status }: { status?: Status }) {
  if (!status) return <span className="size-[7px] shrink-0" aria-hidden />;
  const look =
    status === "built"
      ? "bg-emerald"
      : status === "in-part"
        ? "bg-gold"
        : "border-[1.5px] border-dashed border-muted bg-transparent";
  return (
    <span className={`inline-block size-[7px] shrink-0 rounded-full ${look}`} role="img" aria-label={STATUS_WORDS[status]} />
  );
}

function StatusChip({ status }: { status: Status }) {
  const look =
    status === "built" ? "chip-emerald" : status === "in-part" ? "chip-gold" : "border-dashed border-line-strong bg-transparent";
  return <span className={`chip ${look} ml-2 align-[3px] text-[12px]`}>{STATUS_WORDS[status].toLowerCase()}</span>;
}

function SectionView({ section, depth }: { section: Section; depth: 2 | 3 }) {
  const Heading = depth === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={section.id}>
      <Heading
        id={section.id}
        className={`group scroll-mt-6 ${
          depth === 2 ? "display mt-12 mb-3 text-[23px] leading-tight" : "mt-7 mb-2 text-[17px] font-semibold"
        }`}
      >
        {section.title}
        {section.status && <StatusChip status={section.status} />}
        <a
          href={`#${section.id}`}
          className="ml-2 inline-flex align-middle text-muted opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
          aria-label={`Link to ${section.title}`}
        >
          <Hash className="size-4" aria-hidden />
        </a>
      </Heading>
      {section.blocks.map((b, i) => (
        <BlockView key={i} block={b} />
      ))}
      {(section.children ?? []).map((c) => (
        <SectionView key={c.id} section={c} depth={3} />
      ))}
    </section>
  );
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "p":
      return (
        <p className="mb-3">
          <Text text={block.text} />
        </p>
      );
    case "list":
      return (
        <ul className="mb-4 list-disc space-y-2.5 pl-5">
          {block.items.map((item, i) => (
            <li key={i}>
              <Text text={item} />
            </li>
          ))}
        </ul>
      );
    case "story":
      return (
        <Callout tone="story" label={`In the story${block.when ? ` · ${block.when}` : ""}`}>
          <Text text={block.text} />
        </Callout>
      );
    case "note":
      return (
        <Callout tone="note" label={block.label}>
          <Text text={block.text} />
        </Callout>
      );
    case "placeholder":
      return (
        <Callout tone="placeholder" label={block.label ?? "Not built yet"}>
          <Text text={block.text} />
        </Callout>
      );
    case "table":
      return (
        <div className="mb-4 overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse text-[14px]">
            <thead>
              <tr>
                {block.head.map((h, i) => (
                  <th
                    key={i}
                    scope="col"
                    className="border-b border-line-strong px-2.5 py-2 text-left text-[11.5px] font-semibold tracking-[0.1em] text-muted uppercase"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((c, i) => (
                    <td key={i} className={`border-b border-line px-2.5 py-2.5 align-top ${i === 0 ? "font-medium" : ""}`}>
                      <Text text={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "steps":
      return (
        <ol className="mb-4 space-y-3">
          {block.items.map((step, i) => (
            <li key={i} className="flex gap-3">
              <span className="num mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-line-strong text-[12px] font-semibold text-muted">
                {i + 1}
              </span>
              <span>
                <b>{step.title}.</b> <Text text={step.text} />
              </span>
            </li>
          ))}
        </ol>
      );
    case "timeline":
      return (
        <ol className="my-3 border-l-2 border-line-strong">
          {block.items.map((item, i) => (
            <li key={i} className="relative pb-4 pl-5">
              <span
                className={`absolute top-[7px] -left-[6px] size-2.5 rounded-full ${
                  item.planned ? "border-[1.5px] border-dashed border-muted bg-bg" : "bg-meko"
                }`}
                aria-hidden
              />
              <b className="block">
                <span className="num">{item.when}</span> · {item.title}
              </b>
              <Text text={item.text} />
              {item.planned && <span className="sr-only"> (not shown yet)</span>}
            </li>
          ))}
        </ol>
      );
    case "pack":
      return (
        <figure
          className="relative my-5 grid gap-2.5 rounded-[18px] border-[1.5px] border-meko/60 px-4 pt-7 pb-4 sm:grid-cols-2"
          aria-label={block.label}
        >
          <figcaption className="wordmark absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-meko px-3 py-1 text-[11px] tracking-[0.1em] whitespace-nowrap text-bg uppercase">
            {block.label}
          </figcaption>
          {block.parts.map((part) => (
            <div
              key={part.title}
              className={`rounded-[10px] border border-line border-l-4 bg-surface px-3 py-2.5 text-[13.5px] ${
                part.status === "planned" ? "border-l-muted doc-dashed-left" : "border-l-meko"
              }`}
            >
              <b className="text-[14.5px]">{part.title}</b>
              <StatusChip status={part.status} />
              <p className="mt-1 text-muted">
                <Text text={part.text} />
              </p>
            </div>
          ))}
        </figure>
      );
    case "flow":
      return (
        <figure className="my-4 flex flex-wrap items-stretch gap-2" aria-label={block.nodes.map((n) => n.title).join(", then ")}>
          {/* Each arrow travels with the step it leads to, so a wrapped row starts with its verb. */}
          {block.nodes.map((node, i) => (
            <div key={node.title} className="flex min-w-0 flex-[1_1_200px] items-center gap-2">
              {i > 0 && block.arrows[i - 1] && <span className="flow-arrow shrink-0">{block.arrows[i - 1]}</span>}
              <div className={`flow-node flow-${node.tone} min-w-0 flex-1 self-stretch rounded-xl border-[1.5px] px-3 py-2.5 text-[13.5px]`}>
                <b className="block text-[14px]">{node.title}</b>
                <span className="text-[12.5px] text-muted">{node.text}</span>
              </div>
            </div>
          ))}
        </figure>
      );
    case "see":
      return (
        <p className="mb-3 flex flex-wrap items-center gap-2 text-[13.5px] text-muted">
          See it in Kako:
          {block.links.map((l) => (
            <Link key={l.href + l.label} href={l.href} className="chip hover:text-fg">
              {l.label}
            </Link>
          ))}
        </p>
      );
  }
}

function Callout({
  tone,
  label,
  children,
}: {
  tone: "story" | "note" | "placeholder";
  label: string;
  children: ReactNode;
}) {
  const look = {
    story: "border-l-gold bg-gold-soft",
    note: "border-l-meko bg-meko-soft",
    placeholder: "border-l-muted doc-dashed-left bg-raised",
  }[tone];
  const ink = { story: "text-gold", note: "text-meko", placeholder: "text-muted" }[tone];
  return (
    <aside className={`my-4 rounded-xl border border-line border-l-[3px] px-4 py-3 text-[14.5px] ${look}`}>
      <b className={`block text-[11.5px] tracking-[0.12em] uppercase ${ink}`}>{label}</b>
      <div className="mt-0.5">{children}</div>
    </aside>
  );
}

function Text({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((run, i) => {
        switch (run.kind) {
          case "text":
            return <Fragment key={i}>{run.text}</Fragment>;
          case "bold":
            return <b key={i}>{run.text}</b>;
          case "code":
            return (
              <code key={i} className="rounded-md border border-line bg-raised px-1.5 py-px font-mono text-[0.86em]">
                {run.text}
              </code>
            );
          case "link":
            return (
              <DocLink key={i} href={run.href}>
                {run.text}
              </DocLink>
            );
        }
      })}
    </>
  );
}

function DocLink({ href, children }: { href: string; children: ReactNode }) {
  if (href.startsWith("/"))
    return (
      <Link href={href} className="text-teal underline-offset-2 hover:underline">
        {children}
      </Link>
    );
  return (
    <a href={href} target="_blank" rel="noreferrer" className="text-teal underline-offset-2 hover:underline">
      {children}
      <ArrowUpRight className="ml-0.5 inline size-3.5 align-[-1px]" aria-hidden />
    </a>
  );
}

function CopyMarkdown({ page }: { page: DocPage }) {
  const [state, setState] = useState<"idle" | "copied" | "refused">("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 2000);
    return () => clearTimeout(timer);
  }, [state]);
  async function copy() {
    try {
      await navigator.clipboard.writeText(pageMarkdown(page));
      setState("copied");
    } catch {
      setState("refused");
    }
  }
  return (
    <button type="button" className="btn px-3 py-1.5 text-[13px]" onClick={() => void copy()} aria-live="polite">
      {state === "copied" ? <Check className="size-3.5 text-emerald" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {state === "copied" ? "Copied" : state === "refused" ? "Copy not allowed here" : "Copy page as Markdown"}
    </button>
  );
}

/** What this machine's Kako reaches: off, local Meko, Meko Cloud, or nothing. Shown once known. */
function MekoHereNote() {
  const [here, setHere] = useState<MekoHere | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchHealth(controller.signal)
      .then((report) => setHere(mekoHere(report)))
      .catch(() => undefined); // no note when the backend can't say: the page reads the same
    return () => controller.abort();
  }, []);
  if (!here) return null;
  return (
    <Callout tone="note" label="On this machine">
      <Text text={HERE_WORDS[here]} />
    </Callout>
  );
}

/** The section in view, for "On this page": the last heading above the top third of the page. */
function useActiveSection(ids: string[]): string | null {
  const [active, setActive] = useState<string | null>(ids[0] ?? null);
  const key = ids.join(" ");
  useEffect(() => {
    const root = document.getElementById("docs-scroll");
    if (!root) return;
    const headings = key
      .split(" ")
      .map((id) => document.getElementById(id))
      .filter((h): h is HTMLElement => h !== null);
    const onScroll = () => {
      const line = root.getBoundingClientRect().top + root.clientHeight / 3;
      let current = headings[0]?.id ?? null;
      for (const h of headings) if (h.getBoundingClientRect().top <= line) current = h.id;
      setActive(current);
    };
    onScroll();
    root.addEventListener("scroll", onScroll, { passive: true });
    return () => root.removeEventListener("scroll", onScroll);
  }, [key]);
  return active;
}
