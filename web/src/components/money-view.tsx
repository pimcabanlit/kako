"use client";

import { ArrowRight, CalendarClock, ChevronDown, ChevronUp, Flag, Signpost } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect, useState } from "react";

import type { Loaded } from "@/components/app-shell";
import { Disclaimer } from "@/components/composer";
import { PageHeader, ViewChips } from "@/components/page-header";
import { Failed, failure } from "@/components/plan-view";
import { TopBar } from "@/components/top-bar";
import { api } from "@/lib/api";
import {
  donutArcs,
  milestoneTitle,
  MONEY_VIEWS,
  type MoneyView as View,
  moneyHref,
  momentWhen,
  monthYear,
  ROWS_SHOWN,
  rowsShown,
  signedAmount,
  viewOf,
} from "@/lib/money";
import { bookHref } from "@/lib/shelf";
import { formatDay } from "@/lib/text";
import type { Holding, Money, MoneyDebt, MoneyMilestone, PlanVersion, SplitPart } from "@/lib/types";
import { plural } from "@/lib/working";

/** Where the household's money stands on its date, in five views: the overview, the month's plan
 * line by line, each debt's month-by-month schedule, the big moments ahead and what it owns and
 * owes. The view is in the address (?view=debts). Every figure is the backend's, written out by
 * code; this screen only lays it out. */
export function MoneyView() {
  const params = useSearchParams();
  const router = useRouter();
  const view = viewOf(params.get("view"));
  const [money, setMoney] = useState<Loaded<Money>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.money(controller.signal).then(
      (value) => setMoney({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setMoney({ kind: "error", message: failure(error, "where the money stands") });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  if (money.kind === "loading") return <MoneySkeleton />;
  if (money.kind === "error")
    return <Failed message={money.message} onRetry={() => setAttempt((n) => n + 1)} />;

  const m = money.value;
  const choose = (v: View) => router.replace(moneyHref(v), { scroll: false });
  return (
    <>
      <TopBar phoneOnly />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-7 px-4 pt-8 pb-10 md:px-8 md:pt-12">
          <PageHeader
            title="Money"
            note={`Where the household's money stands on ${formatDay(m.as_of)}, worked out by Kako's engine from the facts it holds.`}
          >
            <ViewChips label="Money views" views={MONEY_VIEWS} chosen={view} onChoose={choose} />
          </PageHeader>
          <section
            role="tabpanel"
            id={`panel-${view}`}
            aria-labelledby={`tab-${view}`}
            className="space-y-6"
          >
            {view === "overview" && <Overview money={m} onChoose={choose} />}
            {view === "plan" && <MonthlyPlan plan={m.plan} before={m.before} />}
            {view === "debts" && <Debts debts={m.debts} />}
            {view === "moments" && <Moments money={m} />}
            {view === "worth" && <NetWorth money={m} />}
          </section>
          <Disclaimer />
        </div>
      </main>
    </>
  );
}

// --- Shared pieces -------------------------------------------------------------------------------

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-[17px] font-semibold">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function ViewLink({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-[13.5px] font-medium text-teal underline-offset-4 hover:underline"
    >
      {children}
      <ArrowRight className="size-3.5" aria-hidden />
    </button>
  );
}

/** A thin bar under a line's name: how much is left, as a share of the whole. */
function FillBar({ fill, tone = "bg-teal" }: { fill: number; tone?: string }) {
  const width = Math.max(0, Math.min(1, fill)) * 100;
  return (
    <span className="mt-1.5 block h-1 w-full max-w-[220px] overflow-hidden rounded-full bg-line" aria-hidden>
      <span className={`block h-full rounded-full ${tone}`} style={{ width: `${width}%` }} />
    </span>
  );
}

// The first column stays put while a wide table scrolls sideways on a phone.
const STICKY = "sticky left-0 z-[1] bg-surface";
const STICKY_ROLLED = "sticky left-0 z-[1] bg-[color-mix(in_srgb,var(--orange)_13%,var(--surface))]";

function Empty({ children }: { children: ReactNode }) {
  return <p className="panel text-[14px] text-muted">{children}</p>;
}

// --- Overview ------------------------------------------------------------------------------------

function Overview({ money, onChoose }: { money: Money; onChoose: (v: View) => void }) {
  const revisit = money.decisions.filter((d) => d.revisit > 0).length;
  return (
    <>
      <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Headline figures">
        {money.tiles.map((t) => (
          <li key={t.label} className="panel min-w-0 space-y-1 px-4 py-3.5">
            <p className="text-[12.5px] text-muted">{t.label}</p>
            <p className={`num text-[20px] font-semibold leading-tight sm:text-[22px] ${t.negative ? "text-rose" : ""}`}>
              {t.value}
            </p>
          </li>
        ))}
      </ul>

      {money.split ? (
        <Section
          title={`Where each ${money.split.total} goes`}
          aside={<ViewLink onClick={() => onChoose("plan")}>See the monthly plan</ViewLink>}
        >
          <Donut parts={money.split.parts} total={money.split.total} over={money.split.over} />
        </Section>
      ) : (
        <Empty>There is no pay on record yet, so there is nothing to split.</Empty>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Section
          title="Next milestones"
          aside={
            money.milestones.length > 0 && (
              <ViewLink onClick={() => onChoose("moments")}>All of them</ViewLink>
            )
          }
        >
          {money.milestones.length > 0 ? (
            <ul className="panel divide-y divide-line p-0">
              {money.milestones.slice(0, 4).map((ms) => (
                <MilestoneItem key={`${ms.kind}-${ms.name}`} milestone={ms} />
              ))}
            </ul>
          ) : (
            <Empty>No milestone is in sight at this plan.</Empty>
          )}
        </Section>
        <Section title="Coming up">
          <ul className="panel divide-y divide-line p-0">
            {money.moments.map((mo) => (
              <li key={`${mo.kind}-${mo.title}-${mo.on}`} className="flex items-start gap-3 px-4 py-3">
                <CalendarClock className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden />
                <div className="min-w-0 flex-1">
                  <p className="text-[14px] font-medium">{mo.title}</p>
                  <p className="text-[12.5px] text-muted">{momentWhen(mo, formatDay)}</p>
                </div>
                <span className="num shrink-0 text-[14px] font-semibold">{mo.value}</span>
              </li>
            ))}
            <li className="flex items-start gap-3 px-4 py-3">
              <Signpost className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
              <div className="min-w-0 flex-1 text-[14px]">
                <Link href="/decisions" className="font-medium underline-offset-4 hover:underline">
                  {plural(money.decisions.length, "decision")} in force
                </Link>
                <p className="text-[12.5px] text-muted">
                  {revisit > 0 ? `${plural(revisit, "decision")} to revisit` : "Nothing to revisit"}
                </p>
              </div>
            </li>
          </ul>
        </Section>
      </div>
    </>
  );
}

function MilestoneItem({ milestone }: { milestone: MoneyMilestone }) {
  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <Flag className="mt-0.5 size-4 shrink-0 text-emerald" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium">{milestoneTitle(milestone)}</p>
        <p className="text-[12.5px] text-muted">
          {formatDay(milestone.on)}, in {milestone.within}
          {milestone.on_track === false && <span className="text-rose"> · after its target date</span>}
        </p>
      </div>
    </li>
  );
}

const CHART: Record<SplitPart["key"], string> = {
  needs: "var(--chart-needs)",
  wants: "var(--chart-wants)",
  debt: "var(--chart-debt)",
  savings: "var(--chart-savings)",
  unplanned: "var(--chart-unplanned)",
};

/** The pay as a ring, each part its share, with the legend beside it carrying every amount and
 * share in words (the colour never stands alone). Hovering a part, or its row, names it in the
 * middle. */
function Donut({ parts, total, over }: { parts: SplitPart[]; total: string; over: string | null }) {
  const [hover, setHover] = useState<string | null>(null);
  const arcs = donutArcs(parts);
  const named = parts.find((p) => p.key === hover) ?? null;
  const summary = parts.map((p) => `${p.label} ${p.text}, ${p.share}`).join("; ");
  return (
    <div className="panel grid items-center gap-6 sm:grid-cols-[auto_1fr] sm:gap-8">
      <div className="relative mx-auto size-[200px] shrink-0">
        <svg viewBox="0 0 200 200" className="size-full" role="img" aria-label={`Where the pay goes: ${summary}`}>
          {arcs.map((a) => (
            <path
              key={a.key}
              d={a.path}
              style={{
                fill: CHART[a.key as SplitPart["key"]] ?? "var(--chart-unplanned)",
                stroke: "var(--surface)",
                opacity: hover && hover !== a.key ? 0.45 : 1,
              }}
              strokeWidth={2}
              strokeLinejoin="round"
              onMouseEnter={() => setHover(a.key)}
              onMouseLeave={() => setHover(null)}
              className="transition-opacity"
            />
          ))}
        </svg>
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center" aria-hidden>
          <div>
            <p className="text-[12px] text-muted">{named ? named.label : "A month"}</p>
            <p className="num text-[17px] font-semibold leading-tight">{named ? named.text : total}</p>
            {named && <p className="num text-[12px] text-muted">{named.share}</p>}
          </div>
        </div>
      </div>
      <div className="min-w-0 space-y-3">
        <table className="num w-full text-[14px]">
          <caption className="sr-only">Where each {total} goes, part by part</caption>
          <thead>
            <tr className="text-left text-[12.5px] text-muted">
              <th scope="col" className="pb-2 font-medium">Part</th>
              <th scope="col" className="pb-2 text-right font-medium">A month</th>
              <th scope="col" className="pb-2 pl-3 text-right font-medium">Share</th>
            </tr>
          </thead>
          <tbody>
            {parts.map((p) => (
              <tr
                key={p.key}
                onMouseEnter={() => setHover(p.key)}
                onMouseLeave={() => setHover(null)}
                className={`border-t border-line ${hover === p.key ? "bg-raised/60" : ""}`}
              >
                <th scope="row" className="py-2 text-left font-medium">
                  <span className="flex items-center gap-2.5">
                    <span className="size-2.5 shrink-0 rounded-full" style={{ background: CHART[p.key] }} aria-hidden />
                    {p.label}
                  </span>
                </th>
                <td className="py-2 text-right">{p.text}</td>
                <td className="py-2 pl-3 text-right text-muted">{p.share}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {over && (
          <p role="note" className="text-[13.5px] text-rose">
            The plan goes {over} over the pay.
          </p>
        )}
      </div>
    </div>
  );
}

// --- Monthly plan --------------------------------------------------------------------------------

function MonthlyPlan({ plan, before }: { plan: PlanVersion; before: PlanVersion | null }) {
  const [showBefore, setShowBefore] = useState(false);
  const shown = showBefore && before ? before : plan;
  const current = shown === plan;
  return (
    <Section
      title="The month, line by line"
      aside={
        before && (
          <div className="flex gap-1.5" role="group" aria-label="Which plan">
            {[
              { v: plan, on: !showBefore, set: false },
              { v: before, on: showBefore, set: true },
            ].map(({ v, on, set }) => (
              <button
                key={v.label}
                type="button"
                aria-pressed={on}
                onClick={() => setShowBefore(set)}
                className={`rounded-full border px-3 py-1 text-[13px] font-semibold whitespace-nowrap transition-colors ${
                  on ? "border-line-strong bg-raised text-fg" : "border-transparent text-muted hover:bg-raised/60 hover:text-fg"
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        )
      }
    >
      <p className="text-[13.5px] text-muted">
        The pay comes in, then each line goes out in turn: what is left after it runs down to what is
        still unplanned.
      </p>
      <div className="panel overflow-x-auto p-0">
        <table className="num w-full min-w-[560px] text-[14px]">
          <caption className="sr-only">The plan {shown.label.toLowerCase()}, line by line</caption>
          <thead>
            <tr className="text-left text-[12.5px] text-muted">
              <th scope="col" className={`${STICKY} px-4 py-2.5 font-medium`}>Line</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">A month</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Left after it</th>
              {current && <th scope="col" className="px-4 py-2.5 font-medium">Change</th>}
            </tr>
          </thead>
          <tbody>
            {shown.lines.map((line, i) => (
              <tr key={`${line.kind}-${line.name}-${i}`} className="border-t border-line align-top">
                <th scope="row" className={`${STICKY} px-4 py-2.5 text-left font-medium`}>
                  {line.name}
                  <FillBar fill={line.fill} />
                </th>
                <td className={`px-3 py-2.5 text-right ${line.kind === "in" ? "text-emerald" : ""}`}>
                  {signedAmount(line)}
                </td>
                <td className="px-3 py-2.5 text-right">{line.left ?? "unknown"}</td>
                {current && (
                  <td className="px-4 py-2.5">
                    {line.change && (
                      <span className={`chip ${line.change === "new" ? "chip-emerald" : "chip-orange"}`}>
                        {line.change}
                      </span>
                    )}
                  </td>
                )}
              </tr>
            ))}
            <tr className="border-t border-line-strong">
              <th scope="row" className={`${STICKY} px-4 py-3 text-left font-semibold`}>Left unplanned</th>
              <td className="px-3 py-3" />
              <td className="px-3 py-3 text-right font-semibold text-emerald">{shown.unplanned ?? "unknown"}</td>
              {current && <td className="px-4 py-3" />}
            </tr>
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// --- Debts ---------------------------------------------------------------------------------------

const ORDINALS = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"];

function orderWords(order: number | null): string | null {
  if (order === null) return null;
  return `${ORDINALS[order - 1] ?? `Number ${order}`} to pay off`;
}

function Debts({ debts }: { debts: MoneyDebt[] }) {
  if (debts.length === 0) return <Empty>The household has no debts on record.</Empty>;
  return (
    <>
      <p className="text-[13.5px] text-muted">
        Each debt month by month at today&rsquo;s plan. When one is paid off, its whole payment rolls to
        the next debt in line from the following month.
      </p>
      {debts.map((d) => (
        <DebtPanel key={d.id} debt={d} />
      ))}
    </>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note?: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-[12.5px] text-muted">{label}</dt>
      <dd className="num text-[15px] font-semibold">{value}</dd>
      {note && <dd className="text-[12.5px] text-muted">{note}</dd>}
    </div>
  );
}

function DebtPanel({ debt }: { debt: MoneyDebt }) {
  const [all, setAll] = useState(false);
  const rows = rowsShown(debt.rows, all);
  const order = orderWords(debt.order);
  const paying =
    debt.minimum && debt.extra ? `${debt.minimum} minimum + ${debt.extra} extra` : debt.minimum ? "the minimum" : null;
  const headingId = `debt-${debt.id}`;
  return (
    <section className="panel space-y-5" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          {order && <p className="eyebrow">{order}</p>}
          <h2 id={headingId} className="text-[19px] font-semibold">
            {debt.name}
          </h2>
        </div>
        <span className={`chip ${debt.extra ? "chip-emerald" : ""}`}>{debt.extra ? "paying extra" : "minimum only"}</span>
      </div>
      <div>
        <p className="num text-[28px] font-semibold leading-tight">{debt.balance}</p>
        <p className="text-[12.5px] text-muted">
          {debt.since ? `owed at the statement of ${formatDay(debt.since)}` : "owed today"}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 md:grid-cols-4">
        <Fact label="Interest" value={debt.rate ?? "unknown"} />
        <Fact label="Paying a month" value={debt.paying ?? "unknown"} note={paying} />
        <Fact
          label="Paid off"
          value={debt.payoff_on ? formatDay(debt.payoff_on) : "not in sight"}
          note={debt.payoff_in ? `in ${debt.payoff_in}` : null}
        />
        <Fact label="Interest still to pay" value={debt.interest_left ?? "unknown"} />
      </dl>
      {debt.why_not && (
        <p role="note" className="text-[13.5px] text-rose">
          {debt.name}: {debt.why_not}.
        </p>
      )}
      {debt.rows.length > 0 && <Schedule debt={debt} rows={rows} all={all} onAll={setAll} />}
    </section>
  );
}

function Schedule({
  debt,
  rows,
  all,
  onAll,
}: {
  debt: MoneyDebt;
  rows: readonly MoneyDebt["rows"][number][];
  all: boolean;
  onAll: (all: boolean) => void;
}) {
  const more = debt.rows.length > ROWS_SHOWN;
  const totals = debt.paid_total !== null && (all || !more);
  return (
    <div className="space-y-3">
      <div className="-mx-[18px] overflow-x-auto border-y border-line sm:mx-0 sm:rounded-xl sm:border">
        <table className="num w-full min-w-[620px] table-fixed text-[14px]">
          <caption className="sr-only">
            {debt.name}, month by month{more && !all ? `: the first ${ROWS_SHOWN} of ${debt.rows.length} months` : ""}
          </caption>
          <thead>
            <tr className="text-left text-[12.5px] text-muted">
              <th scope="col" className={`${STICKY} w-[22%] px-4 py-2.5 font-medium`}>Month</th>
              <th scope="col" className="w-[24%] px-3 py-2.5 text-right font-medium">Payment</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Interest</th>
              <th scope="col" className="px-3 py-2.5 text-right font-medium">Principal</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Balance left</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.month} className={`border-t border-line align-top ${r.rolled_in ? "bg-orange-soft" : ""}`}>
                <th scope="row" className={`${r.rolled_in ? STICKY_ROLLED : STICKY} px-4 py-2.5 text-left font-medium`}>
                  {monthYear(r.on)}
                  <FillBar fill={r.fill} tone={r.rolled_in ? "bg-orange" : "bg-teal"} />
                </th>
                <td className="px-3 py-2.5 text-right">
                  {r.payment}
                  {r.rolled_in && (
                    <span className="block text-[12px] font-medium text-orange">
                      +{r.rolled_in} from the {r.rolled_from ?? "debt paid off"}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right text-muted">{r.interest}</td>
                <td className="px-3 py-2.5 text-right">{r.principal}</td>
                <td className="px-4 py-2.5 text-right">{r.left}</td>
              </tr>
            ))}
            {totals && (
              <tr className="border-t border-line-strong font-semibold">
                <th scope="row" className={`${STICKY} px-4 py-3 text-left`}>Total</th>
                <td className="px-3 py-3 text-right">{debt.paid_total}</td>
                <td className="px-3 py-3 text-right">{debt.interest_total}</td>
                <td className="px-3 py-3 text-right">{debt.principal_total}</td>
                <td className="px-4 py-3" />
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {more && (
        <button type="button" className="btn px-3 py-1.5 text-[13.5px]" aria-expanded={all} onClick={() => onAll(!all)}>
          {all ? <ChevronUp className="size-3.5" aria-hidden /> : <ChevronDown className="size-3.5" aria-hidden />}
          {all ? `Show the first ${ROWS_SHOWN} months` : `Show all ${debt.rows.length} months`}
        </button>
      )}
    </div>
  );
}

// --- Big moments ---------------------------------------------------------------------------------

function Moments({ money }: { money: Money }) {
  const coming = money.moments.filter((m) => m.kind === "thirteenth_month");
  const ahead = money.moments.filter((m) => m.kind === "ahead");
  return (
    <>
      <Section title="Coming in">
        {coming.length > 0 ? (
          <MomentList moments={coming} />
        ) : (
          <Empty>No 13th-month pay is on record.</Empty>
        )}
      </Section>
      <Section title="Changes ahead">
        {ahead.length > 0 ? (
          <MomentList moments={ahead} />
        ) : (
          <Empty>Nothing else is set to change after {formatDay(money.as_of)}.</Empty>
        )}
      </Section>
      <Section title="Milestones">
        {money.milestones.length > 0 ? (
          <ul className="panel divide-y divide-line p-0">
            {money.milestones.map((ms) => (
              <MilestoneItem key={`${ms.kind}-${ms.name}`} milestone={ms} />
            ))}
          </ul>
        ) : (
          <Empty>No milestone is in sight at this plan.</Empty>
        )}
      </Section>
      <Section title="Decisions in force">
        {money.decisions.length > 0 ? (
          <ul className="panel divide-y divide-line p-0">
            {money.decisions.map((d) => (
              <li key={d.id}>
                <Link
                  href={bookHref(d.id, d.revisit > 0 ? "revisit" : "decision")}
                  className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-raised/60"
                >
                  <Signpost className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium">{d.question}</p>
                    <p className="text-[12.5px] text-muted">
                      {d.chosen} · {d.session_title}, {formatDay(d.on)}
                    </p>
                  </div>
                  {d.revisit > 0 && <span className="chip chip-gold chip-dot shrink-0">To revisit</span>}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>No decision is in force.</Empty>
        )}
      </Section>
    </>
  );
}

function MomentList({ moments }: { moments: Money["moments"] }) {
  return (
    <ul className="panel divide-y divide-line p-0">
      {moments.map((mo) => (
        <li key={`${mo.kind}-${mo.title}-${mo.on}`} className="flex items-start gap-3 px-4 py-3">
          <CalendarClock className="mt-0.5 size-4 shrink-0 text-gold" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="text-[14px] font-medium">{mo.title}</p>
            <p className="text-[12.5px] text-muted">{momentWhen(mo, formatDay)}</p>
          </div>
          <span className="num shrink-0 text-[14px] font-semibold">{mo.value}</span>
        </li>
      ))}
    </ul>
  );
}

// --- Net worth -----------------------------------------------------------------------------------

function NetWorth({ money }: { money: Money }) {
  const s = money.standing;
  return (
    <>
      <div className="panel space-y-1">
        <p className="text-[12.5px] text-muted">Net worth on {formatDay(money.as_of)}</p>
        <p className={`num text-[30px] font-semibold leading-tight ${s.negative ? "text-rose" : ""}`}>{s.net ?? "unknown"}</p>
        <p className="text-[13.5px] text-muted">
          What the household owns, {s.owned ?? "unknown"}, less what it owes, {s.owed ?? "unknown"}.
        </p>
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        <HoldingList title="What it owns" holdings={s.owns} total={s.owned} empty="Nothing on record." />
        <HoldingList title="What it owes" holdings={s.owes} total={s.owed} empty="No debts on record." />
      </div>
      <Section title="The road ahead">
        {money.milestones.length > 0 ? (
          <ul className="panel divide-y divide-line p-0">
            {money.milestones.map((ms) => (
              <MilestoneItem key={`${ms.kind}-${ms.name}`} milestone={ms} />
            ))}
          </ul>
        ) : (
          <Empty>No milestone is in sight at this plan.</Empty>
        )}
      </Section>
    </>
  );
}

function HoldingList({
  title,
  holdings,
  total,
  empty,
}: {
  title: string;
  holdings: Holding[];
  total: string | null;
  empty: string;
}) {
  return (
    <Section title={title}>
      {holdings.length > 0 ? (
        <ul className="panel divide-y divide-line p-0">
          {holdings.map((h) => (
            <li key={`${h.kind}-${h.name}`} className="flex items-start gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-[14px] font-medium">{h.name}</p>
                {h.since && <p className="text-[12.5px] text-muted">as of {formatDay(h.since)}</p>}
              </div>
              <span className="num shrink-0 text-[14px] font-semibold">{h.amount ?? "unknown"}</span>
            </li>
          ))}
          <li className="flex items-center gap-3 px-4 py-3">
            <p className="flex-1 text-[14px] font-semibold">Total</p>
            <span className="num shrink-0 text-[14px] font-semibold">{total ?? "unknown"}</span>
          </li>
        </ul>
      ) : (
        <Empty>{empty}</Empty>
      )}
    </Section>
  );
}

// --- Loading -------------------------------------------------------------------------------------

export function MoneySkeleton() {
  return (
    <>
      <TopBar phoneOnly />
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label="Loading where the money stands">
        <div className="mx-auto w-full max-w-5xl space-y-7 px-4 pt-8 md:px-8 md:pt-12">
          <div className="space-y-3">
            <div className="skeleton h-9 w-36" />
            <div className="skeleton h-4 w-2/3" />
          </div>
          <div className="flex flex-wrap gap-2">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="skeleton h-9 w-24 rounded-full" />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-[74px]" />
            ))}
          </div>
          <div className="skeleton h-64" />
        </div>
      </main>
    </>
  );
}
