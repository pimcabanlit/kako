"use client";

import {
  ArrowRight,
  ChevronDown,
  CircleAlert,
  CircleX,
  ExternalLink,
  MessageSquare,
  Plus,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type ReactNode, useEffect, useId, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { BeforeAfter, ComparePanels, type MonthsOpen, useCompare, useMonthsOpen } from "@/components/compare-view";
import { Disclaimer } from "@/components/composer";
import { TopBar } from "@/components/top-bar";
import { KakoMark, PersonMessage, Text } from "@/components/turn";
import { api, ApiError } from "@/lib/api";
import {
  builtFrom,
  checkTally,
  factsBehind,
  millis,
  planStatus,
  versionLabel,
} from "@/lib/plan";
import { formatDay, optionParts } from "@/lib/text";
import type {
  ChangedFact,
  DecisionWhy,
  FactWhy,
  Plan,
  PlanChanged,
  PlanOption,
  PlanSummary,
  PlanTurn,
  Reconciliation,
} from "@/lib/types";
import { listOf, plural } from "@/lib/working";

type View = Loaded<Plan> | { kind: "missing" };

// How many of the figures that moved "what changed" shows before "more".
const MOVED_SHOWN = 6;
// How deep "built from" opens figures inside figures before it stops.
const MAX_DEPTH = 5;

/** What a screen says when a read fails: the API's own words, or a plain line. */
export function failure(error: unknown, what: string): string {
  if (error instanceof ApiError) return error.message;
  console.error(`Reading ${what} failed`, error);
  return `Couldn't read ${what}.`;
}

/** The household's newest plan (the plan screen's home), or why there is none yet. */
export function LatestPlan() {
  const [plans, setPlans] = useState<Loaded<PlanSummary[]>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api.plans(controller.signal).then(
      (value) => setPlans({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setPlans({ kind: "error", message: failure(error, "the plans") });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  if (plans.kind === "loading") return <PlanSkeleton />;
  if (plans.kind === "error")
    return <Failed message={plans.message} onRetry={() => setAttempt((n) => n + 1)} />;
  if (plans.value.length === 0) return <NoPlan />;
  return <PlanView id={plans.value[0].id} />;
}

/** One plan: what Kako proposed, why (down to the facts), the number check, the turn and its
 * Meko calls, and what changed against the last plan or decision. */
export function PlanView({ id }: { id: string }) {
  const [view, setView] = useState<View>({ kind: "loading" });
  const [versions, setVersions] = useState<PlanSummary[]>([]);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.plan(id, controller.signal).then(
      (value) => setView({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
          setView({ kind: "missing" });
          return;
        }
        setView({ kind: "error", message: failure(error, "this plan") });
      },
    );
    // The other versions, for the picker; without them the plan still shows.
    api.plans(controller.signal).then(setVersions, () => setVersions([]));
    return () => controller.abort();
  }, [id, attempt]);

  if (view.kind === "loading") return <PlanSkeleton />;
  if (view.kind === "missing") return <Missing />;
  if (view.kind === "error")
    return <Failed message={view.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const plan = view.value;
  const head = plan.plan;
  const status = planStatus(head.status);
  return (
    <>
      <TopBar>
        <h1 className="shrink-0 text-[15px] font-semibold">Plan v{head.version}</h1>
        <span className={`chip chip-dot shrink-0 ${status.tone === "plain" ? "" : `chip-${status.tone}`}`}>
          {status.label}
        </span>
        <span className="chip num hidden shrink-0 sm:inline-flex">From {formatDay(head.as_of)}</span>
        <div className="ml-auto min-w-0">
          {versions.length > 1 && <VersionPicker current={head.id} versions={versions} />}
        </div>
      </TopBar>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-10 px-4 pt-8 pb-10">
          <Summary plan={plan} />
          <Changed changed={plan.changed} />
          <section aria-labelledby="options" className="space-y-4">
            <h2 id="options" className="display text-[18px]">
              {plan.options.length === 1
                ? "The option"
                : plan.options.length > 1
                  ? `The ${plan.options.length} options`
                  : "Options"}
            </h2>
            {plan.options.length === 0 && (
              <p className="text-muted">This plan holds no options.</p>
            )}
            <PlanOptions plan={plan} />
          </section>
          {plan.reconciliations.length > 0 && (
            <Reconciliations items={plan.reconciliations} />
          )}
          <TurnPanel turn={plan.turn} />
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

function VersionPicker({ current, versions }: { current: string; versions: PlanSummary[] }) {
  const router = useRouter();
  const pickerId = useId();
  return (
    <div className="relative flex items-center">
      <label htmlFor={pickerId} className="sr-only">
        Version
      </label>
      <select
        id={pickerId}
        value={current}
        onChange={(e) => router.push(`/plans/${e.target.value}`)}
        className="num w-[7.5rem] appearance-none truncate rounded-full border border-line bg-raised py-1.5 pr-8 pl-3 text-[13px] font-semibold text-fg hover:border-line-strong sm:w-auto"
      >
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            {versionLabel(v)}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 size-4 text-muted" aria-hidden />
    </div>
  );
}

function Summary({ plan }: { plan: Plan }) {
  const { turn, plan: head } = plan;
  return (
    <section className="space-y-4" aria-label="The plan">
      <p className="text-[13px] text-muted">
        Proposed {turn.said_by ? `when ${turn.said_by} asked ` : ""}in{" "}
        <Link href={`/sessions/${head.session_id}`} className="font-semibold text-fg underline decoration-line-strong underline-offset-4 hover:decoration-teal">
          {head.session_title}
        </Link>
        , for the household&rsquo;s figures from <span className="num">{formatDay(head.as_of)}</span>.
      </p>
      <div className="flex gap-3">
        <KakoMark />
        <Text text={plan.summary} className="min-w-0 flex-1 text-[15px] leading-7" />
      </div>
    </section>
  );
}

// --- What changed ---------------------------------------------------------------------------

function Changed({ changed }: { changed: PlanChanged | null }) {
  if (changed === null)
    return (
      <section className="rounded-2xl border border-line bg-surface/70 px-4 py-3 text-[14px]" aria-label="What changed">
        <h2 className="font-semibold">What changed</h2>
        <p className="mt-0.5 text-muted">
          This is the household&rsquo;s first plan, and no decision came before it, so there is
          nothing earlier to compare it with.
        </p>
      </section>
    );
  const shown = changed.figures.slice(0, MOVED_SHOWN);
  const more = changed.figures.slice(MOVED_SHOWN);
  const nothing = changed.figures.length === 0 && changed.facts.length === 0;
  return (
    <section className="panel edge edge-orange space-y-4 text-[14px]" aria-labelledby="changed">
      <div>
        <h2 id="changed" className="display text-[18px]">
          What changed
        </h2>
        <p className="mt-0.5 text-[13px] text-muted">
          Since{" "}
          {changed.since_plan ? (
            <Link href={`/plans/${changed.since_plan}`} className="underline decoration-line-strong underline-offset-4 hover:text-fg hover:decoration-teal">
              {changed.since}
            </Link>
          ) : (
            changed.since
          )}
        </p>
      </div>
      {nothing && <p>Nothing moved: the figures and the facts behind them are the same.</p>}
      {shown.length > 0 && <Moved figures={shown} />}
      {more.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-[13px] text-muted hover:text-fg">
            {plural(more.length, "more figure")} moved
          </summary>
          <div className="mt-2">
            <Moved figures={more} />
          </div>
        </details>
      )}
      {changed.facts.length > 0 && (
        <div>
          <h3 className="eyebrow mb-2">The facts behind it</h3>
          <ul className="space-y-2">
            {changed.facts.map((f, i) => (
              <ChangedFactRow key={`${f.title}-${i}`} fact={f} />
            ))}
          </ul>
        </div>
      )}
      {changed.revisit.length > 0 && (
        <div>
          <h3 className="eyebrow mb-2">Decisions to revisit</h3>
          <ul className="space-y-3">
            {changed.revisit.map((r) => (
              <li key={r.decision_id} className="space-y-1">
                <p className="flex flex-col items-start gap-1 sm:flex-row sm:gap-2">
                  <span className="chip chip-gold chip-dot shrink-0">To revisit</span>
                  <span className="min-w-0">&ldquo;{r.question}&rdquo;</span>
                </p>
                <p className="text-[13px] text-muted">
                  You chose {r.chosen} in {r.session_title}, on{" "}
                  <span className="num">{formatDay(r.decided_on)}</span>.
                  {r.because.length > 0 && <> It rested on {listOf(r.because.map((b) => b.title))}, which changed.</>}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** The figures that moved, before and now. One grid, so the values line up; on a phone each
 * figure's name sits above its two values. */
function Moved({ figures }: { figures: PlanChanged["figures"] }) {
  return (
    <ul className="num grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 text-[14px] sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:gap-x-3">
      {figures.map((f, i) => (
        <li key={`${f.title}-${i}`} className="contents">
          <span className="col-span-2 pt-1.5 text-muted sm:col-span-1 sm:py-1">{f.title}</span>
          <span className="pb-1.5 whitespace-nowrap text-muted sm:py-1 sm:text-right">
            <span className="sr-only">was </span>
            {f.before.startsWith("none") ? f.before : <s className="decoration-[1.5px]">{f.before}</s>}
          </span>
          <span className="pb-1.5 whitespace-nowrap sm:py-1 sm:text-right">
            <ArrowRight className="mr-1.5 inline size-3.5 -translate-y-px text-orange" aria-hidden />
            <span className="sr-only">now </span>
            <span className="font-semibold">{f.after}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

// Changed is orange; a corrected mistake is rose (docs/look-and-feel.md).
const FACT_TONE: Record<string, string> = {
  replaced: "chip-orange",
  corrected: "chip-rose",
  new: "chip-orange",
  ended: "chip-orange",
};

export function ChangedFactRow({ fact }: { fact: ChangedFact }) {
  return (
    <li className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-2">
      <span className={`chip shrink-0 ${FACT_TONE[fact.label] ?? ""}`}>{fact.label}</span>
      <span className="num min-w-0">
        {fact.title}
        {": "}
        {fact.before !== null && (
          <>
            <s className="text-muted decoration-[1.5px]">{fact.before}</s>
            {fact.after !== null && <span className="text-muted"> → </span>}
          </>
        )}
        {fact.after !== null && <span className="font-semibold">{fact.after}</span>}
        {fact.from_day && <span className="text-muted">, from {fact.from_day}</span>}
      </span>
    </li>
  );
}

// --- An option and its why ------------------------------------------------------------------

/** The plan's options, each set beside today's plan, then the comparison and the months. */
function PlanOptions({ plan }: { plan: Plan }) {
  const compared = useCompare(plan.options.length > 0 ? plan.plan.id : null);
  const months = useMonthsOpen();
  return (
    <>
      {plan.options.map((o) => (
        <OptionPanel key={o.label} option={o} plan={plan} compared={compared} months={months} />
      ))}
      <ComparePanels state={compared} months={months} />
    </>
  );
}

function OptionPanel({
  option,
  plan,
  compared,
  months,
}: {
  option: PlanOption;
  plan: Plan;
  compared: ReturnType<typeof useCompare>;
  months: MonthsOpen;
}) {
  const { letter, words } = optionParts(option.label);
  const { why } = option;
  const facts = [...new Set([...why.facts, ...factsBehind(why.figures, plan.figures)])];
  const tally = checkTally(option.checks);
  // A document Kako read from its own files is not Meko's: it shows apart, without violet.
  const documents = why.memories.filter((m) => m.kind === "document");
  const fromMeko = why.memories.filter((m) => m.kind !== "document");
  const rests = [
    why.figures.length ? plural(why.figures.length, "figure") : null,
    facts.length ? plural(facts.length, "fact") : null,
    why.decisions.length ? plural(why.decisions.length, "decision") : null,
    fromMeko.length ? `${fromMeko.length} from Meko` : null,
    documents.length ? plural(documents.length, "document") : null,
  ].filter((p): p is string => p !== null);
  return (
    <article
      className={`panel space-y-4 ${option.recommended ? "edge edge-emerald" : ""}`}
      aria-label={`Option ${option.label}`}
    >
      <header className="flex items-start gap-3">
        {letter && (
          <span className="display grid size-8 shrink-0 place-items-center rounded-lg border border-line-strong bg-raised text-[15px]">
            {letter}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h3 className="display text-[16px] leading-snug">{words}</h3>
          {option.recommended && <span className="chip chip-emerald chip-dot mt-1.5">Recommended</span>}
        </div>
      </header>
      <p className="text-[14px] text-fg/90">{option.summary}</p>
      {option.allocations.length > 0 && (
        <table className="num w-full text-[14px]">
          <caption className="eyebrow pb-1.5 text-left">Each month</caption>
          <tbody>
            {option.allocations.map((a) => (
              <tr key={a.recommendation_id} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted">
                  {a.name}
                </th>
                <td className="py-1.5 text-right font-semibold">{a.shown}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <BeforeAfter state={compared} label={option.label} months={months} />
      {option.specialists.length > 0 && (
        <p className="text-xs text-muted">
          From the {listOf(option.specialists)}{" "}
          {option.specialists.length === 1 ? "specialist" : "specialists"}
        </p>
      )}
      <details open={option.recommended} className="group rounded-2xl border border-line bg-surface/70">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[13.5px] [&::-webkit-details-marker]:hidden">
          <ChevronDown className="size-4 shrink-0 -rotate-90 text-muted transition-transform group-open:rotate-0" aria-hidden />
          <span className="font-semibold">Why</span>
          <span className="num min-w-0 truncate text-muted">
            {rests.length ? `Rests on ${listOf(rests)}` : "No sources kept"}
            {tally.numbers > 0 &&
              ` · ${tally.flagged ? `${tally.flagged} of ${tally.numbers} numbers flagged` : `all ${plural(tally.numbers, "number")} checked`}`}
          </span>
        </summary>
        <div className="space-y-6 border-t border-line px-3.5 pt-4 pb-4 text-[14px]">
          {why.figures.length > 0 && (
            <WhySection title="The figures it cites" note="Each one worked out by Kako's engine; open one to see how, down to the facts it read.">
              <ul className="space-y-3">
                {why.figures.map((f) => (
                  <FigureRow key={f} id={f} plan={plan} path={[]} />
                ))}
              </ul>
            </WhySection>
          )}
          {why.facts.length > 0 && (
            <WhySection title="The facts it cites">
              <ul className="space-y-2.5">
                {why.facts.map((f) => (
                  <FactRow key={f} fact={plan.facts[f]} />
                ))}
              </ul>
            </WhySection>
          )}
          {why.decisions.length > 0 && (
            <WhySection title="Decisions it rests on">
              <ul className="space-y-3">
                {why.decisions.map((d) => (
                  <DecisionRow key={d.id} decision={d} />
                ))}
              </ul>
            </WhySection>
          )}
          {documents.length > 0 && (
            <WhySection title="From documents">
              <ul className="space-y-2.5">
                {documents.map((m, i) => (
                  <li key={`${m.source_id}-${i}`} className="space-y-1">
                    <span className="chip font-medium">
                      Document: {m.source_id.replace(/^file:/, "").replace(/-/g, " ")}
                    </span>
                    {m.quote && <p className="quote line-clamp-4">{m.quote}</p>}
                  </li>
                ))}
              </ul>
            </WhySection>
          )}
          {fromMeko.length > 0 && (
            <WhySection title="From Meko">
              <ul className="space-y-2.5">
                {fromMeko.map((m, i) => {
                  const kept = m.fact_id ? plan.facts[m.fact_id] : undefined;
                  return (
                    <li key={`${m.source_id}-${i}`} className="space-y-1">
                      <span className="chip chip-meko chip-dot">
                        {m.kind === "knowledge" ? "Meko knowledge" : "Meko memory"}
                      </span>
                      {m.quote && <p className="quote">{m.quote}</p>}
                      <p className="text-xs text-muted">
                        {kept ? <>Kept for: {kept.title}. </> : null}
                        <span className="font-mono">{m.source_id}</span>
                      </p>
                    </li>
                  );
                })}
              </ul>
            </WhySection>
          )}
          {why.words.length > 0 && (
            <WhySection title="In your words">
              <ul className="space-y-2">
                {why.words.map((w, i) => (
                  <li key={i}>
                    <p className="quote">&ldquo;{w.quote}&rdquo;</p>
                    {w.said_by && <p className="mt-1 pl-3.5 text-xs text-muted">{w.said_by}</p>}
                  </li>
                ))}
              </ul>
            </WhySection>
          )}
          <NumberCheck option={option} />
        </div>
      </details>
    </article>
  );
}

function WhySection({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div>
        <h4 className="eyebrow">{title}</h4>
        {note && <p className="mt-0.5 text-xs text-muted">{note}</p>}
      </div>
      {children}
    </section>
  );
}

/** A figure, and how it was worked out: its formula in words, the figures it was built from (each
 * openable the same way), and the facts it read. */
function FigureRow({ id, plan, path }: { id: string; plan: Plan; path: string[] }) {
  const figure = plan.figures[id];
  if (!figure) return null;
  const from = builtFrom(figure);
  const again = path.includes(id) || path.length >= MAX_DEPTH;
  const flag = figure.flag && !figure.value.includes(figure.flag) ? figure.flag : null;
  return (
    <li className="space-y-1">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="min-w-0">{figure.title}</span>
        <span className="num font-semibold">{figure.value}</span>
      </div>
      {flag && <span className="chip chip-dot">{flag}</span>}
      {figure.what_if && path.length === 0 && (
        <p className="num text-xs text-muted">In the option&rsquo;s what-if: {figure.what_if}</p>
      )}
      {!again && (
        <details className="group/fig">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12.5px] text-muted hover:text-fg [&::-webkit-details-marker]:hidden">
            <ChevronDown className="size-3.5 shrink-0 -rotate-90 transition-transform group-open/fig:rotate-0" aria-hidden />
            How it&rsquo;s worked out{from ? `, from ${from}` : ""}
          </summary>
          <div className="mt-2 space-y-3 border-l border-line-strong pl-3.5">
            <p className="text-[13.5px]">
              {figure.formula_words}{" "}
              <code className="font-mono text-[11.5px] text-teal">{figure.formula}</code>
            </p>
            {figure.inputs.length > 0 && (
              <ul className="space-y-2.5">
                {figure.inputs.map((input) => (
                  <FigureRow key={input} id={input} plan={plan} path={[...path, id]} />
                ))}
              </ul>
            )}
            {figure.facts.length > 0 && (
              <ul className="space-y-2.5">
                {figure.facts.map((f) => (
                  <FactRow key={f} fact={plan.facts[f]} />
                ))}
              </ul>
            )}
          </div>
        </details>
      )}
    </li>
  );
}

const STATUS_NOW: Record<string, string> = {
  replaced: "Replaced since",
  retracted: "Corrected since",
};

/** A fact: its value (with the one it replaced, struck), where it came from and who approved it,
 * and whether it is shared with every agent in Meko. */
function FactRow({ fact }: { fact: FactWhy | undefined }) {
  if (!fact) return null;
  return (
    <li className="space-y-0.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <span className="min-w-0 text-[13.5px]">{fact.title}</span>
        <span className="num text-[13.5px]">
          {fact.replaced && (
            <>
              <s className="text-muted decoration-[1.5px]">{fact.replaced}</s>{" "}
            </>
          )}
          <span className="font-semibold">{fact.value}</span>
        </span>
      </div>
      <p className="num text-xs text-muted">
        {fact.source}. From {formatDay(fact.valid_from)}
        {fact.valid_to ? ` to ${formatDay(fact.valid_to)}` : ""}.
      </p>
      {(fact.shared || STATUS_NOW[fact.status]) && (
        <p className="flex flex-wrap gap-1.5 pt-0.5">
          {fact.shared && <span className="chip chip-meko chip-dot">{fact.shared}</span>}
          {STATUS_NOW[fact.status] && <span className="chip">{STATUS_NOW[fact.status]}</span>}
        </p>
      )}
    </li>
  );
}

function DecisionRow({ decision }: { decision: DecisionWhy }) {
  return (
    <li className="space-y-1.5">
      <p>&ldquo;{decision.question}&rdquo;</p>
      <p className="flex flex-wrap items-center gap-2">
        <span className="chip chip-emerald chip-dot">Chosen</span>
        <span>{decision.chosen}</span>
      </p>
      {decision.reasoning && <p className="quote">{decision.reasoning}</p>}
      {decision.rejected.map((r) => (
        <p key={r.label} className="flex flex-wrap items-baseline gap-2 text-[13.5px]">
          <span className="chip">Not chosen</span>
          <span>
            {r.label}
            {r.reason && <span className="text-muted">: {r.reason}</span>}
          </span>
        </p>
      ))}
      <p className="text-xs text-muted">
        {decision.session_title}, <span className="num">{formatDay(decision.on)}</span>
        {decision.status !== "active" && `, ${decision.status}`}
      </p>
    </li>
  );
}

/** What the number check matched each number in the option's texts to. It confirms each number
 * is one Kako's engine, a fact, the option's amount or the household's words produced; it does
 * not judge what the sentence says about it. */
function NumberCheck({ option }: { option: PlanOption }) {
  if (option.checks.length === 0)
    return (
      <WhySection title="The number check">
        <p className="text-[13.5px] text-muted">No number check was kept for this option&rsquo;s texts.</p>
      </WhySection>
    );
  return (
    <WhySection
      title="The number check"
      note="Every number in Kako's words was matched to a figure, a fact, the option's amount or the household's own words with that value. It checks each number exists, not what the sentence says about it."
    >
      <ul className="space-y-3">
        {option.checks.map((c, i) => (
          <li key={i} className="space-y-1.5">
            <p className="quote">{c.text}</p>
            {c.numbers.length > 0 ? (
              <ul className="space-y-1 pl-3.5">
                {c.numbers.map((n, j) => (
                  <li key={j} className="grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-2 text-[13px]">
                    <span className="num font-semibold">{n.text}</span>
                    {n.matched ? (
                      <span className="text-muted">
                        <span aria-hidden>→ </span>
                        <span className="sr-only">matched </span>
                        {n.matched}
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-rose">
                        <CircleAlert className="size-3.5 shrink-0" aria-hidden />
                        Matched nothing, so it was flagged
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="pl-3.5 text-[13px] text-muted">No numbers in it.</p>
            )}
          </li>
        ))}
      </ul>
    </WhySection>
  );
}

// --- How it was reconciled, and the turn ----------------------------------------------------

function Reconciliations({ items }: { items: Reconciliation[] }) {
  return (
    <section className="panel space-y-3 text-[14px]" aria-labelledby="reconciled">
      <h2 id="reconciled" className="display text-[18px]">
        How Kako weighed the specialists
      </h2>
      <ul className="space-y-3">
        {items.map((r, i) => (
          <li key={i} className="space-y-1">
            <p className="flex flex-wrap items-center gap-2">
              <span className="chip chip-rose chip-dot">{r.kind.replace(/_/g, " ")}</span>
              <span className="text-muted">
                between the {listOf(r.specialists)} specialists, {plural(r.attempts, "split")} tried
              </span>
            </p>
            <p>{r.resolution}</p>
            {r.rejected && <p className="text-[13px] text-muted">Rejected: {r.rejected}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TurnPanel({ turn }: { turn: PlanTurn }) {
  return (
    <section className="panel space-y-4 text-[14px]" aria-labelledby="turn">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="turn" className="display text-[18px]">
          The turn that proposed it
        </h2>
        <Link href={`/sessions/${turn.session_id}`} className="btn btn-ghost px-2.5 py-1 text-[13px] text-muted">
          <MessageSquare className="size-3.5" aria-hidden />
          Show the working in the session
        </Link>
      </div>
      {turn.message && <PersonMessage name={turn.said_by} text={turn.message} />}
      <div className="space-y-2">
        <h3 className="eyebrow">Meko</h3>
        {!turn.in_meko ? (
          <p className="text-muted">Meko was off for this session, so the turn is kept only in Kako.</p>
        ) : (
          <>
            {turn.meko_calls.length === 0 ? (
              <p className="text-muted">No Meko calls were logged for this turn.</p>
            ) : (
              <ul className="divide-y divide-line">
                {turn.meko_calls.map((c, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1.5 text-[13px]">
                    <code className="font-mono text-[12.5px] text-meko">{c.tool}</code>
                    <span className="font-mono text-[12px] text-muted">{c.agent_id}</span>
                    <span className="num ml-auto flex gap-3 text-muted">
                      {c.results !== null && <span>{plural(c.results, "result")}</span>}
                      {millis(c.ms) && <span>{millis(c.ms)}</span>}
                      {c.outcome !== "ok" && <span className="text-rose">{c.outcome}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {turn.trace_url ? (
              <a href={turn.trace_url} target="_blank" rel="noreferrer" className="chip chip-meko chip-dot hover:underline">
                Open the trace on Meko Cloud
                <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : (
              <p className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
                <span className="chip chip-meko chip-dot">Kept in Meko</span>
                This Meko has no trace page; on Meko Cloud a link to the turn&rsquo;s trace shows here.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

// --- States ---------------------------------------------------------------------------------

export function PlanSkeleton() {
  return (
    <>
      <TopBar>
        <div className="skeleton h-5 w-40" />
      </TopBar>
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label="Loading the plan">
        <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pt-8">
          <div className="skeleton h-4 w-2/3" />
          <div className="space-y-2.5">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-11/12" />
            <div className="skeleton h-4 w-3/4" />
          </div>
          <div className="skeleton h-44" />
          <div className="skeleton h-64" />
        </div>
      </main>
    </>
  );
}

export function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <>
      <TopBar />
      <main className="grid flex-1 place-items-center px-4">
        <div role="alert" className="panel edge edge-rose max-w-md space-y-3 text-sm">
          <p className="flex items-start gap-2 text-rose">
            <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />
            {message}
          </p>
          <button type="button" className="btn px-3 py-1.5 text-sm" onClick={onRetry}>
            <RefreshCw className="size-3.5" aria-hidden />
            Try again
          </button>
        </div>
      </main>
    </>
  );
}

function NoPlan() {
  return (
    <>
      <TopBar>
        <h1 className="text-[15px] font-semibold">Plan</h1>
      </TopBar>
      <main className="grid flex-1 place-items-center px-4 text-center">
        <div className="max-w-md space-y-3">
          <p className="display text-[22px]">No plan yet</p>
          <p className="text-muted">
            A plan is kept when Kako answers a planning question with options. Ask one in a
            session, and its why and what changed show here.
          </p>
          <Link href="/" className="btn btn-primary">
            <Plus className="size-4" aria-hidden />
            New session
          </Link>
        </div>
      </main>
      <div className="px-4 pb-4">
        <Disclaimer />
      </div>
    </>
  );
}

function Missing() {
  return (
    <>
      <TopBar />
      <main className="grid flex-1 place-items-center px-4 text-center">
        <div className="space-y-3">
          <p className="display text-[22px]">No such plan</p>
          <p className="text-muted">It may belong to another household, or the link is wrong.</p>
          <Link href="/plans" className="btn btn-primary">
            The latest plan
          </Link>
        </div>
      </main>
      <div className="px-4 pb-4">
        <Disclaimer />
      </div>
    </>
  );
}
