"use client";

// Before and after a plan's options (docs/architecture.md, "The session screen" and "The plan
// screen"): on each option's card what it changes against today's plan, below the options a table of
// today's plan and each option side by side, and each option's months one by one. Every value and
// every change in words is the engine's, from GET /plans/{id}/compare.

import { ArrowRight, ChevronDown, ChevronUp, X } from "lucide-react";
import { useEffect, useId, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { api, ApiError } from "@/lib/api";
import { cardRows, changeTone, isTotal, moved, optionIndex, rolledNote } from "@/lib/compare";
import { monthYear, ROWS_SHOWN, rowsShown } from "@/lib/money";
import { optionParts } from "@/lib/text";
import type { CompareCell, CompareDebt, CompareFund, Comparison } from "@/lib/types";

/** The plan's options beside today's plan; null with no plan to read. */
export function useCompare(planId: string | null): Loaded<Comparison> | null {
  const [state, setState] = useState<Loaded<Comparison>>({ kind: "loading" });
  const [read, setRead] = useState(planId);
  if (read !== planId) {
    // A different plan: start again before the next read (React's "adjust state on a prop change").
    setRead(planId);
    setState({ kind: "loading" });
  }
  useEffect(() => {
    if (!planId) return;
    const controller = new AbortController();
    api.compare(planId, controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof ApiError ? error.message : "Couldn't set these options beside today's plan.";
        if (!(error instanceof ApiError)) console.error("Reading the comparison failed", error);
        setState({ kind: "error", message });
      },
    );
    return () => controller.abort();
  }, [planId]);
  return planId ? state : null;
}

/** The option's months, open in the panel below the options, and the panel's id for aria-controls. */
export type MonthsOpen = { label: string | null; panelId: string; open: (label: string | null) => void };

export function useMonthsOpen(): MonthsOpen {
  const [label, setLabel] = useState<string | null>(null);
  const panelId = useId();
  const open = (next: string | null) => {
    setLabel(next);
    if (next !== null) {
      // After the panel renders, bring it into view (smoothly unless motion is reduced).
      requestAnimationFrame(() => {
        const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        document.getElementById(panelId)?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
      });
    }
  };
  return { label, panelId, open };
}

function ChangeChip({ cell }: { cell: Pick<CompareCell, "change" | "direction"> }) {
  const tone = changeTone(cell.direction);
  if (!cell.change || tone === null) return null;
  return <span className={`chip shrink-0 ${tone}`}>{cell.change}</span>;
}

/** On an option's card: what it changes against today's plan, then a way into its months. */
export function BeforeAfter({
  state,
  label,
  months,
}: {
  state: Loaded<Comparison> | null;
  label: string;
  months: MonthsOpen;
}) {
  if (state === null || state.kind === "error") return null; // the panel below says why, once
  if (state.kind === "loading")
    return (
      <div aria-busy="true" aria-label="Setting this option beside today's plan" className="space-y-2">
        <p className="eyebrow">Before → after</p>
        <div className="h-4 w-3/4 animate-pulse rounded bg-raised motion-reduce:animate-none" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-raised motion-reduce:animate-none" />
      </div>
    );
  const rows = cardRows(state.value, label);
  if (rows.length === 0) return null;
  const open = months.label === label;
  return (
    <div>
      <p className="eyebrow mb-1.5" title="Today's plan, then with this option">
        Before → after
      </p>
      <ul className="divide-y divide-line border-t border-line">
        {rows.map((r) => (
          <li key={r.key} className="py-2">
            <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
              <p className="text-[12.5px] text-muted">{r.label}</p>
              <ChangeChip cell={r.after} />
            </div>
            <div className="num mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[14px]">
              <span className="sr-only">Today&rsquo;s plan:</span>
              <span className={`text-muted ${moved(r) ? "line-through decoration-line-strong" : ""}`}>
                {r.before.value}
              </span>
              <ArrowRight className="size-3.5 shrink-0 text-muted" aria-hidden />
              <span className="sr-only">with this option:</span>
              <span className="font-semibold">{r.after.value}</span>
            </div>
          </li>
        ))}
      </ul>
      <button
        type="button"
        className="btn mt-3 px-3 py-1.5 text-[13px]"
        aria-expanded={open}
        aria-controls={months.panelId}
        onClick={() => months.open(open ? null : label)}
      >
        {open ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
        {open ? "Hide month by month" : "See month by month"}
      </button>
    </div>
  );
}

/** Below the options: today's plan and each option side by side, then the open option's months. */
export function ComparePanels({ state, months }: { state: Loaded<Comparison> | null; months: MonthsOpen }) {
  if (state === null) return null;
  if (state.kind === "loading")
    return (
      <div aria-busy="true" aria-label="Comparing the options" className="panel space-y-3">
        <div className="h-4 w-48 animate-pulse rounded bg-raised motion-reduce:animate-none" />
        <div className="h-24 animate-pulse rounded-xl bg-raised motion-reduce:animate-none" />
      </div>
    );
  if (state.kind === "error")
    return (
      <p role="note" className="rounded-xl border border-line bg-surface px-3.5 py-2.5 text-[13.5px] text-muted">
        {state.message}
      </p>
    );
  const c = state.value;
  return (
    <>
      <CompareTable c={c} />
      <div id={months.panelId} className="scroll-mt-4">
        {months.label !== null && optionIndex(c, months.label) >= 0 && (
          <MonthByMonth c={c} label={months.label} months={months} />
        )}
      </div>
    </>
  );
}

function head(label: string): string {
  const { letter, words } = optionParts(label);
  return letter ? `${letter} · ${words}` : words;
}

function Value({ cell, strong = false }: { cell: CompareCell; strong?: boolean }) {
  return (
    <>
      <span className={strong ? "font-semibold" : ""}>{cell.value}</span>
      {cell.note && <span className="block text-[12px] text-muted">{cell.note}</span>}
    </>
  );
}

function CompareTable({ c }: { c: Comparison }) {
  const width = 170 + 170 * (c.options.length + 1);
  return (
    <section className="panel space-y-3 p-0 pt-4" aria-label="Compare the options">
      <div className="px-[18px]">
        <h3 className="display text-[16px]">Compare the options</h3>
        <p className="text-[13px] text-muted">{c.baseline} Each option is worked out by the engine on the same facts.</p>
      </div>
      <div className="overflow-x-auto border-t border-line">
        <table className="num w-full text-[13.5px]" style={{ minWidth: width }}>
          <caption className="sr-only">Today&rsquo;s plan and each option, what each reaches and what it changes</caption>
          <thead>
            <tr className="text-left text-[12.5px] text-muted">
              <th scope="col" className="sticky left-0 z-[1] bg-surface px-[18px] py-2 font-medium">
                <span className="sr-only">Outcome</span>
              </th>
              <th scope="col" className="px-3 py-2 font-medium">Today&rsquo;s plan</th>
              {c.options.map((o) => (
                <th key={o.label} scope="col" className="px-3 py-2 font-medium text-fg last:pr-[18px]">
                  {head(o.label)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-line align-top">
              <th scope="row" className="sticky left-0 z-[1] bg-surface px-[18px] py-2.5 text-left font-medium">
                Each month
              </th>
              <td className="px-3 py-2.5 text-muted">{c.each_month}</td>
              {c.options.map((o) => (
                <td key={o.label} className="px-3 py-2.5 last:pr-[18px]">
                  {o.each_month}
                </td>
              ))}
            </tr>
            {c.rows.map((r) => (
              <tr key={r.key} className={`align-top ${isTotal(r) ? "border-t border-line-strong" : "border-t border-line"}`}>
                <th
                  scope="row"
                  className={`sticky left-0 z-[1] bg-surface px-[18px] py-2.5 text-left ${isTotal(r) ? "font-semibold" : "font-medium"}`}
                >
                  {r.label}
                </th>
                <td className="px-3 py-2.5 text-muted">
                  <Value cell={r.before} />
                </td>
                {r.options.map((cell, i) => (
                  <td key={c.options[i]?.label ?? i} className="px-3 py-2.5 last:pr-[18px]">
                    <Value cell={cell} strong={isTotal(r)} />
                    {cell.change && changeTone(cell.direction) !== null && (
                      <div className="mt-1">
                        <ChangeChip cell={cell} />
                      </div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// The first column stays put while a wide table scrolls sideways on a phone.
const STICKY = "sticky left-0 z-[1] bg-surface";
const STICKY_ROLLED = "sticky left-0 z-[1] bg-[color-mix(in_srgb,var(--orange)_13%,var(--surface))]";
const STICKY_REACHED = "sticky left-0 z-[1] bg-[color-mix(in_srgb,var(--emerald)_12%,var(--surface))]";

function FillBar({ fill, tone }: { fill: number; tone: string }) {
  const width = Math.max(0, Math.min(1, fill)) * 100;
  return (
    <span className="mt-1.5 block h-1 w-full max-w-[160px] overflow-hidden rounded-full bg-line" aria-hidden>
      <span className={`block h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
    </span>
  );
}

function MonthByMonth({ c, label, months }: { c: Comparison; label: string; months: MonthsOpen }) {
  const shown = c.months[optionIndex(c, label)];
  return (
    <section className="panel space-y-6" aria-label={`Month by month, option ${label}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="display text-[16px]">Month by month</h3>
          <p className="text-[13px] text-muted">
            Each debt with option {optionParts(label).letter ?? label}, its balance in today&rsquo;s plan beside it.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {c.options.length > 1 && (
            <div className="flex gap-1.5" role="group" aria-label="Which option">
              {c.options.map((o) => (
                <button
                  key={o.label}
                  type="button"
                  aria-pressed={o.label === label}
                  onClick={() => months.open(o.label)}
                  className={`rounded-full border px-3 py-1 text-[13px] font-semibold ${
                    o.label === label
                      ? "border-line-strong bg-raised text-fg"
                      : "border-transparent text-muted hover:bg-raised/60"
                  }`}
                >
                  Option {optionParts(o.label).letter ?? o.label}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            className="btn btn-ghost size-8 p-0"
            aria-label="Close month by month"
            onClick={() => months.open(null)}
          >
            <X className="size-4" aria-hidden />
          </button>
        </div>
      </div>
      {shown.debts.map((d) => (
        <DebtMonths key={`${label}-${d.name}`} debt={d} />
      ))}
      {shown.fund && <FundMonths key={`${label}-fund`} fund={shown.fund} />}
      {shown.debts.length === 0 && !shown.fund && (
        <p className="text-[13.5px] text-muted">This option has no debt to pay down or fund to fill.</p>
      )}
    </section>
  );
}

function DebtMonths({ debt }: { debt: CompareDebt }) {
  const [all, setAll] = useState(false);
  const rows = rowsShown(debt.rows, all);
  const more = debt.rows.length > ROWS_SHOWN;
  const totals = debt.paid_off !== null && (all || !more);
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[15px] font-semibold">{debt.name}</h4>
        <ChangeChip cell={{ change: debt.change, direction: debt.direction }} />
      </div>
      <div className="space-y-0.5 text-[13.5px]">
        <p className="num">{debt.closing}</p>
        {debt.before_closing && <p className="num text-muted">{debt.before_closing}</p>}
      </div>
      <div className="-mx-[18px] overflow-x-auto border-y border-line sm:mx-0 sm:rounded-xl sm:border">
        <table className="num w-full min-w-[640px] table-fixed text-[13.5px]">
          <caption className="sr-only">
            {debt.name}, month by month{more && !all ? `: the first ${ROWS_SHOWN} of ${debt.rows.length} months` : ""}
          </caption>
          <thead>
            <tr className="text-left text-[12px] text-muted">
              <th scope="col" className={`${STICKY} w-[16%] px-4 py-2 font-medium`}>Month</th>
              <th scope="col" className="w-[20%] px-3 py-2 text-right font-medium">Payment</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Interest</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Principal</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Balance left</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Today&rsquo;s plan</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const rolled = rolledNote(r);
              return (
                <tr key={r.month} className={`border-t border-line align-top ${rolled ? "bg-orange-soft" : ""}`}>
                  <th scope="row" className={`${rolled ? STICKY_ROLLED : STICKY} px-4 py-2 text-left font-medium`}>
                    {monthYear(r.on)}
                    <FillBar fill={r.fill} tone={rolled ? "bg-orange" : "bg-teal"} />
                  </th>
                  <td className="px-3 py-2 text-right">
                    {r.payment}
                    {rolled && <span className="block text-[11.5px] font-medium text-orange">{rolled}</span>}
                  </td>
                  <td className="px-3 py-2 text-right text-muted">{r.interest}</td>
                  <td className="px-3 py-2 text-right">{r.principal}</td>
                  <td className="px-3 py-2 text-right font-semibold">{r.left}</td>
                  <td className="px-4 py-2 text-right text-muted">
                    {r.before_left ?? <span aria-label="not shown">—</span>}
                  </td>
                </tr>
              );
            })}
            {totals && (
              <tr className="border-t border-line-strong font-semibold">
                <th scope="row" className={`${STICKY} px-4 py-2.5 text-left`}>Total</th>
                <td className="px-3 py-2.5 text-right">{debt.paid_total}</td>
                <td className="px-3 py-2.5 text-right">{debt.interest_total}</td>
                <td className="px-3 py-2.5 text-right">{debt.principal_total}</td>
                <td className="px-3 py-2.5" />
                <td className="px-4 py-2.5" />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {more && (
        <button type="button" className="btn px-3 py-1.5 text-[13px]" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
          {all ? `Show the first ${ROWS_SHOWN} months` : `Show all ${debt.rows.length} months`}
        </button>
      )}
    </div>
  );
}

function FundMonths({ fund }: { fund: CompareFund }) {
  const [all, setAll] = useState(false);
  const rows = rowsShown(fund.rows, all);
  const more = fund.rows.length > ROWS_SHOWN;
  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-[15px] font-semibold">{fund.name}</h4>
        <span className="chip num">Target {fund.target}</span>
      </div>
      <div className="space-y-0.5 text-[13.5px]">
        <p className="num">{fund.closing}</p>
        <p className="num text-muted">{fund.before_closing}</p>
      </div>
      <div className="-mx-[18px] overflow-x-auto border-y border-line sm:mx-0 sm:rounded-xl sm:border">
        <table className="num w-full min-w-[520px] table-fixed text-[13.5px]">
          <caption className="sr-only">
            {fund.name}, month by month{more && !all ? `: the first ${ROWS_SHOWN} of ${fund.rows.length} months` : ""}
          </caption>
          <thead>
            <tr className="text-left text-[12px] text-muted">
              <th scope="col" className={`${STICKY} w-[28%] px-4 py-2 font-medium`}>Month</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Added</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">In the fund</th>
              <th scope="col" className="px-4 py-2 text-right font-medium">Still to go</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const reached = r.to_go === null;
              return (
                <tr key={r.month} className={`border-t border-line align-top ${reached ? "bg-emerald-soft" : ""}`}>
                  <th scope="row" className={`${reached ? STICKY_REACHED : STICKY} px-4 py-2 text-left font-medium`}>
                    {monthYear(r.on)}
                    <FillBar fill={r.fill} tone="bg-emerald" />
                  </th>
                  <td className="px-3 py-2 text-right">{r.added}</td>
                  <td className="px-3 py-2 text-right font-semibold">{r.balance}</td>
                  <td className={`px-4 py-2 text-right ${reached ? "font-semibold text-emerald" : "text-muted"}`}>
                    {reached ? "at target" : r.to_go}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {more && (
        <button type="button" className="btn px-3 py-1.5 text-[13px]" aria-expanded={all} onClick={() => setAll(!all)}>
          {all ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
          {all ? `Show the first ${ROWS_SHOWN} months` : `Show all ${fund.rows.length} months`}
        </button>
      )}
    </div>
  );
}
