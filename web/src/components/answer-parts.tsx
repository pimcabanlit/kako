"use client";

import { BookOpen, Calculator, FileText, FlaskConical, type LucideIcon } from "lucide-react";

import type { Calculation, Scenario, Source } from "@/lib/types";
import { sourceDetail, sourceKind } from "@/lib/words";

// The parts of an answer that say how it was worked out: its labels, its sources, a what-if that
// saved nothing, and a sum with its working. Plain styling: colour keeps its one meaning
// (docs/look-and-feel.md), and violet stays Meko's.

const LABEL_ICONS: Record<string, LucideIcon> = {
  "General information": BookOpen,
  "Scenario, nothing saved": FlaskConical,
  Calculated: Calculator,
  "From your documents": FileText,
};

/** The labels under a reply: what kind of answer it is, as code worked it out. */
export function AnswerLabels({ labels }: { labels: string[] }) {
  if (labels.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="About this answer">
      {labels.map((label) => {
        const Icon = LABEL_ICONS[label];
        return (
          <li key={label} className="chip font-medium">
            {Icon && <Icon className="size-3.5 text-muted" aria-hidden />}
            {label}
          </li>
        );
      })}
    </ul>
  );
}

/** A list of sources as chips: the kind, then the value or the document's name. */
export function SourceChips({ sources, title = "Where it comes from" }: { sources: Source[]; title?: string }) {
  if (sources.length === 0) return null;
  return (
    <div>
      <p className="eyebrow mb-1.5">{title}</p>
      <ul className="flex flex-wrap gap-1.5">
        {sources.map((s, i) => {
          const kind = sourceKind(s);
          const tone = kind.tone === "plain" ? "" : `chip-${kind.tone}`;
          const detail = sourceDetail(s);
          return (
            <li key={`${s.ref}-${i}`} className="max-w-full">
              <span className={`chip ${tone} font-medium`} title={s.shown}>
                <span className="shrink-0 font-semibold">{kind.label}</span>
                {detail && <span className="num truncate">{detail}</span>}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** A what-if that changed facts or added items: what it changed, what Kako assumed, and the
 * headline figures before and after. Nothing in it was saved. */
export function ScenarioCard({ scenario }: { scenario: Scenario }) {
  return (
    <section className="panel space-y-3 text-[14px]" aria-label="Scenario, nothing saved">
      <header className="flex flex-wrap items-center gap-2">
        <FlaskConical className="size-4 text-muted" aria-hidden />
        <h3 className="display text-[16px]">Scenario, nothing saved</h3>
      </header>
      {scenario.changes.length > 0 && (
        <div>
          <h4 className="eyebrow mb-1">What the scenario changes</h4>
          <ul className="num list-disc space-y-1 pl-5 marker:text-muted">
            {scenario.changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
      {scenario.assumptions.length > 0 && (
        <div>
          <h4 className="eyebrow mb-1">Kako assumed</h4>
          <ul className="num list-disc space-y-1 pl-5 text-muted marker:text-muted">
            {scenario.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
      {scenario.figures.length > 0 && (
        <table className="num w-full text-[14px]">
          <caption className="eyebrow pb-1.5 text-left">Before and after</caption>
          <tbody>
            {scenario.figures.map((f, i) => (
              <tr key={i} className="border-t border-line">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal text-muted">
                  {f.title}
                </th>
                <td className="py-1.5 text-right whitespace-nowrap">
                  <span className="text-muted">{f.before}</span>
                  <span className="px-1.5 text-muted" aria-label="becomes">
                    →
                  </span>
                  <span className="font-semibold">{f.after}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="text-[13px] text-muted">{scenario.note}</p>
    </section>
  );
}

/** A sum Kako's calculator worked out, with the formula and each input's source. */
export function CalculationCard({ calculation }: { calculation: Calculation }) {
  return (
    <section className="panel space-y-2 text-[14px]" aria-label={`Calculated: ${calculation.label}`}>
      <header className="flex flex-wrap items-center gap-2">
        <Calculator className="size-4 text-muted" aria-hidden />
        <h3 className="display text-[16px]">{calculation.label}</h3>
      </header>
      <p className="num text-[18px] font-semibold">{calculation.result}</p>
      <p className="font-mono text-[12.5px] text-muted">{calculation.formula}</p>
      {calculation.inputs.length > 0 && (
        <ul className="num space-y-0.5 text-[13px] text-muted">
          {calculation.inputs.map((input, i) => (
            <li key={i}>{input}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
