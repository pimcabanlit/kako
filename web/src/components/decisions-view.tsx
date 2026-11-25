"use client";

import { ChevronDown, ClipboardList, MessageSquare } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { ChangedFactRow, Failed, failure } from "@/components/plan-view";
import { HistorySkeleton } from "@/components/timeline-view";
import { TopBar } from "@/components/top-bar";
import { api } from "@/lib/api";
import { decidedLine, decisionAnchor, decisionStatus, quoteOf } from "@/lib/history";
import { formatDay, optionParts } from "@/lib/text";
import type { Decision, DecisionOption, Decisions } from "@/lib/types";
import type { Tone } from "@/lib/words";
import { plural } from "@/lib/working";

function tone(t: Tone): string {
  return t === "plain" ? "" : `chip-${t}`;
}

/** Every decision the household made, newest first: what it chose and turned down, and why, the
 * facts it rests on, and what has moved under it since. */
export function DecisionsView() {
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

  // The timeline links to one decision (#decision-<id>); it is on the page only once loaded.
  useEffect(() => {
    if (view.kind !== "ready" || !window.location.hash) return;
    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    target?.scrollIntoView({ block: "start" });
    target?.focus({ preventScroll: true });
  }, [view.kind]);

  if (view.kind === "loading") return <HistorySkeleton what="the decisions" />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const { decisions, as_of } = view.value;
  const toRevisit = decisions.filter((d) => d.revisit.length > 0).length;
  return (
    <>
      <TopBar>
        <h1 className="shrink-0 text-[15px] font-semibold">Decisions</h1>
        {toRevisit > 0 && (
          <span className="chip chip-gold chip-dot shrink-0">{toRevisit} to revisit</span>
        )}
        <span className="chip num ml-auto hidden shrink-0 sm:inline-flex">
          Household date {formatDay(as_of)}
        </span>
      </TopBar>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-6 px-4 pt-8 pb-10">
          {decisions.length === 0 ? (
            <NoDecisions />
          ) : (
            <>
              <p className="text-[13.5px] text-muted">
                Every choice the household made, newest first: what it chose, what it turned down
                and why, and the facts it rested on. When one of those facts has changed since, the
                decision is marked to revisit.
              </p>
              {decisions.map((d) => (
                <DecisionCard key={d.id} decision={d} />
              ))}
            </>
          )}
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

function DecisionCard({ decision: d }: { decision: Decision }) {
  const status = decisionStatus(d.status);
  const quote = quoteOf(d);
  const revisit = d.revisit.length > 0;
  const headingId = `${decisionAnchor(d.id)}-q`;
  return (
    <article
      id={decisionAnchor(d.id)}
      tabIndex={-1}
      aria-labelledby={headingId}
      className={`panel scroll-mt-6 space-y-4 text-[14px] outline-none ${revisit ? "edge edge-gold" : ""}`}
    >
      <header className="space-y-2">
        <p className="flex flex-wrap items-center gap-2">
          <span className={`chip chip-dot ${tone(status.tone)}`}>{status.label}</span>
          {revisit && <span className="chip chip-gold chip-dot">To revisit</span>}
        </p>
        <h2 id={headingId} className="display text-[17px] leading-snug">
          &ldquo;{d.question}&rdquo;
        </h2>
        <p className="num text-[13px] text-muted">
          {decidedLine(d)}
          {" · "}
          <Link href={`/sessions/${d.session_id}`} className="inline-flex items-center gap-1 underline decoration-line-strong underline-offset-4 hover:text-fg hover:decoration-teal">
            <MessageSquare className="size-3.5" aria-hidden />
            the session
          </Link>
          {d.plan_id && (
            <>
              {" · "}
              <Link href={`/plans/${d.plan_id}`} className="inline-flex items-center gap-1 underline decoration-line-strong underline-offset-4 hover:text-fg hover:decoration-teal">
                <ClipboardList className="size-3.5" aria-hidden />
                the plan
              </Link>
            </>
          )}
        </p>
      </header>

      {revisit && (
        <section className="space-y-2 rounded-2xl border border-gold/30 bg-gold-soft px-3.5 py-3" aria-label="To revisit">
          <p>
            <span className="font-semibold">To revisit.</span>{" "}
            {d.revisit.length === 1 ? "A fact it rests on has" : "Facts it rests on have"} changed
            since it was made:
          </p>
          <ul className="space-y-1.5">
            {d.revisit.map((c, i) => (
              <ChangedFactRow key={`${c.title}-${i}`} fact={c} />
            ))}
          </ul>
        </section>
      )}

      <ul className="space-y-2.5" aria-label="The options">
        {d.options.map((o) => (
          <OptionRow key={o.label} option={o} reasoning={o.chosen ? d.reasoning : null} />
        ))}
      </ul>

      {quote && (
        <figure className="space-y-1">
          <blockquote className="quote">&ldquo;{quote}&rdquo;</blockquote>
          {d.said_by && <figcaption className="pl-3.5 text-xs text-muted">{d.said_by}</figcaption>}
        </figure>
      )}

      {d.status !== "active" && (
        <p className="text-[13px] text-muted">
          {d.valid_to && <>In force until <span className="num">{formatDay(d.valid_to)}</span>. </>}
          {d.replaced_by && (
            <Link href={`#${decisionAnchor(d.replaced_by)}`} className="underline decoration-line-strong underline-offset-4 hover:text-fg">
              The decision that replaced it
            </Link>
          )}
        </p>
      )}
      {d.outcome && <p className="text-[13px]"><span className="text-muted">How it turned out: </span>{d.outcome}</p>}

      <RestsOnList decision={d} />
    </article>
  );
}

function OptionRow({ option, reasoning }: { option: DecisionOption; reasoning: string | null }) {
  const { letter, words } = optionParts(option.label);
  return (
    <li
      className={`flex gap-3 rounded-2xl border px-3.5 py-3 ${
        option.chosen ? "border-emerald/30 bg-emerald-soft" : "border-line bg-surface/70"
      }`}
    >
      {letter && (
        <span className="display grid size-7 shrink-0 place-items-center rounded-lg border border-line-strong bg-raised text-[13px]">
          {letter}
        </span>
      )}
      <div className="min-w-0 flex-1 space-y-1.5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold">{words}</span>
          {option.chosen ? (
            <span className="chip chip-emerald chip-dot">Chosen</span>
          ) : (
            <span className="chip chip-rose chip-dot">Not chosen</span>
          )}
        </p>
        {option.leans.length > 0 && (
          <p className="text-xs text-muted">Leans: {option.leans.join(", ")}</p>
        )}
        {reasoning && <p>{reasoning}</p>}
        {!option.chosen && option.reason && (
          <p className="text-[13.5px]">
            <span className="text-muted">Why not: </span>
            {option.reason}
          </p>
        )}
      </div>
    </li>
  );
}

function RestsOnList({ decision: d }: { decision: Decision }) {
  if (d.rests_on.length === 0)
    return <p className="text-[13px] text-muted">No facts were kept as what it rests on.</p>;
  const moved = d.rests_on.filter((r) => r.moved).length;
  return (
    <details className="group rounded-2xl border border-line bg-surface/70">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[13.5px] [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-4 shrink-0 -rotate-90 text-muted transition-transform group-open:rotate-0" aria-hidden />
        <span>
          <span className="font-semibold">Rests on {plural(d.rests_on.length, "fact")}</span>
          {moved > 0 && <span className="text-muted">, {moved} changed since</span>}
        </span>
      </summary>
      <div className="border-t border-line px-3.5 pt-3 pb-3.5">
        <p className="mb-2.5 text-xs text-muted">
          The household&rsquo;s figures when it chose, as Kako held them. Balances and the plan&rsquo;s
          own amounts move as the plan works, so a decision doesn&rsquo;t rest on them.
        </p>
        <ul className="space-y-2">
          {d.rests_on.map((r, i) => (
            <li key={`${r.title}-${i}`} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-[13.5px]">
              <span className="min-w-0">
                {r.title}
                {r.moved && <span className="chip chip-orange chip-dot ml-2 align-middle">Changed</span>}
              </span>
              <span className="num">
                <span className="font-semibold">{r.value}</span>
                <span className="text-xs text-muted"> from {formatDay(r.valid_from)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

function NoDecisions() {
  return (
    <div className="space-y-3 py-16 text-center">
      <p className="display text-[22px]">No decisions yet</p>
      <p className="mx-auto max-w-md text-muted">
        A decision is kept when an adult approves one of Kako&rsquo;s options in a session. It shows
        here with the options it turned down, and is marked to revisit when its facts change.
      </p>
      <Link href="/" className="btn btn-primary">
        New session
      </Link>
    </div>
  );
}
