"use client";

import { ChevronRight, LoaderCircle } from "lucide-react";

import type { SpecialistProposal, Step, TurnAnswer } from "@/lib/types";
import { count, usd } from "@/lib/text";
import {
  describeTool,
  groupSteps,
  shortInput,
  type StepGroup,
  summarize,
  summaryLine,
  TONE_WORDS,
  toneOf,
} from "@/lib/working";

const TONE_CLASS = {
  ok: "text-emerald",
  sent_back: "chip chip-rose py-0 px-2 text-[11.5px]",
  refused: "chip chip-rose py-0 px-2 text-[11.5px]",
  error: "chip chip-rose py-0 px-2 text-[11.5px]",
} as const;

function StepRow({ step, live }: { step: Step; live?: boolean }) {
  const tone = toneOf(step);
  const meko = step.tool === "search_memory";
  return (
    <li className="grid grid-cols-[28px_minmax(0,1fr)] gap-2.5 py-2">
      <span className="num pt-0.5 font-mono text-xs text-muted">{step.seq}</span>
      <div className="min-w-0 space-y-0.5">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px]">
          <span className="font-semibold">{describeTool(step.tool)}</span>
          <code className={`font-mono text-[12px] ${meko ? "text-meko" : "text-teal"}`}>{step.tool}</code>
          {tone !== "ok" && <span className={TONE_CLASS[tone]}>{TONE_WORDS[tone]}</span>}
          {live && <span className="pulse-dot size-1.5 rounded-full bg-gold" aria-hidden />}
        </p>
        {step.input_summary && step.input_summary !== "{}" && (
          <p className="truncate font-mono text-[12px] text-muted" title={step.input_summary}>
            {shortInput(step.input_summary)}
          </p>
        )}
        {step.result_summary && (
          <p className={`text-[13px] ${tone === "ok" ? "text-fg/90" : "text-rose"}`}>
            {step.result_summary}
          </p>
        )}
      </div>
    </li>
  );
}

function Group({ group, lastSeq }: { group: StepGroup; lastSeq: number | null }) {
  return (
    <li>
      {group.step ? (
        <ul>
          <StepRow step={group.step} live={group.step.seq === lastSeq} />
        </ul>
      ) : (
        <p className="flex items-center gap-2 py-2 pl-[38px] text-[13.5px] font-semibold">
          The {group.specialist} specialist is working
          <span className="pulse-dot size-1.5 rounded-full bg-gold" aria-hidden />
        </p>
      )}
      {group.children.length > 0 && (
        <div className="mb-1 ml-[38px] rounded-xl border border-line bg-raised/50 px-3">
          <p className="eyebrow pt-2.5">{group.specialist} specialist</p>
          <ul className="divide-y divide-line">
            {group.children.map((s) => (
              <StepRow key={s.seq} step={s} live={s.seq === lastSeq} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

export function StepList({ steps, live = false }: { steps: Step[]; live?: boolean }) {
  const groups = groupSteps(steps);
  const lastSeq = live && steps.length ? Math.max(...steps.map((s) => s.seq)) : null;
  return (
    <ol className="divide-y divide-line">
      {groups.map((g, i) => (
        <Group key={g.step?.seq ?? `working-${g.specialist}-${i}`} group={g} lastSeq={lastSeq} />
      ))}
    </ol>
  );
}

function Proposals({ proposals }: { proposals: SpecialistProposal[] }) {
  return (
    <ul className="space-y-2.5">
      {proposals.map((p, i) => (
        <li key={`${p.specialist}-${i}`} className="text-[13.5px]">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-semibold capitalize">{p.specialist}</span>
            {p.what_if ? (
              <code className="font-mono text-[12px] text-teal">{p.what_if}</code>
            ) : (
              <span className="text-xs text-muted">no change proposed</span>
            )}
          </p>
          <p className="mt-0.5 text-muted">{p.summary}</p>
        </li>
      ))}
    </ul>
  );
}

/** "Show the working" under an answer: every step each agent took, what each specialist
 * proposed, and what the turn cost. Closed by default, like a chat app's "thinking". */
export function Working({ steps, answer }: { steps: Step[]; answer: TurnAnswer }) {
  const summary = summarize(steps);
  return (
    <details className="group rounded-2xl border border-line bg-surface/40 open:bg-surface/70">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-2xl px-3.5 py-2.5 text-sm [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 text-muted transition-transform group-open:rotate-90" aria-hidden />
        <span className="shrink-0 font-semibold">Show the working</span>
        <span className="num min-w-0 truncate text-muted">{summaryLine(summary)}</span>
      </summary>
      <div className="space-y-5 border-t border-line px-3.5 pt-2 pb-4">
        {steps.length > 0 ? (
          <section aria-label="The agents' steps">
            <StepList steps={steps} />
          </section>
        ) : (
          <p className="pt-2 text-sm text-muted">No tool calls were logged for this turn.</p>
        )}
        {answer.proposals.length > 0 && (
          <section>
            <h4 className="eyebrow mb-2">What each specialist proposed</h4>
            <Proposals proposals={answer.proposals} />
          </section>
        )}
        <p className="num flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-line pt-3 text-xs text-muted">
          <span>{answer.cost.model_calls} model calls</span>
          <span>
            {count(answer.cost.input_tokens)} tokens in, {count(answer.cost.output_tokens)} out
          </span>
          <span>{usd(answer.cost.usd)}</span>
          {answer.plan && <span>plan v{answer.plan.version}, proposed</span>}
          {answer.meko.message_id && (
            answer.meko.trace_url ? (
              <a href={answer.meko.trace_url} target="_blank" rel="noreferrer" className="chip chip-meko chip-dot hover:underline">
                Meko trace
              </a>
            ) : (
              <span className="chip chip-meko chip-dot">Kept in Meko</span>
            )
          )}
          {answer.meko.error && <span className="text-rose">Meko didn&rsquo;t keep this turn: {answer.meko.error}</span>}
        </p>
      </div>
    </details>
  );
}

/** While a turn runs: the steps so far, as they come, like a chat app's live "thinking". */
export function LiveWorking({ steps }: { steps: Step[] }) {
  return (
    <div className="rounded-2xl border border-line bg-surface/70 px-3.5 py-3" aria-live="polite">
      <p className="flex items-center gap-2 text-sm font-semibold">
        <LoaderCircle className="size-4 animate-spin text-teal motion-reduce:animate-none" aria-hidden />
        Kako is working on it
        <span className="num font-normal text-muted">
          {steps.length ? summaryLine(summarize(steps)) : "reading the household's figures"}
        </span>
      </p>
      {steps.length > 0 && (
        <div className="mt-2 border-t border-line">
          <StepList steps={steps} live />
        </div>
      )}
    </div>
  );
}
