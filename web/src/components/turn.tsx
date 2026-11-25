"use client";

import { ArrowRight, CircleAlert, CircleX, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import type { Loaded } from "@/components/app-shell";
import { ApprovalCard } from "@/components/approval-card";
import { BeforeAfter, ComparePanels, useCompare, useMonthsOpen } from "@/components/compare-view";
import { LiveWorking, Working } from "@/components/working";
import { blocks, optionParts, parseChange, splitLabel } from "@/lib/text";
import type {
  KeptTurn,
  Option,
  Proposal,
  Replan,
  Resolution,
  Step,
  TurnAnswer,
} from "@/lib/types";
import { listOf } from "@/lib/working";
import { initials, sourceKind } from "@/lib/words";

/** The household's message: on the right, in a raised bubble, with who wrote it. */
export function PersonMessage({ name, text }: { name: string | null; text: string }) {
  return (
    <div className="ml-auto flex max-w-[85%] flex-col items-end gap-1.5">
      <p className="flex items-center gap-2 text-xs font-semibold text-muted">
        {name ?? "Someone in the household"}
        <span
          className="grid size-6 place-items-center rounded-full border border-line-strong bg-raised text-[11px] text-fg"
          aria-hidden
        >
          {name ? initials(name) : "?"}
        </span>
      </p>
      <div className="bubble-person whitespace-pre-wrap">{text}</div>
    </div>
  );
}

export function KakoMark() {
  return (
    <span
      className="wordmark grid size-7 shrink-0 place-items-center rounded-full text-[13px] text-on-accent"
      style={{ background: "var(--btn)" }}
      aria-hidden
    >
      k
    </span>
  );
}

export function Text({ text, className = "" }: { text: string; className?: string }) {
  return (
    <div className={`space-y-3 ${className}`}>
      {blocks(text).map((b, i) =>
        b.kind === "p" ? (
          <p key={i}>{b.text}</p>
        ) : (
          <ul key={i} className="list-disc space-y-1 pl-5 marker:text-muted">
            {b.items.map((item, j) => (
              <li key={j}>{item}</li>
            ))}
          </ul>
        ),
      )}
    </div>
  );
}

function OptionCard({ option, compared }: { option: Option; compared?: ReactNode }) {
  const { letter, words } = optionParts(option.label);
  return (
    <article className="panel flex min-w-0 flex-col gap-3.5" aria-label={`Option ${option.label}`}>
      <header className="flex items-start gap-3">
        {letter && (
          <span className="display grid size-8 shrink-0 place-items-center rounded-lg border border-line-strong bg-raised text-[15px]">
            {letter}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h3 className="display text-[16px] leading-snug">{words}</h3>
          {option.recommended && (
            <span className="chip chip-emerald chip-dot mt-1.5">Recommended</span>
          )}
        </div>
      </header>
      <p className="text-[14px] text-fg/90">{option.summary}</p>
      {option.allocations.length > 0 && (
        <table className="num w-full text-[14px]">
          <caption className="eyebrow pb-1.5 text-left">Each month</caption>
          <tbody>
            {option.allocations.map((a) => (
              <tr key={a.entity} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted">
                  {a.name}
                </th>
                <td className="py-1.5 text-right font-semibold">{a.shown}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {compared}
      {option.sources.length > 0 && (
        <div>
          <p className="eyebrow mb-1.5">Where it comes from</p>
          <ul className="flex flex-wrap gap-1.5">
            {option.sources.map((s, i) => {
              const kind = sourceKind(s);
              const tone = kind.tone === "plain" ? "" : `chip-${kind.tone}`;
              const quote = s.kind === "conversation";
              return (
                <li key={`${s.ref}-${i}`} className="max-w-full">
                  <span className={`chip ${tone} font-medium`} title={s.shown}>
                    <span className="shrink-0 font-semibold">{kind.label}</span>
                    {!quote && !/^[A-Z]+\d+$/.test(s.shown) && (
                      <span className="num truncate">{s.shown}</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {option.specialists.length > 0 && (
        <p className="mt-auto text-xs text-muted">
          From the {listOf(option.specialists)}{" "}
          {option.specialists.length === 1 ? "specialist" : "specialists"}
        </p>
      )}
    </article>
  );
}

function ResolutionPanel({ resolution }: { resolution: Resolution }) {
  return (
    <section className="panel space-y-3 text-[14px]" aria-label="How the proposals were reconciled">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="display text-[16px]">How Kako weighed the proposals</h3>
        {resolution.conflicts.map((c) => (
          <span key={c} className="chip chip-rose chip-dot">
            {c}
          </span>
        ))}
      </div>
      {resolution.described.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-muted marker:text-muted">
          {resolution.described.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      )}
      {resolution.splits.length > 0 && (
        <div>
          <p className="eyebrow mb-1.5">Splits tried on the engine</p>
          <ul className="flex flex-wrap gap-1.5">
            {resolution.splits.map((s) => {
              const fits = s.endsWith(": fits");
              return (
                <li key={s} className={`chip chip-dot font-mono text-[12px] ${fits ? "chip-emerald" : "chip-rose"}`}>
                  {s}
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {(resolution.chosen || resolution.rejected) && (
        <p className="flex flex-wrap items-center gap-2">
          {resolution.chosen && <span className="chip chip-emerald chip-dot">Chosen: {resolution.chosen}</span>}
          {resolution.rejected && <span className="chip chip-rose chip-dot">Rejected: {resolution.rejected}</span>}
        </p>
      )}
      <p>{resolution.reason}</p>
    </section>
  );
}

function ReplanPanel({ replan }: { replan: Replan }) {
  const revisit = replan.because.map(splitLabel).filter((l) => l.label === "To revisit");
  const facts = replan.because.map(splitLabel).filter((l) => l.label === null);
  return (
    <section className="panel edge edge-orange space-y-4 text-[14px]" aria-label="What changed">
      <div>
        <h3 className="display text-[16px]">What changed</h3>
        <p className="mt-0.5 text-[13px] text-muted">Since {replan.since}</p>
      </div>
      <ul className="space-y-1.5">
        {replan.what_changed.map((line, i) => {
          const parts = parseChange(line);
          return (
            <li key={i} className="num flex flex-wrap items-baseline gap-x-2">
              <span className="size-1.5 translate-y-[-2px] rounded-full bg-orange" aria-hidden />
              {parts ? (
                <>
                  <span className="text-muted">{parts.label}:</span>
                  <s className="text-muted decoration-[1.5px]">{parts.before}</s>
                  <span className="text-muted" aria-hidden>
                    →
                  </span>
                  <span className="font-semibold">{parts.after}</span>
                </>
              ) : (
                <span>{line}</span>
              )}
            </li>
          );
        })}
      </ul>
      {replan.why && (
        <div>
          <h4 className="eyebrow mb-1">Why</h4>
          <p>{replan.why}</p>
        </div>
      )}
      {revisit.length > 0 && (
        <div className="space-y-2">
          <h4 className="eyebrow">Decisions to revisit</h4>
          <ul className="space-y-1.5">
            {revisit.map((r, i) => (
              <li key={i} className="flex flex-col items-start gap-1 sm:flex-row sm:gap-2">
                <span className="chip chip-gold chip-dot shrink-0">To revisit</span>
                <span className="min-w-0">{r.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {facts.length > 0 && (
        <details className="text-[13px]">
          <summary className="cursor-pointer text-muted hover:text-fg">
            The facts behind it ({facts.length})
          </summary>
          <ul className="num mt-2 space-y-1 text-muted">
            {facts.map((f, i) => (
              <li key={i}>{f.text}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Kako's answer: unboxed text, then options, how a conflict ended, what changed, the changes
 * waiting for a yes, and "show the working". Every number in it came from the engine and passed
 * the number check; any the check couldn't match is flagged where it is shown. */
export function KakoAnswer({
  answer,
  steps,
  proposals,
  onDecided,
}: {
  answer: TurnAnswer;
  steps: Step[];
  proposals: Loaded<Proposal[]>;
  onDecided: () => void;
}) {
  // Each option beside today's plan, worked out by the engine for the plan this turn proposed.
  const compared = useCompare(answer.options.length > 0 ? (answer.plan?.id ?? null) : null);
  const months = useMonthsOpen();
  return (
    <div className="flex gap-3">
      <KakoMark />
      <div className="min-w-0 flex-1 space-y-4">
        <p className="text-xs font-semibold text-muted">Kako</p>
        <Text text={answer.reply} className="text-[15px] leading-7" />
        {answer.flagged.length > 0 && (
          <div role="note" className="flex gap-2 rounded-xl border border-rose/40 bg-rose-soft px-3 py-2 text-[13.5px] text-rose">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p>
              The number check couldn&rsquo;t match{" "}
              {answer.flagged.map((f, i) => (
                <span key={i}>
                  {i > 0 && ", "}
                  <b className="num">{f.text}</b> ({f.where})
                </span>
              ))}{" "}
              to any figure, fact or amount you said. Treat {answer.flagged.length === 1 ? "it" : "them"} with care.
            </p>
          </div>
        )}
        {answer.options.length > 0 && (
          <div className={`grid gap-3 ${answer.options.length > 1 ? "lg:grid-cols-2" : ""}`}>
            {answer.options.map((o) => (
              <OptionCard
                key={o.label}
                option={o}
                compared={<BeforeAfter state={compared} label={o.label} months={months} />}
              />
            ))}
          </div>
        )}
        <ComparePanels state={compared} months={months} />
        {answer.plan && (
          <Link
            href={`/plans/${answer.plan.id}`}
            className="group inline-flex items-center gap-1.5 text-[13.5px] font-semibold text-teal hover:underline"
          >
            Plan v{answer.plan.version}: why, down to the facts, and the number check
            <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
        )}
        {answer.replan && <ReplanPanel replan={answer.replan} />}
        {answer.resolution && <ResolutionPanel resolution={answer.resolution} />}
        {answer.changes.length > 0 && (
          <ApprovalCard changes={answer.changes} proposals={proposals} onDecided={onDecided} />
        )}
        {answer.not_proposed.length > 0 && (
          <div role="note" className="rounded-xl border border-rose/40 bg-rose-soft px-3 py-2 text-[13.5px] text-rose">
            <p className="font-semibold">Kako couldn&rsquo;t hold these for your yes:</p>
            <ul className="mt-1 list-disc pl-5">
              {answer.not_proposed.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
        <Working steps={steps} answer={answer} />
      </div>
    </div>
  );
}

export function KeptTurnView({
  turn,
  proposals,
  onDecided,
}: {
  turn: KeptTurn;
  proposals: Loaded<Proposal[]>;
  onDecided: () => void;
}) {
  return (
    <div className="space-y-6">
      <PersonMessage name={turn.said_by?.display_name ?? null} text={turn.message} />
      <KakoAnswer answer={turn.answer} steps={turn.steps} proposals={proposals} onDecided={onDecided} />
    </div>
  );
}

/** A turn on its way: the message, then the agents' steps as they come, or why it stopped. */
export function PendingTurnView({
  name,
  message,
  steps,
  error,
  onRetry,
  onDismiss,
}: {
  name: string | null;
  message: string;
  steps: Step[];
  error?: string;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="space-y-6">
      <PersonMessage name={name} text={message} />
      <div className="flex gap-3">
        <KakoMark />
        <div className="min-w-0 flex-1 space-y-3">
          <p className="text-xs font-semibold text-muted">Kako</p>
          {error ? (
            <div role="alert" className="panel edge edge-rose space-y-3 text-sm">
              <p className="flex items-start gap-2 text-rose">
                <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />
                {error}
              </p>
              <div className="flex gap-2">
                <button type="button" className="btn px-3 py-1.5 text-sm" onClick={onRetry}>
                  <RefreshCw className="size-3.5" aria-hidden />
                  Try again
                </button>
                <button type="button" className="btn btn-ghost px-3 py-1.5 text-sm" onClick={onDismiss}>
                  Dismiss
                </button>
              </div>
            </div>
          ) : (
            <LiveWorking steps={steps} />
          )}
        </div>
      </div>
    </div>
  );
}
