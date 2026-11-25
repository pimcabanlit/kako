"use client";

import {
  ArrowUpRight,
  ChevronRight,
  ClipboardList,
  Clock,
  CreditCard,
  FileText,
  Flag,
  House,
  type LucideIcon,
  MessageSquare,
  Milestone,
  PiggyBank,
  Receipt,
  Scale,
  Target,
  Undo2,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { DetailSheet } from "@/components/detail-sheet";
import { PageHeader, type View, ViewChips } from "@/components/page-header";
import { ChangedFactRow, Failed, failure } from "@/components/plan-view";
import { TopBar } from "@/components/top-bar";
import { api } from "@/lib/api";
import {
  byKind,
  byMonth,
  eventHref,
  eventLine,
  type Month,
  thingCard,
  valueState,
  windowWords,
} from "@/lib/history";
import { formatDay } from "@/lib/text";
import type { Thing, Timeline, TimelineEvent } from "@/lib/types";
import type { Tone } from "@/lib/words";

type Tab = "events" | "things";

const TABS: readonly View<Tab>[] = [
  { id: "events", label: "What happened" },
  { id: "things", label: "Each thing" },
];

const KIND: Record<string, { label: string; tone: Tone; icon: LucideIcon }> = {
  start: { label: "Start", tone: "plain", icon: Flag },
  life_event: { label: "Life event", tone: "orange", icon: Milestone },
  correction: { label: "Correction", tone: "rose", icon: Undo2 },
  decision: { label: "Decision", tone: "emerald", icon: Scale },
  change: { label: "Facts", tone: "plain", icon: FileText },
  plan: { label: "Plan", tone: "plain", icon: ClipboardList },
  session: { label: "Session", tone: "plain", icon: MessageSquare },
};

const THING_KIND: Record<string, { label: string; icon: LucideIcon }> = {
  household: { label: "The household", icon: House },
  income: { label: "Income", icon: Wallet },
  expense: { label: "Spending", icon: Receipt },
  debt: { label: "Debt", icon: CreditCard },
  account: { label: "Savings", icon: PiggyBank },
  goal: { label: "Goal", icon: Target },
};

const OPENS: Record<string, string> = {
  plan: "Open the plan",
  session: "Open the session",
  decision: "Open it on the decisions screen",
};

function tone(t: Tone): string {
  return t === "plain" ? "" : `chip-${t}`;
}

function kindOf(event: TimelineEvent) {
  return KIND[event.kind] ?? { label: event.kind, tone: "plain" as Tone, icon: FileText };
}

type Opened = { type: "event"; event: TimelineEvent } | { type: "thing"; thing: Thing } | null;

/** The household's story: what happened, newest first, and each thing it holds. A clean list
 * and cards first; each one's details open in a sheet. */
export function TimelineView() {
  const [view, setView] = useState<Loaded<Timeline>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<Tab>("events");
  const [opened, setOpened] = useState<Opened>(null);

  useEffect(() => {
    const controller = new AbortController();
    api.timeline(controller.signal).then(
      (value) => setView({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setView({ kind: "error", message: failure(error, "the timeline") });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  if (view.kind === "loading") return <TimelineSkeleton />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const timeline = view.value;
  const empty = timeline.events.length === 0 && timeline.things.length === 0;
  return (
    <>
      <TopBar phoneOnly />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl space-y-7 px-4 pt-8 pb-10 md:px-8 md:pt-12">
          <PageHeader
            title="Timeline"
            note={
              <>
                The household&rsquo;s story as Kako holds it on{" "}
                <span className="num">{formatDay(timeline.as_of)}</span>, the household&rsquo;s
                date. Nothing is overwritten.
              </>
            }
          >
            {!empty && (
              <ViewChips label="Timeline views" views={TABS} chosen={tab} onChoose={setTab} />
            )}
          </PageHeader>
          {empty ? (
            <Empty />
          ) : (
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
              {tab === "events" ? (
                <WhatHappened
                  timeline={timeline}
                  onOpen={(event) => setOpened({ type: "event", event })}
                />
              ) : (
                <EachThing
                  timeline={timeline}
                  onOpen={(thing) => setOpened({ type: "thing", thing })}
                />
              )}
            </div>
          )}
          <Disclaimer />
        </div>
      </main>
      <DetailSheet
        open={opened !== null}
        label={
          opened?.type === "event"
            ? opened.event.title
            : opened?.type === "thing"
              ? opened.thing.name
              : "Details"
        }
        onClose={() => setOpened(null)}
      >
        {opened?.type === "event" && <EventDetails event={opened.event} />}
        {opened?.type === "thing" && <ThingDetails thing={opened.thing} asOf={timeline.as_of} />}
      </DetailSheet>
    </>
  );
}

// --- What happened ---------------------------------------------------------------------------

function WhatHappened({
  timeline,
  onOpen,
}: {
  timeline: Timeline;
  onOpen: (event: TimelineEvent) => void;
}) {
  const ahead = timeline.events.filter((e) => e.ahead);
  const past = timeline.events.filter((e) => !e.ahead);
  return (
    <div className="space-y-8">
      {ahead.length > 0 && (
        <section aria-labelledby="ahead" className="space-y-2">
          <h2 id="ahead" className="eyebrow">
            Ahead of <span className="num">{formatDay(timeline.as_of)}</span>
          </h2>
          <p className="text-[13px] text-muted">
            Approved already, and true from the day shown.
          </p>
          <EventList events={ahead} onOpen={onOpen} />
        </section>
      )}
      {byMonth(past).map((m: Month) => (
        <section key={m.key} aria-labelledby={`month-${m.key}`} className="space-y-2">
          <h2 id={`month-${m.key}`} className="eyebrow">
            {m.label}
          </h2>
          <EventList events={m.events} onOpen={onOpen} />
        </section>
      ))}
    </div>
  );
}

function EventList({
  events,
  onOpen,
}: {
  events: TimelineEvent[];
  onOpen: (event: TimelineEvent) => void;
}) {
  return (
    <ul className="divide-y divide-line/70">
      {events.map((e, i) => (
        <li key={`${e.kind}-${e.ref ?? e.title}-${e.on}-${i}`}>
          <EventRow event={e} onOpen={() => onOpen(e)} />
        </li>
      ))}
    </ul>
  );
}

function EventRow({ event, onOpen }: { event: TimelineEvent; onOpen: () => void }) {
  const kind = kindOf(event);
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-haspopup="dialog"
      className="group -mx-3 flex w-[calc(100%+1.5rem)] items-center gap-3.5 rounded-2xl px-3 py-3 text-left transition-colors hover:bg-raised/70"
    >
      <IconTile icon={kind.icon} tone={kind.tone} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-semibold">
          {event.kind === "decision" ? <>&ldquo;{event.title}&rdquo;</> : event.title}
        </span>
        <span className="num block truncate text-[13px] text-muted">
          {eventLine(event).join(" · ")}
        </span>
      </span>
      {event.revisit && <span className="chip chip-gold chip-dot shrink-0">To revisit</span>}
      {event.ahead && <span className="chip chip-orange chip-dot shrink-0">Coming</span>}
      <ChevronRight
        className="size-4 shrink-0 text-muted transition-transform group-hover:translate-x-0.5"
        aria-hidden
      />
    </button>
  );
}

function EventDetails({ event }: { event: TimelineEvent }) {
  const kind = kindOf(event);
  const href = eventHref(event);
  // A life event's detail is its kind ("New job"), so it names the chip.
  const label = event.kind === "life_event" && event.detail ? event.detail : kind.label;
  return (
    <article className="space-y-6 text-[14px]">
      <header className="space-y-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <IconTile icon={kind.icon} tone={kind.tone} />
          <span className={`chip ${tone(kind.tone)}`}>{label}</span>
          {event.ahead && <span className="chip chip-orange chip-dot">Coming</span>}
          {event.revisit && <span className="chip chip-gold chip-dot">To revisit</span>}
        </div>
        <h2 className="display text-[22px] leading-snug">
          {event.kind === "decision" ? <>&ldquo;{event.title}&rdquo;</> : event.title}
        </h2>
        <p className="num text-[13.5px] text-muted">{eventLine(event).join(" · ")}</p>
      </header>
      <Detail event={event} />
      {event.changes.length > 0 && (
        <section className="space-y-2.5">
          <h3 className="eyebrow">{event.kind === "correction" ? "The correction" : "What changed"}</h3>
          <ul className="space-y-2.5">
            {event.changes.map((c, i) => (
              <ChangedFactRow key={`${c.title}-${i}`} fact={c} />
            ))}
          </ul>
        </section>
      )}
      {event.source && (
        <section className="space-y-1.5">
          <h3 className="eyebrow">Where it came from</h3>
          <p>{event.source}</p>
        </section>
      )}
      {event.revisit && (
        <p className="panel edge edge-gold text-[13.5px]">
          Something this decision rested on has changed since, so it is worth a second look.
        </p>
      )}
      {href && (
        <Link href={href} className="btn px-3.5 py-2 text-[14px]">
          {OPENS[event.kind] ?? "Open"}
          <ArrowUpRight className="size-4" aria-hidden />
        </Link>
      )}
    </article>
  );
}

function Detail({ event }: { event: TimelineEvent }) {
  if (!event.detail || event.kind === "life_event") return null;
  if (event.kind === "change")
    return <span className="chip chip-meko chip-dot">{event.detail}</span>;
  if (event.kind === "correction") return <p className="quote">Why: {event.detail}</p>;
  if (event.kind === "decision") return <p className="text-[15px] font-semibold">{event.detail}</p>;
  return <p className="num text-muted">{event.detail}</p>;
}

// --- Each thing ------------------------------------------------------------------------------

function EachThing({ timeline, onOpen }: { timeline: Timeline; onOpen: (thing: Thing) => void }) {
  return (
    <div className="space-y-8">
      {byKind(timeline.things).map((g) => (
        <section key={g.kind} aria-labelledby={`kind-${g.kind}`} className="space-y-3">
          <h2 id={`kind-${g.kind}`} className="eyebrow">
            {g.label}
          </h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {g.things.map((t) => (
              <li key={t.id ?? "household"} className="min-w-0">
                <ThingCardButton thing={t} onOpen={() => onOpen(t)} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ThingCardButton({ thing, onOpen }: { thing: Thing; onOpen: () => void }) {
  const kind = THING_KIND[thing.kind] ?? { label: thing.kind, icon: FileText };
  const card = thingCard(thing);
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-haspopup="dialog"
      className="flex h-full w-full items-start gap-3.5 rounded-[14px] border border-line bg-surface/60 p-4 text-left transition-colors hover:border-line-strong hover:bg-raised/70"
    >
      <IconTile icon={kind.icon} tone="plain" />
      <span className="min-w-0 flex-1 space-y-1">
        <span className="block truncate text-[15px] font-semibold">{thing.name}</span>
        <span className="line-clamp-2 block text-[13.5px] text-muted">
          {card.value !== null && (
            <span className="num font-semibold text-fg">{card.value} </span>
          )}
          {card.words}
        </span>
        <span className="num flex flex-wrap items-center gap-x-2 gap-y-1 pt-1 text-[12.5px] text-muted">
          {card.meta && (
            <span className="inline-flex items-center gap-1.5">
              <Clock className="size-3.5" aria-hidden />
              {card.meta}
            </span>
          )}
          {card.coming && (
            <span className="chip chip-orange chip-dot">Changes {formatDay(card.coming)}</span>
          )}
          {card.corrected && <span className="chip chip-rose chip-dot">Corrected</span>}
        </span>
      </span>
    </button>
  );
}

function ThingDetails({ thing, asOf }: { thing: Thing; asOf: string }) {
  const kind = THING_KIND[thing.kind] ?? { label: thing.kind, icon: FileText };
  const dates = [
    thing.opened_on ? `Opened ${formatDay(thing.opened_on)}` : null,
    thing.closed_on ? `closed ${formatDay(thing.closed_on)}` : null,
  ].filter((d) => d !== null);
  return (
    <article className="space-y-6 text-[14px]">
      <header className="space-y-3">
        <div className="flex items-center gap-2.5">
          <IconTile icon={kind.icon} tone="plain" />
          <span className="chip">{kind.label}</span>
        </div>
        <h2 className="display text-[22px] leading-snug">{thing.name}</h2>
        <p className="num text-[13.5px] text-muted">
          {dates.length > 0 && <>{dates.join(", ")}. </>}
          Each value it has held, and its state on {formatDay(asOf)}.
        </p>
      </header>
      {thing.attributes.length === 0 ? (
        <p className="text-muted">No values kept for it.</p>
      ) : (
        <ul className="space-y-5">
          {thing.attributes.map((a) => (
            <li key={a.attribute} className="space-y-2.5">
              <h3 className="text-[13px] font-semibold text-muted first-letter:uppercase">
                {a.words}
              </h3>
              <ul className="space-y-3 border-l border-line pl-4">
                {a.values.map((v) => {
                  const state = valueState(v.state);
                  const gone = v.state === "past" || v.state === "corrected";
                  return (
                    <li key={v.id} className="space-y-0.5">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className={`num font-semibold ${gone ? "text-muted" : ""}`}>
                          {v.state === "corrected" ? (
                            <s className="decoration-[1.5px]">{v.value}</s>
                          ) : (
                            v.value
                          )}
                        </span>
                        <span className={`chip chip-dot ml-auto ${tone(state.tone)}`}>
                          {state.label}
                        </span>
                      </div>
                      <p className="num text-[13px] text-muted">{windowWords(v)}</p>
                      {v.reason && <p className="text-[13px] text-rose">Corrected: {v.reason}</p>}
                      <p className="text-xs text-muted">{v.source}</p>
                      {v.shared_on && (
                        <p className="pt-1">
                          <span className="chip chip-meko chip-dot num">
                            Shared with every agent in Meko on {formatDay(v.shared_on)}
                          </span>
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

// --- Shared pieces and states ----------------------------------------------------------------

function IconTile({ icon: Icon, tone: t }: { icon: LucideIcon; tone: Tone }) {
  return (
    <span
      className={`grid size-10 shrink-0 place-items-center rounded-xl border ${
        t === "plain" ? "border-line bg-raised text-fg" : `chip-${t}`
      }`}
      aria-hidden
    >
      <Icon className="size-[18px]" />
    </span>
  );
}

function TimelineSkeleton() {
  return (
    <>
      <TopBar phoneOnly />
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label="Loading the timeline">
        <div className="mx-auto w-full max-w-4xl space-y-7 px-4 pt-8 md:px-8 md:pt-12">
          <div className="space-y-3">
            <div className="skeleton h-9 w-44" />
            <div className="skeleton h-4 w-2/3" />
          </div>
          <div className="flex gap-2">
            <div className="skeleton h-9 w-32 rounded-full" />
            <div className="skeleton h-9 w-28 rounded-full" />
          </div>
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3.5">
              <div className="skeleton size-10 shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="skeleton h-4 w-1/2" />
                <div className="skeleton h-3.5 w-1/3" />
              </div>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}

/** Loading the decisions or the metrics. */
export function HistorySkeleton({ what }: { what: string }) {
  return (
    <>
      <TopBar>
        <div className="skeleton h-5 w-32" />
      </TopBar>
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label={`Loading ${what}`}>
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 pt-8">
          <div className="skeleton h-4 w-2/3" />
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex gap-3">
              <div className="skeleton size-8 shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="skeleton h-4 w-1/3" />
                <div className="skeleton h-4 w-5/6" />
                <div className="skeleton h-4 w-1/2" />
              </div>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}

function Empty() {
  return (
    <div className="space-y-3 py-16 text-center">
      <p className="display text-[22px]">Nothing yet</p>
      <p className="mx-auto max-w-md text-muted">
        The household&rsquo;s story starts with its first figures. Once Kako holds them, every
        change, life event, decision and correction shows here on the day it took effect.
      </p>
    </div>
  );
}
