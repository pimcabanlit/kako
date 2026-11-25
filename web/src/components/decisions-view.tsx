"use client";

import {
  ArrowLeft,
  ArrowRight,
  BookMarked,
  ClipboardList,
  CreditCard,
  GraduationCap,
  House,
  type LucideIcon,
  Plane,
  Plus,
  Umbrella,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { PageHeader, ViewChips } from "@/components/page-header";
import { Failed, failure } from "@/components/plan-view";
import { TopBar } from "@/components/top-bar";
import { api } from "@/lib/api";
import { anchoredDecision, decisionStatus } from "@/lib/history";
import {
  acrossShelf,
  BOOKMARKS,
  type Bookmark,
  bookHref,
  bookmarkLabels,
  bookmarkOf,
  changedParts,
  type CoverIcon,
  coverIcon,
  coverOf,
  factGroups,
  NEXT_BOOKMARK,
  onShelf,
  optionWords,
  patternWords,
  sharedFrom,
  type ShelfView,
  shelfChips,
  whyLine,
} from "@/lib/shelf";
import { formatDay } from "@/lib/text";
import type { Decision, Decisions } from "@/lib/types";
import type { Tone } from "@/lib/words";
import { plural } from "@/lib/working";

function tone(t: Tone): string {
  return t === "plain" ? "" : `chip-${t}`;
}

const ICONS: Record<CoverIcon, LucideIcon> = {
  trip: Plane,
  card: CreditCard,
  buffer: Umbrella,
  school: GraduationCap,
  home: House,
  book: BookMarked,
};

/** Every decision the household made, as a bookshelf: each decision a book whose cover is its
 * question, its author who decided and the session it was decided in. Opening one shows its three
 * bookmarks: the decision, what to revisit, and the facts it rests on. The book and bookmark open
 * are in the address (?book=<id>&mark=revisit), so the timeline can link straight to one. */
export function DecisionsView() {
  const params = useSearchParams();
  const router = useRouter();
  const bookId = params.get("book");
  const mark = bookmarkOf(params.get("mark"));
  const [view, setView] = useState<Loaded<Decisions>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.decisions(controller.signal).then(
      (value) => setView({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setView({ kind: "error", message: failure(error, "the decisions") });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  // Older links named a decision as #decision-<id>: open its book instead.
  useEffect(() => {
    const id = anchoredDecision(window.location.hash);
    if (id) router.replace(bookHref(id));
  }, [router]);

  if (view.kind === "loading") return <ShelfSkeleton />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const { decisions, as_of } = view.value;
  if (bookId) {
    const book = decisions.find((d) => d.id === bookId);
    return book ? (
      <OpenBook
        key={book.id}
        decision={book}
        cover={coverOf(decisions).get(book.id) ?? 0}
        mark={mark}
        onMark={(m) => router.replace(bookHref(book.id, m), { scroll: false })}
      />
    ) : (
      <NotOnShelf />
    );
  }
  return <Shelf decisions={decisions} asOf={as_of} />;
}

// The book last closed, so the shelf can give its cover the focus back.
let lastClosed: string | null = null;

// --- The shelf -----------------------------------------------------------------------------------

const PHONE_HEIGHTS = ["h-[236px]", "h-[220px]", "h-[248px]"];
const HEIGHTS = ["sm:h-[340px]", "sm:h-[316px]", "sm:h-[352px]"];

const EMPTY_VIEW: Record<ShelfView, string> = {
  all: "No decisions yet.",
  revisit: "Nothing to revisit: no fact a decision rests on has changed since it was made.",
  "in-force": "No decision is in force.",
  revised: "No decision has been revised or reversed yet.",
};

function Shelf({ decisions, asOf }: { decisions: Decision[]; asOf: string }) {
  const [shelf, setShelf] = useState<ShelfView>("all");
  const covers = coverOf(decisions);
  const shown = decisions.filter((d) => onShelf(d, shelf));
  const pattern = acrossShelf(decisions);

  // Back from a book: its cover has the focus again.
  useEffect(() => {
    if (lastClosed) document.getElementById(`cover-${lastClosed}`)?.focus();
    lastClosed = null;
  }, []);

  return (
    <>
      <TopBar phoneOnly />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-6xl space-y-8 px-4 pt-8 pb-10 md:px-8 md:pt-12">
          <PageHeader
            title="Decisions"
            note={
              <>
                Every choice the household made, shelved newest first, as Kako holds them on{" "}
                <span className="num">{formatDay(asOf)}</span>. Open a book to see what was chosen,
                what has moved since, and the facts it rests on.
              </>
            }
          >
            {decisions.length > 0 && (
              <ViewChips
                label="Which decisions"
                views={shelfChips(decisions)}
                chosen={shelf}
                onChoose={setShelf}
              />
            )}
          </PageHeader>

          {decisions.length === 0 ? (
            <NoDecisions />
          ) : (
            <div role="tabpanel" id={`panel-${shelf}`} aria-labelledby={`tab-${shelf}`} className="space-y-8">
              <section aria-label="The shelf" className="pt-4">
                {shown.length === 0 ? (
                  <p className="py-14 text-center text-muted">{EMPTY_VIEW[shelf]}</p>
                ) : (
                  <ul className="grid grid-cols-2 items-end gap-x-4 gap-y-8 px-1 sm:flex sm:flex-wrap sm:gap-7 sm:px-5">
                    {shown.map((d, i) => (
                      <li key={d.id}>
                        <BookOnShelf decision={d} cover={covers.get(d.id) ?? 0} at={i} />
                      </li>
                    ))}
                    {shelf === "all" && (
                      <li className={`${PHONE_HEIGHTS[shown.length % 3]} sm:h-[300px]`}>
                        <div className="flex h-full w-full flex-col items-center justify-center gap-2.5 rounded-[4px_14px_14px_4px] border-[1.5px] border-dashed border-line-strong p-5 text-center text-[13px] text-muted sm:w-[236px] sm:text-[13.5px]">
                          <Plus className="size-6" aria-hidden />
                          The next decision is shelved here once an adult approves it.
                        </div>
                      </li>
                    )}
                  </ul>
                )}
                <div aria-hidden className="shelf-plank mt-[-2px]" />
              </section>

              <section aria-label="What the covers mean" className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[13.5px] text-muted">
                <span className="inline-flex items-center gap-2">
                  <span aria-hidden className="h-[22px] w-3 bg-[#fcd34d] [clip-path:polygon(0_0,100%_0,100%_100%,50%_80%,0_100%)]" />
                  Gold ribbon: a fact it rests on has changed, so it&rsquo;s worth revisiting
                </span>
                <span>Cover colour and pattern: the session it was made in</span>
              </section>

              {pattern && <AcrossShelf pattern={patternWords(pattern)} />}
            </div>
          )}
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

function BookOnShelf({ decision: d, cover, at }: { decision: Decision; cover: number; at: number }) {
  const Icon = ICONS[coverIcon(d)];
  const revisit = d.revisit.length > 0;
  const status = decisionStatus(d.status);
  return (
    <Link
      id={`cover-${d.id}`}
      href={bookHref(d.id)}
      className={`book-cover book-lift cover-${cover} flex w-full flex-col rounded-[4px_14px_14px_4px] pt-5 pr-4 pb-4 pl-7 outline-none focus-visible:ring-2 focus-visible:ring-teal focus-visible:ring-offset-2 focus-visible:ring-offset-bg sm:w-[236px] sm:pt-6 sm:pr-5 sm:pb-5 sm:pl-9 ${PHONE_HEIGHTS[at % 3]} ${HEIGHTS[at % 3]}`}
    >
      {revisit && <span aria-hidden className="cover-ribbon" />}
      <Icon className="size-6 shrink-0 sm:size-7" style={{ color: "var(--cover-icon)" }} strokeWidth={1.6} aria-hidden />
      {d.status !== "active" && (
        <span className={`chip mt-3 w-fit ${tone(status.tone)}`}>{status.label}</span>
      )}
      <span className="display mt-auto text-[14.5px] leading-snug font-semibold sm:text-[18px]">
        {d.question}
      </span>
      <span className="mt-3 text-[13px] italic sm:text-[14px]" style={{ color: "var(--cover-ink)" }}>
        by {d.decided_by ?? "the household"}
      </span>
      <span className="num mt-0.5 text-[12px] text-white/75 sm:text-[12.5px]">
        {d.session_title} · {formatDay(d.on)}
      </span>
      {revisit && <span className="sr-only">, to revisit</span>}
    </Link>
  );
}

function AcrossShelf({ pattern }: { pattern: { lead: string; lean: string; tail: string } }) {
  return (
    <section
      aria-label="A pattern across the shelf"
      className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-[18px] border border-line bg-glass px-5 py-4"
    >
      <span className="eyebrow">Across the shelf</span>
      <p className="min-w-0 flex-1 text-[15px]">
        {pattern.lead} <strong className="text-emerald">{pattern.lean}</strong>
        {pattern.tail}
      </p>
      <span className="chip">Counted from each option&rsquo;s tags</span>
    </section>
  );
}

// --- The open book -------------------------------------------------------------------------------

/** Short names for a phone, where the three must still fit on one row. */
function phoneLabels(d: Decision): Record<Bookmark, string> {
  return {
    decision: "Decision",
    revisit: `Revisit · ${d.revisit.length}`,
    facts: plural(d.rests_on.length, "fact"),
  };
}

function OpenBook({
  decision: d,
  cover,
  mark,
  onMark,
}: {
  decision: Decision;
  cover: number;
  mark: Bookmark;
  onMark: (mark: Bookmark) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const page = useRef<HTMLDivElement>(null);
  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    return () => {
      lastClosed = d.id;
    };
  }, [d.id]);

  function goTo(next: Bookmark) {
    onMark(next);
    page.current?.scrollIntoView({ block: "start" });
    document.getElementById(`mark-${next}`)?.focus({ preventScroll: true });
  }

  return (
    <>
      <TopBar phoneOnly />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-7 px-4 pt-6 pb-10 md:px-8 md:pt-10">
          <Link
            href="/decisions"
            className="inline-flex items-center gap-2 text-[14px] font-semibold text-muted hover:text-fg"
          >
            <ArrowLeft className="size-4" aria-hidden />
            Back to the shelf
          </Link>
          <article
            aria-labelledby={`book-${d.id}`}
            className="flex flex-col rounded-[6px_18px_18px_6px] shadow-[0_40px_80px_-34px_rgba(0,0,0,0.7)] md:flex-row"
          >
            <BookCover decision={d} cover={cover} headingRef={heading} />
            <div
              ref={page}
              className="book-page min-w-0 flex-1 scroll-mt-4 rounded-b-[18px] border border-t-0 border-line px-4 pb-7 sm:px-6 md:rounded-l-none md:rounded-r-[18px] md:border-t md:border-l-0 md:px-10"
            >
              <Bookmarks decision={d} mark={mark} onMark={onMark} />
              <div
                role="tabpanel"
                id={`page-${mark}`}
                aria-labelledby={`mark-${mark}`}
                className="mt-7 max-w-[660px] md:mt-9"
              >
                {mark === "decision" && <DecisionPage decision={d} />}
                {mark === "revisit" && <RevisitPage decision={d} />}
                {mark === "facts" && <FactsPage decision={d} />}
                <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line pt-3 text-[13.5px] text-muted">
                  <span>Bookmark {BOOKMARKS.indexOf(mark) + 1} of 3</span>
                  <button
                    type="button"
                    onClick={() => goTo(NEXT_BOOKMARK[mark].to)}
                    className="ml-auto inline-flex items-center gap-1.5 font-semibold text-teal hover:underline"
                  >
                    {NEXT_BOOKMARK[mark].label}
                    <ArrowRight className="size-3.5" aria-hidden />
                  </button>
                </div>
              </div>
            </div>
          </article>
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

function BookCover({
  decision: d,
  cover,
  headingRef,
}: {
  decision: Decision;
  cover: number;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
}) {
  const Icon = ICONS[coverIcon(d)];
  const status = decisionStatus(d.status);
  return (
    <div
      className={`book-cover cover-${cover} flex shrink-0 flex-col gap-3 rounded-t-[6px] px-6 pt-7 pb-6 pl-10 md:w-[340px] md:rounded-tr-none md:rounded-l-[6px] md:pt-10 md:pb-8 md:pl-12 lg:w-[370px] md:min-h-[620px]`}
    >
      <Icon className="size-8 md:size-9" style={{ color: "var(--cover-icon)" }} strokeWidth={1.6} aria-hidden />
      <p className="mt-1 flex flex-wrap gap-2">
        <span className={`chip chip-dot ${tone(status.tone)}`}>{status.label}</span>
        {d.revisit.length > 0 && <span className="chip chip-gold chip-dot">To revisit</span>}
      </p>
      <h1
        ref={headingRef}
        id={`book-${d.id}`}
        tabIndex={-1}
        className="display mt-3 text-[23px] leading-[1.2] font-semibold outline-none md:mt-4 md:text-[28px]"
      >
        {d.question}
      </h1>
      <div className="mt-auto space-y-1 pt-6">
        <p className="text-[16px] italic md:text-[17px]" style={{ color: "var(--cover-ink)" }}>
          by {d.decided_by ?? "the household"}
        </p>
        <p className="text-[13.5px] text-white/75">
          Decided in{" "}
          <Link
            href={`/sessions/${d.session_id}`}
            className="underline decoration-white/40 underline-offset-4 hover:decoration-white"
            style={{ color: "var(--cover-icon)" }}
          >
            {d.session_title}
          </Link>
          {" · "}
          <span className="num">{formatDay(d.on)}</span>
        </p>
      </div>
    </div>
  );
}

/** The three bookmarks, on one row: tabs, the arrow keys moving between them. */
function Bookmarks({
  decision: d,
  mark,
  onMark,
}: {
  decision: Decision;
  mark: Bookmark;
  onMark: (mark: Bookmark) => void;
}) {
  const labels = bookmarkLabels(d);
  const short = phoneLabels(d);
  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const at = BOOKMARKS.indexOf(mark);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = BOOKMARKS[(at + step + BOOKMARKS.length) % BOOKMARKS.length];
    if (!next) return;
    event.preventDefault();
    onMark(next);
    document.getElementById(`mark-${next}`)?.focus();
  }
  return (
    <div
      role="tablist"
      aria-label="Bookmarks"
      onKeyDown={onKeyDown}
      className="-mt-px flex flex-nowrap items-start gap-2 overflow-x-auto sm:gap-3"
    >
      {BOOKMARKS.map((m) => {
        const on = m === mark;
        return (
          <button
            key={m}
            type="button"
            role="tab"
            id={`mark-${m}`}
            aria-selected={on}
            aria-controls={`page-${m}`}
            aria-label={labels[m]}
            tabIndex={on ? 0 : -1}
            onClick={() => onMark(m)}
            className={`ribbon ribbon-${m}`}
          >
            {m === "revisit" && d.revisit.length > 0 && !on && (
              <span aria-hidden className="mt-[5px] size-2 shrink-0 rounded-full bg-gold" />
            )}
            <span className="sm:hidden">{short[m]}</span>
            <span className="hidden sm:inline">{labels[m]}</span>
          </button>
        );
      })}
    </div>
  );
}

function DecisionPage({ decision: d }: { decision: Decision }) {
  const chosen = d.options.find((o) => o.chosen);
  const turnedDown = d.options.filter((o) => !o.chosen);
  const why = whyLine(d);
  const who = d.decided_by ?? "the household";
  return (
    <div className="space-y-5">
      <p className="eyebrow">What {who} chose</p>
      <div className="space-y-2.5 rounded-2xl border border-emerald/35 bg-emerald-soft px-5 py-4">
        <p className="text-[18px] font-bold">{chosen ? optionWords(chosen) : d.chosen}</p>
        {chosen && chosen.leans.length > 0 && (
          <p className="text-[14px] text-muted">Leans to: {chosen.leans.join(", ")}</p>
        )}
        {why && <p className="text-[15px]">{why}</p>}
        {d.quote && (
          <figure className="pt-1">
            <blockquote className="border-l-2 border-emerald pl-3.5 text-[16px] italic">
              &ldquo;{d.quote}&rdquo;
            </blockquote>
            <figcaption className="mt-1 pl-4 text-[13px] text-muted">
              {d.said_by ? `${d.said_by}, in ${d.session_title}` : d.session_title}
            </figcaption>
          </figure>
        )}
      </div>

      {turnedDown.length > 0 && (
        <>
          <p className="eyebrow pt-1">What was turned down</p>
          <ul className="space-y-3">
            {turnedDown.map((o) => (
              <li key={o.label} className="space-y-1 rounded-2xl border border-line px-5 py-4 text-muted">
                <p className="text-[16px] font-semibold">{optionWords(o)}</p>
                {o.leans.length > 0 && <p className="text-[14px]">Leans to: {o.leans.join(", ")}</p>}
                {o.reason && <p className="text-[14px]">Why not: {o.reason}</p>}
              </li>
            ))}
          </ul>
        </>
      )}

      {d.status !== "active" && (d.valid_to || d.replaced_by) && (
        <p className="text-[13.5px] text-muted">
          {d.valid_to && (
            <>
              In force until <span className="num">{formatDay(d.valid_to)}</span>.{" "}
            </>
          )}
          {d.replaced_by && (
            <Link href={bookHref(d.replaced_by)} className="text-teal underline-offset-4 hover:underline">
              Open the decision that replaced it
            </Link>
          )}
        </p>
      )}
      {d.outcome && (
        <p className="text-[14px]">
          <span className="text-muted">How it turned out: </span>
          {d.outcome}
        </p>
      )}
      {d.plan_id && (
        <Link href={`/plans/${d.plan_id}`} className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-teal hover:underline">
          <ClipboardList className="size-4" aria-hidden />
          The plan it accepted
        </Link>
      )}
    </div>
  );
}

function RevisitPage({ decision: d }: { decision: Decision }) {
  const n = d.revisit.length;
  return (
    <div className="space-y-5">
      <p className="eyebrow">What has moved since {formatDay(d.on)}</p>
      {n === 0 ? (
        <p className="rounded-2xl border border-line px-5 py-4 text-[15px] text-muted">
          {d.status === "active"
            ? "Nothing it rests on has changed since. It stands as decided."
            : "It is no longer in force, so nothing about it is marked to revisit."}
        </p>
      ) : (
        <div className="edge edge-gold relative space-y-5 rounded-2xl border bg-gold-soft px-5 py-5">
          <p className="text-[17px] font-bold">
            {n === 1
              ? "One fact this decision rests on has changed"
              : `${n} facts this decision rests on have changed`}
          </p>
          <ul className="space-y-5">
            {d.revisit.map((c, i) => {
              const parts = changedParts(c, d.rests_on);
              return (
                <li key={`${c.title}-${i}`} className="space-y-2">
                  <p className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <span className="chip chip-orange">{c.label}</span>
                    <span className="font-semibold">{parts.thing}</span>
                    {parts.words && <span className="text-muted">{parts.words}</span>}
                  </p>
                  <p className="num flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
                    {c.before && <span className="text-[19px] text-muted line-through">{c.before}</span>}
                    <ArrowRight className="size-4 shrink-0 self-center text-orange" aria-hidden />
                    <span className="sr-only">now</span>
                    <span className="display text-[24px]">{c.after ?? "no longer held"}</span>
                    {c.from_day && <span className="chip">from {c.from_day}</span>}
                  </p>
                </li>
              );
            })}
          </ul>
          <p className="text-[14px] text-muted">
            <Link href="/timeline" className="font-semibold text-teal hover:underline">
              See it on the timeline
            </Link>
          </p>
        </div>
      )}
    </div>
  );
}

function FactsPage({ decision: d }: { decision: Decision }) {
  const groups = factGroups(d.rests_on, d.revisit);
  const moved = d.rests_on.filter((r) => r.moved).length;
  const shared = sharedFrom(d.rests_on);
  const who = d.decided_by ?? "the household";
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2">
        <p className="eyebrow">What Kako held when {who} decided</p>
        {moved > 0 && <span className="chip chip-orange ml-auto">{moved} changed since</span>}
      </div>
      {groups.length === 0 ? (
        <p className="text-[15px] text-muted">No facts were kept as what it rests on.</p>
      ) : (
        <div className="gap-3.5 md:columns-2">
          {groups.map((g) => (
            <section
              key={g.kind}
              aria-label={g.label}
              className="mb-3.5 break-inside-avoid rounded-2xl border border-line bg-raised/60 px-4 pt-3 pb-1"
            >
              <p className="flex items-baseline justify-between gap-3 pb-1">
                <span className="font-bold">{g.label}</span>
                <span className="text-[12.5px] text-muted">{plural(g.count, "fact")}</span>
              </p>
              <ul>
                {g.things.map((t) => (
                  <li key={t.name} className="border-t border-line/70 py-2.5 text-[14px] first:border-t-0">
                    <p className="font-medium">{t.name}</p>
                    <ul className="num mt-1 space-y-1 text-[13.5px]">
                      {t.lines.map((l, i) =>
                        l.moved ? (
                          <li key={i} className="-mx-2 rounded-lg bg-orange-soft px-2 py-1">
                            <span className="block text-muted line-through">
                              {l.value}
                              {l.label && ` ${l.label}`}
                            </span>
                            {l.now?.value && (
                              <span className="block font-semibold text-orange">
                                now {l.now.value}
                                {l.now.from_day && ` from ${l.now.from_day}`}
                              </span>
                            )}
                          </li>
                        ) : (
                          <li key={i}>
                            <span className="font-semibold">{l.value}</span>
                            {l.label && <span className="text-muted"> {l.label}</span>}
                            {!shared && (
                              <span className="text-xs text-muted"> · from {formatDay(l.from)}</span>
                            )}
                          </li>
                        ),
                      )}
                    </ul>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
      <p className="text-[13px] text-muted">
        {shared && (
          <>
            Every value here held from <span className="num">{formatDay(shared)}</span>.{" "}
          </>
        )}
        Balances and the plan&rsquo;s own amounts move as the plan works, so a decision never rests on
        them.
      </p>
    </div>
  );
}

function NotOnShelf() {
  return (
    <>
      <TopBar phoneOnly />
      <main className="grid flex-1 place-items-center px-4">
        <div className="max-w-md space-y-3 text-center">
          <p className="display text-[20px]">That decision isn&rsquo;t on the shelf</p>
          <p className="text-muted">The link may be from another household or an older copy of the demo.</p>
          <Link href="/decisions" className="btn">
            <ArrowLeft className="size-4" aria-hidden />
            Back to the shelf
          </Link>
        </div>
      </main>
    </>
  );
}

function NoDecisions() {
  return (
    <div className="space-y-3 py-16 text-center">
      <p className="display text-[22px]">No decisions yet</p>
      <p className="mx-auto max-w-md text-muted">
        A decision is kept when an adult approves one of Kako&rsquo;s options in a session. It is
        shelved here as a book, and marked to revisit when a fact it rests on changes.
      </p>
      <Link href="/" className="btn btn-primary">
        New session
      </Link>
    </div>
  );
}

export function ShelfSkeleton() {
  return (
    <>
      <TopBar phoneOnly />
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label="Loading the decisions">
        <div className="mx-auto w-full max-w-6xl space-y-8 px-4 pt-8 md:px-8 md:pt-12">
          <div className="space-y-3">
            <div className="skeleton h-9 w-48" />
            <div className="skeleton h-4 w-2/3" />
          </div>
          <div className="flex gap-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-9 w-24 rounded-full" />
            ))}
          </div>
          <div className="grid grid-cols-2 items-end gap-4 pt-4 sm:flex sm:gap-7 sm:px-5">
            {[0, 1, 2].map((i) => (
              <div key={i} className={`skeleton w-full rounded-[4px_14px_14px_4px] sm:w-[236px] ${PHONE_HEIGHTS[i]} ${HEIGHTS[i]}`} />
            ))}
          </div>
          <div className="shelf-plank" />
        </div>
      </main>
    </>
  );
}
