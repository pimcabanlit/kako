"use client";

import {
  ClipboardList,
  FileText,
  Flag,
  type LucideIcon,
  MessageSquare,
  Milestone,
  Scale,
  Undo2,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { ChangedFactRow, Failed, failure } from "@/components/plan-view";
import { TopBar } from "@/components/top-bar";
import { api } from "@/lib/api";
import { byDay, type Day, eventHref, valueState, windowWords } from "@/lib/history";
import { formatDay } from "@/lib/text";
import type { Thing, Timeline, TimelineEvent } from "@/lib/types";
import type { Tone } from "@/lib/words";

type Tab = "events" | "things";

const TABS: { id: Tab; label: string }[] = [
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

const THING_KIND: Record<string, string> = {
  household: "The household",
  income: "Income",
  expense: "Spending",
  debt: "Debt",
  account: "Savings",
  goal: "Goal",
};

function tone(t: Tone): string {
  return t === "plain" ? "" : `chip-${t}`;
}

/** The household's story: what happened, newest first, and each thing's values over time. */
export function TimelineView() {
  const [view, setView] = useState<Loaded<Timeline>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<Tab>("events");

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

  if (view.kind === "loading") return <HistorySkeleton what="the timeline" />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const timeline = view.value;
  return (
    <>
      <TopBar>
        <h1 className="shrink-0 text-[15px] font-semibold">Timeline</h1>
        <span className="chip num hidden shrink-0 sm:inline-flex">
          Household date {formatDay(timeline.as_of)}
        </span>
        <div role="tablist" aria-label="Timeline views" className="ml-auto flex shrink-0 rounded-full border border-line bg-raised p-0.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`panel-${t.id}`}
              onClick={() => setTab(t.id)}
              className={`rounded-full px-3 py-1 text-[13px] font-semibold whitespace-nowrap transition-colors ${
                tab === t.id ? "bg-bg text-fg ring-1 ring-line-strong" : "text-muted hover:text-fg"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </TopBar>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div
          role="tabpanel"
          id={`panel-${tab}`}
          aria-labelledby={`tab-${tab}`}
          className="mx-auto w-full max-w-3xl space-y-8 px-4 pt-8 pb-10"
        >
          {timeline.events.length === 0 && timeline.things.length === 0 ? (
            <Empty />
          ) : tab === "events" ? (
            <WhatHappened timeline={timeline} />
          ) : (
            <EachThing timeline={timeline} />
          )}
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

// --- What happened ---------------------------------------------------------------------------

function WhatHappened({ timeline }: { timeline: Timeline }) {
  const { ahead, past } = byDay(timeline.events);
  return (
    <>
      <p className="text-[13.5px] text-muted">
        What happened to the household and what Kako made of it, newest first, each on the day it
        took effect. Nothing is overwritten: a replaced figure keeps its old value, and a mistake
        stays with its correction.
      </p>
      {ahead.length > 0 && (
        <section aria-labelledby="ahead" className="panel edge edge-orange space-y-4">
          <div>
            <h2 id="ahead" className="display text-[18px]">
              Ahead of the household&rsquo;s date
            </h2>
            <p className="mt-0.5 text-[13px] text-muted">
              Approved already, and true from the day shown. Until then the household&rsquo;s
              figures stay as they are on <span className="num">{formatDay(timeline.as_of)}</span>.
            </p>
          </div>
          <Days days={ahead} />
        </section>
      )}
      {past.length > 0 && (
        <section aria-labelledby="happened" className="space-y-4">
          <h2 id="happened" className="display text-[18px]">
            What happened
          </h2>
          <Days days={past} />
        </section>
      )}
    </>
  );
}

function Days({ days }: { days: Day[] }) {
  return (
    <ol className="space-y-6">
      {days.map((d) => (
        <li key={d.on} className="space-y-3">
          <h3 className="num flex items-center gap-3 text-[13px] font-semibold text-muted">
            {formatDay(d.on)}
            <span className="h-px flex-1 bg-line" aria-hidden />
          </h3>
          <ul className="space-y-4">
            {d.events.map((e, i) => (
              <EventRow key={`${e.kind}-${e.ref ?? e.title}-${i}`} event={e} />
            ))}
          </ul>
        </li>
      ))}
    </ol>
  );
}

function EventRow({ event }: { event: TimelineEvent }) {
  const kind = KIND[event.kind] ?? { label: event.kind, tone: "plain" as Tone, icon: FileText };
  const Icon = kind.icon;
  const href = eventHref(event);
  // A life event's detail is its kind ("New job"), so it names the chip.
  const label = event.kind === "life_event" && event.detail ? event.detail : kind.label;
  // A plan's status and a session's turns read best beside its name.
  const inline = (event.kind === "plan" || event.kind === "session") && event.detail !== null;
  return (
    <li className="flex gap-3">
      <span className={`chip ${tone(kind.tone)} size-8 shrink-0 justify-center rounded-lg p-0`} aria-hidden>
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1 space-y-1.5 text-[14px]">
        <p className="flex flex-wrap items-center gap-2">
          <span className={`chip ${tone(kind.tone)}`}>{label}</span>
          {event.revisit && href && (
            <Link href={href} className="chip chip-gold chip-dot hover:underline">
              To revisit
            </Link>
          )}
        </p>
        <p>
          <span className="font-semibold">
            {href ? (
              <Link href={href} className="underline decoration-line-strong underline-offset-4 hover:decoration-teal">
                {event.kind === "decision" ? <>&ldquo;{event.title}&rdquo;</> : event.title}
              </Link>
            ) : (
              event.title
            )}
          </span>
          {inline && <span className="num text-muted"> · {event.detail}</span>}
        </p>
        {!inline && <Detail event={event} />}
        {event.changes.length > 0 && (
          <ul className="space-y-1.5 pt-0.5">
            {event.changes.map((c, i) => (
              <ChangedFactRow key={`${c.title}-${i}`} fact={c} />
            ))}
          </ul>
        )}
        {event.source && <p className="text-xs text-muted">{event.source}</p>}
      </div>
    </li>
  );
}

function Detail({ event }: { event: TimelineEvent }) {
  if (!event.detail || event.kind === "life_event") return null;
  if (event.kind === "change")
    return <span className="chip chip-meko chip-dot">{event.detail}</span>;
  if (event.kind === "correction")
    return <p className="quote">Why: {event.detail}</p>;
  return <p className="num text-muted">{event.detail}</p>;
}

// --- Each thing over time --------------------------------------------------------------------

function EachThing({ timeline }: { timeline: Timeline }) {
  return (
    <>
      <p className="text-[13.5px] text-muted">
        Everything the household has, and the household itself, with each value it has held: when
        it held, where it came from and who approved it. On{" "}
        <span className="num">{formatDay(timeline.as_of)}</span>, the household&rsquo;s date,
        each value is current, coming, past or corrected.
      </p>
      <ul className="space-y-4">
        {timeline.things.map((t) => (
          <ThingPanel key={t.id ?? "household"} thing={t} />
        ))}
      </ul>
    </>
  );
}

function ThingPanel({ thing }: { thing: Thing }) {
  const opened = thing.opened_on ? `Opened ${formatDay(thing.opened_on)}` : null;
  const closed = thing.closed_on ? `closed ${formatDay(thing.closed_on)}` : null;
  return (
    <li className="panel space-y-3 text-[14px]" aria-label={thing.name}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="display text-[16px]">{thing.name}</h2>
        {thing.kind !== "household" && (
          <span className="text-xs text-muted">
            {THING_KIND[thing.kind] ?? thing.kind}
            {opened && <span className="num">, {opened.toLowerCase()}</span>}
            {closed && <span className="num">, {closed}</span>}
          </span>
        )}
      </header>
      {thing.attributes.length === 0 ? (
        <p className="text-muted">No values kept for it.</p>
      ) : (
        <ul className="divide-y divide-line">
          {thing.attributes.map((a) => (
            <li key={a.attribute} className="space-y-2 py-2.5 first:pt-0 last:pb-0">
              <h3 className="text-[13px] text-muted first-letter:uppercase">{a.words}</h3>
              <ul className="space-y-2.5">
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
                        <span className="num text-[13px] text-muted">{windowWords(v)}</span>
                        <span className={`chip chip-dot ml-auto ${tone(state.tone)}`}>{state.label}</span>
                      </div>
                      {v.reason && <p className="text-[13px] text-rose">Corrected: {v.reason}</p>}
                      <p className="text-xs text-muted">{v.source}</p>
                      {v.shared_on && (
                        <p className="pt-0.5">
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
    </li>
  );
}

// --- States ----------------------------------------------------------------------------------

/** Loading the timeline or the decisions. */
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
