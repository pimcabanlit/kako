"use client";

import { Activity, ClipboardList, MessageSquare, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useShell } from "@/components/app-shell";
import { ThemeToggle } from "@/components/theme-toggle";
import { formatDay } from "@/lib/text";
import { plural } from "@/lib/working";

/** The sessions down the left, newest first, with "New session" and the plan at the top. */
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { sessions, reloadSessions, household, pending } = useShell();
  const pathname = usePathname();
  const onPlans = pathname === "/plans" || pathname.startsWith("/plans/");

  return (
    <nav aria-label="Sessions and plans" className="flex h-full w-full flex-col">
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <Link href="/" onClick={onNavigate} className="wordmark text-[22px]" aria-label="Kako, new session">
          kako
        </Link>
        <ThemeToggle />
      </div>
      <div className="px-3">
        <Link
          href="/"
          onClick={onNavigate}
          className="btn w-full justify-start"
          aria-current={pathname === "/" ? "page" : undefined}
        >
          <Plus className="size-4" aria-hidden />
          New session
        </Link>
        <Link
          href="/plans"
          onClick={onNavigate}
          aria-current={onPlans ? "page" : undefined}
          className={`mt-1.5 flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm font-medium transition-colors ${
            onPlans ? "bg-raised text-fg" : "text-fg/90 hover:bg-raised/70"
          }`}
        >
          <ClipboardList className={`size-4 shrink-0 ${onPlans ? "text-teal" : "text-muted"}`} aria-hidden />
          Plan
          <span className="ml-auto text-xs font-normal text-muted">why and what changed</span>
        </Link>
      </div>

      <p className="eyebrow mt-6 mb-2 px-5">Sessions</p>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {sessions.kind === "loading" && (
          <div className="space-y-2 px-2" aria-label="Loading the sessions">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-9" />
            ))}
          </div>
        )}
        {sessions.kind === "error" && (
          <div className="space-y-2 px-2 text-sm">
            <p className="text-rose">{sessions.message}</p>
            <button type="button" className="btn btn-ghost px-2 py-1 text-sm" onClick={reloadSessions}>
              <RefreshCw className="size-3.5" aria-hidden />
              Try again
            </button>
          </div>
        )}
        {sessions.kind === "ready" && sessions.value.length === 0 && (
          <p className="px-2 text-sm text-muted">
            No sessions yet. Start one and ask Kako about your budget, debts, savings or goals.
          </p>
        )}
        {sessions.kind === "ready" && sessions.value.length > 0 && (
          <ul className="space-y-0.5">
            {sessions.value.map((s) => {
              const href = `/sessions/${s.id}`;
              const active = pathname === href;
              const working = pending?.sessionId === s.id && pending.status === "running";
              return (
                <li key={s.id}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`group flex items-start gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-colors ${
                      active ? "bg-raised text-fg" : "text-fg/90 hover:bg-raised/70"
                    }`}
                  >
                    <MessageSquare
                      className={`mt-0.5 size-4 shrink-0 ${active ? "text-teal" : "text-muted"}`}
                      aria-hidden
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{s.title}</span>
                      <span className="num block truncate text-xs text-muted">
                        {formatDay(s.household_date)}
                        {" · "}
                        {working ? "answering…" : s.ended_at ? "ended" : plural(s.turns, "turn")}
                      </span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-line px-4 py-3 text-xs text-muted">
        {household.kind === "ready" ? (
          <p className="truncate">
            <span className="font-semibold text-fg">{household.value.name}</span>
            <span className="num"> · {formatDay(household.value.as_of_date)}</span>
          </p>
        ) : household.kind === "error" ? (
          <p className="text-rose">{household.message}</p>
        ) : (
          <div className="skeleton h-4 w-40" />
        )}
        <Link href="/system" onClick={onNavigate} className="mt-1.5 inline-flex items-center gap-1.5 hover:text-fg">
          <Activity className="size-3.5" aria-hidden />
          System check
        </Link>
      </div>
    </nav>
  );
}
