"use client";

import { Gauge, Info, MessageSquare } from "lucide-react";
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { Failed, failure } from "@/components/plan-view";
import { HistorySkeleton } from "@/components/timeline-view";
import { TopBar } from "@/components/top-bar";
import { ApiError, api } from "@/lib/api";
import {
  GROUP_WORDS,
  allowanceWords,
  fill,
  modeWords,
  outcomeWords,
  pct,
  pointsBetween,
  usd4,
  whole,
} from "@/lib/metrics";
import { formatDay } from "@/lib/text";
import type { DatapackMetrics, Metrics, Spread, TurnGroup } from "@/lib/types";
import { plural } from "@/lib/working";

/** What Kako measured: each turn's cost and time, the brief against Meko's whole context, the
 * number check, the test set against one agent, what dreaming learned, and the Meko calls left. */
export function MetricsView() {
  const [view, setView] = useState<Loaded<Metrics>>({ kind: "loading" });
  const [meko, setMeko] = useState<MekoLoaded>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.metrics(controller.signal).then(
      (value) => setView({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setView({ kind: "error", message: failure(error, "the metrics") });
      },
    );
    api.mekoMetrics(controller.signal).then(
      (value) => setMeko({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // 503: Meko isn't running here or isn't set up. A note, not an error.
        if (error instanceof ApiError && error.status === 503)
          setMeko({ kind: "absent", message: error.message });
        else setMeko({ kind: "error", message: failure(error, "Meko's metrics") });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  if (view.kind === "loading") return <HistorySkeleton what="the metrics" />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const m = view.value;
  return (
    <>
      <TopBar>
        <h1 className="shrink-0 text-[15px] font-semibold">Metrics</h1>
        <span className="chip num ml-auto shrink-0">Measured {formatDay(m.measured_at)}</span>
      </TopBar>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-4xl space-y-10 px-4 pt-8 pb-10">
          <p className="text-[13.5px] text-muted">
            What Kako measured, from the rows it kept and the test runs it saved. Every figure here
            is worked out in code, like every figure Kako shows.
          </p>
          <Turns groups={m.turns} />
          <Brief metrics={m} meko={meko} />
          <Checks groups={m.turns} />
          <TestSets metrics={m} />
          <Learning metrics={m} />
          <MekoCalls metrics={m} />
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

function Section({
  id,
  title,
  note,
  children,
}: {
  id: string;
  title: string;
  note: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="space-y-4">
      <header className="space-y-1">
        <h2 id={id} className="display text-[18px]">
          {title}
        </h2>
        <p className="text-[13.5px] text-muted">{note}</p>
      </header>
      {children}
    </section>
  );
}

function Tile({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="panel min-w-0 space-y-1 px-4 py-3.5">
      <p className="text-[12.5px] text-muted">{label}</p>
      <p className="text-[22px] font-semibold leading-tight">{value}</p>
      {children && <div className="text-[12.5px] text-muted">{children}</div>}
    </div>
  );
}

function SessionLink({ spread }: { spread: Spread }) {
  return (
    <Link
      href={`/sessions/${spread.worst_session_id}`}
      className="inline-flex items-center gap-1 underline decoration-line-strong underline-offset-4 hover:text-fg hover:decoration-teal"
    >
      <MessageSquare className="size-3 shrink-0" aria-hidden />
      {spread.worst_title}, {spread.worst_seed}
    </Link>
  );
}

/** A labelled bar against 100: the score is its words, the bar only shows it. */
function Meter({
  label,
  value,
  note,
  muted = false,
}: {
  label: ReactNode;
  value: string | number | null;
  note?: ReactNode;
  muted?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <span className="text-[14px] font-medium">{label}</span>
        <span className="num ml-auto text-[15px] font-semibold">{pct(value)}</span>
      </div>
      <div
        className={`h-2 overflow-hidden rounded-full ${muted ? "bg-raised" : "bg-emerald-soft"}`}
        aria-hidden
      >
        <div
          className={`h-full rounded-full ${muted ? "bg-muted/60" : "bg-emerald"}`}
          style={{ width: `${fill(value)}%` }}
        />
      </div>
      {note && <p className="text-[12.5px] text-muted">{note}</p>}
    </div>
  );
}

const MEASURES: {
  key: "seconds" | "tokens" | "cost_usd" | "model_calls";
  label: string;
  shown: (v: string) => string;
}[] = [
  { key: "seconds", label: "Seconds", shown: (v) => `${v} s` },
  { key: "tokens", label: "Tokens", shown: whole },
  { key: "cost_usd", label: "Cost", shown: usd4 },
  { key: "model_calls", label: "Model calls", shown: (v) => v },
];

function Turns({ groups }: { groups: TurnGroup[] }) {
  const household = groups.find((g) => g.group === "household");
  const any = groups.some((g) => g.turns > 0);
  const replayed = groups.reduce((n, g) => n + g.replayed, 0);
  return (
    <Section
      id="metrics-turns"
      title="Each turn"
      note="The model calls, tokens, cost and seconds of one answer, on average and at worst. Seconds are model time as the turn ran it: the orchestrator's calls one after another, the specialists side by side."
    >
      {!any ? (
        <Nothing>
          No turn yet. Ask Kako something in a session, or run demo mode, and each answer&rsquo;s cost
          and time shows here.
        </Nothing>
      ) : (
        <>
          {household && household.turns > 0 && (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {MEASURES.map(({ key, label, shown }) => {
                const s = household[key];
                return (
                  <Tile key={key} label={`${label}, on average`} value={s ? shown(s.average) : "None"}>
                    {s && (
                      <>
                        Worst {shown(s.worst)}: <SessionLink spread={s} />
                      </>
                    )}
                  </Tile>
                );
              })}
            </div>
          )}
          <div className="panel overflow-x-auto p-0">
            <table className="num w-full min-w-[640px] text-[13.5px]">
              <caption className="sr-only">Each turn, by where it was asked: average and worst</caption>
              <thead>
                <tr className="text-left text-[12.5px] text-muted">
                  <th scope="col" className="px-4 py-2.5 font-medium">
                    Turns
                  </th>
                  {MEASURES.map((m) => (
                    <th key={m.key} scope="col" className="px-3 py-2.5 text-right font-medium">
                      {m.label}
                      <span className="block font-normal">average · worst</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map((g) => (
                  <tr key={g.group} className="border-t border-line align-top">
                    <th scope="row" className="px-4 py-2.5 text-left font-medium">
                      {GROUP_WORDS[g.group].label}
                      <span className="block text-[12.5px] font-normal text-muted">
                        {plural(g.turns, "turn")}, {GROUP_WORDS[g.group].note}
                      </span>
                    </th>
                    {MEASURES.map(({ key, shown }) => {
                      const s = g[key];
                      return (
                        <td key={key} className="px-3 py-2.5 text-right">
                          {s ? (
                            <>
                              {shown(s.average)}
                              <span className="block text-muted">{shown(s.worst)}</span>
                            </>
                          ) : (
                            <span className="text-muted">None</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[12.5px] text-muted">
            {replayed > 0
              ? `${plural(replayed, "turn")} replayed from recordings: their cost and seconds are the ones their recording took on the model that answered it. `
              : ""}
            Cached input tokens are billed at a small part of the price (a tenth on Foundry, a twentieth on
            Claude Opus)
            {household?.cached_pct ? `; ${household.cached_pct}% of the household's were cached` : ""}.
          </p>
        </>
      )}
    </Section>
  );
}

/** Meko's own metrics: read, being read, not there to ask, or failed. */
type MekoLoaded = Loaded<DatapackMetrics> | { kind: "absent"; message: string };

function Brief({ metrics, meko }: { metrics: Metrics; meko: MekoLoaded }) {
  const household = metrics.turns.find((g) => g.group === "household");
  const brief = household?.brief_tokens ?? null;
  return (
    <Section
      id="metrics-brief"
      title="The brief against the whole context"
      note="Every agent starts from one brief: the household's figures, facts and decisions, and what Meko's context search found. It is a small part of what Meko holds for the household."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="The brief, on average" value={brief ? `${whole(brief.average)} tokens` : "Not yet"}>
          {brief
            ? `Worst ${whole(brief.worst)}; budget ${whole(metrics.brief_budget)} (${plural(household?.brief_turns ?? 0, "turn")})`
            : `Kept on each turn from Nov 25; budget ${whole(metrics.brief_budget)}`}
        </Tile>
        {meko.kind === "ready" && (
          <>
            <Tile label="What Meko holds" value={`${whole(meko.value.context_tokens)} tokens`}>
              {whole(meko.value.knowledge.count)} documents, {whole(meko.value.memories.count)} memories,{" "}
              {whole(meko.value.conversations.count)} conversations
            </Tile>
            <Tile label="The brief's share of it" value={pct(meko.value.brief_pct_of_context)}>
              The average brief against the whole datapack
            </Tile>
          </>
        )}
        {meko.kind === "loading" && (
          <div className="skeleton h-[92px] sm:col-span-2" aria-label="Asking Meko for its metrics" />
        )}
        {meko.kind === "absent" && (
          <div className="panel text-[13.5px] sm:col-span-2">
            <p className="flex items-start gap-2">
              <Info className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
              <span>{meko.message}.</span>
            </p>
            <p className="mt-1 pl-6 text-muted">The rest of this page comes from Kako&rsquo;s own rows.</p>
          </div>
        )}
        {meko.kind === "error" && (
          <div role="alert" className="panel edge edge-rose text-[13.5px] sm:col-span-2">
            <p className="text-rose">Meko&rsquo;s own metrics couldn&rsquo;t be read. {meko.message}</p>
            <p className="mt-1 text-muted">The rest of this page comes from Kako&rsquo;s own rows.</p>
          </div>
        )}
      </div>
      {meko.kind === "ready" && (
        <div className="panel space-y-4">
          <p className="flex flex-wrap items-center gap-2 text-[13.5px]">
            <span className="chip chip-meko">
              <Gauge className="size-3.5" aria-hidden />
              Meko&rsquo;s datapack_metrics
            </span>
            <span className="text-muted">
              {meko.value.datapack_name ?? "The datapack"} on {meko.value.target === "cloud" ? "Meko Cloud" : "local Meko"},{" "}
              {plural(meko.value.searches, "search")} over the last {meko.value.days} days
            </span>
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Meter
              label="Context efficiency"
              value={meko.value.saved_pct}
              note={
                meko.value.tokens_sent !== null && meko.value.tokens_saved !== null
                  ? `Context search sent ${whole(meko.value.tokens_sent)} tokens instead of ${whole(meko.value.tokens_sent + meko.value.tokens_saved)}: the share saved.`
                  : "Measured once the datapack has been searched."
              }
            />
            <Meter
              label="Context relevance"
              value={meko.value.relevant_pct}
              note={
                meko.value.relevance_high !== null
                  ? `Search results scoring 0.5 or more: ${whole(meko.value.relevance_high ?? 0)} high, ${whole(meko.value.relevance_mid ?? 0)} mid, ${whole(meko.value.relevance_low ?? 0)} low.`
                  : "Measured once the datapack has been searched."
              }
            />
          </div>
        </div>
      )}
    </Section>
  );
}

function Checks({ groups }: { groups: TurnGroup[] }) {
  const checked = groups.filter((g) => g.checks.texts > 0);
  return (
    <Section
      id="metrics-checks"
      title="Every number checked"
      note="Each text the household reads is read for numbers, and each number must match a figure the engine worked out, a fact, or the household's own words. A text that fails is sent back once, then shown with the number flagged."
    >
      {checked.length === 0 ? (
        <Nothing>No text checked yet.</Nothing>
      ) : (
        <div className="panel space-y-4">
          {checked.map((g) => (
            <Meter
              key={g.group}
              label={GROUP_WORDS[g.group].label}
              value={g.checks.pass_pct}
              note={`${g.checks.passed} of ${plural(g.checks.texts, "text")} passed${g.checks.failed ? `, ${g.checks.failed} shown flagged` : ""}; ${g.checks.regenerated} ${g.checks.regenerated === 1 ? "first try" : "first tries"} sent back.`}
            />
          ))}
        </div>
      )}
    </Section>
  );
}

function TestSets({ metrics }: { metrics: Metrics }) {
  const { specialists, single, error } = metrics.test_set;
  return (
    <Section
      id="metrics-test-set"
      title="Specialists against one agent"
      note="The agent test set: 22 household questions, each answer scored in code against what it must hold. The same questions go to the orchestrator with four specialists and to one agent with every tool."
    >
      {error && <Unreadable message={error} />}
      {!error && !specialists && !single && (
        <Nothing>Not measured yet: run `kako test-set --save` for each architecture.</Nothing>
      )}
      {(specialists || single) && (
        <div className="panel space-y-4">
          {specialists && (
            <Meter
              label="Orchestrator and four specialists"
              value={specialists.score_pct}
              note={`${specialists.checks_passed} of ${specialists.checks_total} checks; ${whole(specialists.model_calls)} model calls, ${whole(specialists.tokens)} tokens, ${usd4(specialists.cost_usd)}; ${modeWords(specialists.mode)}, ${formatDay(specialists.run_at)}.`}
            />
          )}
          {single && (
            <Meter
              muted
              label="One agent (the baseline)"
              value={single.score_pct}
              note={`${single.checks_passed} of ${single.checks_total} checks; ${whole(single.model_calls)} model calls, ${whole(single.tokens)} tokens, ${usd4(single.cost_usd)}; ${modeWords(single.mode)}, ${formatDay(single.run_at)}.`}
            />
          )}
          {specialists && single && (
            <p className="text-[13.5px]">
              The specialists score{" "}
              <span className="num font-semibold">{pointsBetween(specialists.score_pct, single.score_pct)}</span> against one
              agent, with {whole(specialists.model_calls)} model calls against {whole(single.model_calls)}.
            </p>
          )}
        </div>
      )}
    </Section>
  );
}

function Learning({ metrics }: { metrics: Metrics }) {
  const { preference: p, dreaming: d, gaps } = metrics;
  return (
    <Section
      id="metrics-learning"
      title="What Kako learned, measured"
      note="Dreaming reads each finished session and proposes what the household said that Kako doesn't hold; across sessions it finds patterns, such as a preference. A person approves each one before it is shared."
    >
      <div className="panel space-y-4">
        <h3 className="text-[15px] font-semibold">The learned preference</h3>
        {p.error && <Unreadable message={p.error} />}
        {!p.error && !p.measured && (
          <p className="text-[13.5px] text-muted">
            Not measured yet: `kako test-set --without-preference --save` on a household that never
            learned it.
          </p>
        )}
        {p.measured && p.with_side && p.without_side && (
          <>
            <p className="text-[13.5px] text-muted">
              The test set&rsquo;s {plural(p.questions.length, "question")} whose good answer cites the
              household&rsquo;s preference for flexibility, learned from Sessions 1 to 3, answered with it
              and on a household that never learned it.
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-3">
                <Meter label="With the preference" value={p.with_side.score_pct} />
                <Meter muted label="Without it" value={p.without_side.score_pct} />
                <p className="text-[12.5px] text-muted">Every check</p>
              </div>
              <div className="space-y-3">
                <Meter label="With the preference" value={p.with_side.behaviour_pct} />
                <Meter muted label="Without it" value={p.without_side.behaviour_pct} />
                <p className="text-[12.5px] text-muted">Leaving out the check that cites it: what the answer does</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="num w-full min-w-[520px] text-[13.5px]">
                <caption className="sr-only">Each preference question with and without the preference</caption>
                <thead>
                  <tr className="text-left text-[12.5px] text-muted">
                    <th scope="col" className="py-2 pr-3 font-medium">Question</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">With</th>
                    <th scope="col" className="px-3 py-2 text-right font-medium">Without</th>
                    <th scope="col" className="py-2 pl-3 text-right font-medium">Cites it</th>
                  </tr>
                </thead>
                <tbody>
                  {p.questions.map((q) => (
                    <tr key={q.id} className="border-t border-line align-top">
                      <th scope="row" className="py-2 pr-3 text-left font-normal">
                        <span className="font-medium">{q.id}</span>{" "}
                        <span className="text-muted">{q.message}</span>
                      </th>
                      <td className="px-3 py-2 text-right">{pct(q.score_with_pct)}</td>
                      <td className="px-3 py-2 text-right">{pct(q.score_without_pct)}</td>
                      <td className="py-2 pl-3 text-right text-muted">
                        {q.cited_with ? "Yes" : "No"} · {q.cited_without ? "yes" : "no"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-[12.5px] text-muted">
              With: {modeWords(p.with_side.mode)}, {formatDay(p.with_side.run_at)}. Without:{" "}
              {modeWords(p.without_side.mode)}, {formatDay(p.without_side.run_at)}, {usd4(p.without_side.cost_usd)}. One
              run each, so one question moves a score by several points.
            </p>
          </>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="panel space-y-3">
          <h3 className="text-[15px] font-semibold">Dreaming&rsquo;s labelled set</h3>
          {d.error ? (
            <Unreadable message={d.error} />
          ) : d.score_pct === null ? (
            <p className="text-[13.5px] text-muted">Not measured yet: `kako dream eval --save`.</p>
          ) : (
            <Meter
              label="Proposals found"
              value={d.score_pct}
              note={`${d.found} of ${d.expected} expected; ${plural(d.wrong ?? 0, "wrong proposal")}, ${plural(d.unquoted ?? 0, "number")} without a quote; ${modeWords(d.eval_mode)}, ${d.eval_at ? formatDay(d.eval_at) : ""}.`}
            />
          )}
          <p className="text-[12.5px] text-muted">
            In this household: {plural(d.runs_done, "dreaming run")} done
            {d.runs_failed ? `, ${d.runs_failed} failed` : ""}
            {d.runs_waiting ? `, ${d.runs_waiting} waiting` : ""}; {plural(d.proposals, "proposal")} made.
          </p>
        </div>
        <div className="panel space-y-3">
          <h3 className="text-[15px] font-semibold">Context Gaps, before and after</h3>
          {gaps.total === 0 ? (
            <p className="text-[13.5px] text-muted">
              No gap yet. Meko Cloud logs each weak search; once an answer is approved and in Meko, the search is
              replayed and its score before and after shows here. Local Meko has no search log.
            </p>
          ) : (
            <>
              <p className="text-[13.5px]">
                {plural(gaps.total, "gap")}; {gaps.replayed} replayed, {gaps.improved} improved.
              </p>
              <ul className="space-y-2">
                {gaps.gaps.slice(0, 6).map((g) => {
                  const o = outcomeWords(g.verify_outcome);
                  return (
                    <li key={g.query} className="flex flex-wrap items-baseline gap-x-2 text-[13.5px]">
                      <span className="min-w-0 flex-1">&ldquo;{g.query}&rdquo;</span>
                      <span className="num text-muted">
                        {g.score_before}
                        {g.score_after !== null ? ` → ${g.score_after}` : ""}
                      </span>
                      <span className={`chip ${o.tone === "plain" ? "" : `chip-${o.tone}`}`}>{o.label}</span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>
      </div>
    </Section>
  );
}

function MekoCalls({ metrics }: { metrics: Metrics }) {
  const { target, allowances } = metrics.meko_calls;
  return (
    <Section
      id="metrics-meko-calls"
      title="Meko calls left"
      note={
        <>
          Meko Cloud&rsquo;s Free tier allows each of these a fixed number of calls for the account&rsquo;s
          lifetime. Kako counts every call before it is sent and refuses one past this environment&rsquo;s
          ceiling. Calls go to {target === "cloud" ? "Meko Cloud" : "local Meko"} now; the count is this
          database&rsquo;s, not the account&rsquo;s.
        </>
      }
    >
      <div className="panel overflow-x-auto p-0">
        <table className="num w-full min-w-[560px] text-[13.5px]">
          <caption className="sr-only">Meko calls by Free-tier allowance</caption>
          <thead>
            <tr className="text-left text-[12.5px] text-muted">
              <th scope="col" className="px-4 py-2.5 font-medium">Allowance</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Local Meko</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Meko Cloud</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Ceiling</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Left</th>
            </tr>
          </thead>
          <tbody>
            {allowances.map((a) => (
              <tr key={a.name} className="border-t border-line">
                <th scope="row" className="px-4 py-2.5 text-left font-medium">
                  {allowanceWords(a.name)}
                  <span className="block text-[12.5px] font-normal text-muted">
                    Free tier {whole(a.free)}
                  </span>
                </th>
                <td className="px-3 py-2.5 text-right">{whole(a.local_used)}</td>
                <td className="px-3 py-2.5 text-right">{whole(a.cloud_used)}</td>
                <td className="px-3 py-2.5 text-right">{whole(a.cloud_ceiling)}</td>
                <td className={`px-4 py-2.5 text-right font-semibold ${a.cloud_ceiling > 0 && a.cloud_left === 0 ? "text-rose" : ""}`}>
                  {whole(a.cloud_left)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12.5px] text-muted">
        The ceiling is KAKO_MEKO_CLOUD_CEILING, never above the Free tier&rsquo;s own allowance; at 0, nothing
        capped can be sent to Meko Cloud.
      </p>
    </Section>
  );
}

function Nothing({ children }: { children: ReactNode }) {
  return <p className="panel text-[13.5px] text-muted">{children}</p>;
}

function Unreadable({ message }: { message: string }) {
  return (
    <p role="alert" className="panel edge edge-rose text-[13.5px] text-rose">
      A saved result can&rsquo;t be read: {message}
    </p>
  );
}
