"use client";

import {
  Activity,
  BookOpen,
  ChevronUp,
  ClipboardList,
  Gauge,
  History,
  type LucideIcon,
  MessageSquare,
  Plus,
  RefreshCw,
  Signpost,
  Users,
  Wallet,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { useShell } from "@/components/app-shell";
import { Brand } from "@/components/brand";
import { CollapseSidebar, OpenSidebar } from "@/components/sidebar-toggle";
import { ThemeToggle } from "@/components/theme-toggle";
import { formatDay } from "@/lib/text";
import { listOf, plural } from "@/lib/working";

// The screens above the sessions: where the money stands, what the household plans, its story,
// and what it decided.
const SCREENS: { href: string; label: string; note: string; icon: LucideIcon }[] = [
  { href: "/money", label: "Money", note: "where it all stands", icon: Wallet },
  { href: "/plans", label: "Plan", note: "why and what changed", icon: ClipboardList },
  { href: "/timeline", label: "Timeline", note: "what happened when", icon: History },
  { href: "/decisions", label: "Decisions", note: "and what to revisit", icon: Signpost },
  { href: "/metrics", label: "Metrics", note: "what Kako measured", icon: Gauge },
];

/** Whether a screen's link is the one open: the screen itself or a page under it. */
function isHere(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The sessions down the left, newest first, with "New session" and the screens at the top. The
 * header's last button collapses it to the rail (`SidebarRail`), or in the phone's drawer closes the
 * drawer (`onClose`). */
export function Sidebar({ onNavigate, onClose }: { onNavigate?: () => void; onClose?: () => void }) {
  const { sessions, reloadSessions, pending } = useShell();
  const pathname = usePathname();

  return (
    <nav aria-label="Sessions and screens" className="flex h-full w-full flex-col">
      <div className="flex items-center justify-between gap-2 pt-3.5 pr-2.5 pb-3 pl-4">
        <Link href="/" onClick={onNavigate} className="rounded-lg" aria-label="Kako, new session">
          <Brand />
        </Link>
        <div className="flex items-center gap-0.5">
          <ThemeToggle />
          <CollapseSidebar onClose={onClose} />
        </div>
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
        <ul className="mt-1.5 space-y-0.5">
          {SCREENS.map(({ href, label, note, icon: Icon }) => {
            const here = isHere(pathname, href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  onClick={onNavigate}
                  aria-current={here ? "page" : undefined}
                  className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm font-medium transition-colors ${
                    here ? "bg-raised text-fg" : "text-fg/90 hover:bg-raised/70"
                  }`}
                >
                  <Icon className={`size-4 shrink-0 ${here ? "text-teal" : "text-muted"}`} aria-hidden />
                  {label}
                  <span className="ml-auto truncate text-xs font-normal text-muted">{note}</span>
                </Link>
              </li>
            );
          })}
        </ul>
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

      <HouseholdMenu onNavigate={onNavigate} />
    </nav>
  );
}

/** The sidebar collapsed, as ChatGPT's does: a rail of icons, each named on hover and to a screen
 * reader. The mark at the top opens the sidebar again; "New session" and the screens stay a click
 * away, and the foot keeps the household menu's System check and Documentation and the theme switch.
 * The sessions and the household wait in the open sidebar. */
export function SidebarRail() {
  const pathname = usePathname();
  const item = (here: boolean) =>
    `grid size-10 place-items-center rounded-xl transition-colors ${
      here ? "bg-raised text-teal" : "text-muted hover:bg-raised/70 hover:text-fg"
    }`;

  return (
    <nav aria-label="Screens" className="flex h-full w-full flex-col items-center gap-1 py-3">
      <OpenSidebar />
      <Link
        href="/"
        aria-label="New session"
        title="New session"
        aria-current={pathname === "/" ? "page" : undefined}
        className={`mt-2 ${item(pathname === "/")}`}
      >
        <Plus className="size-[18px]" aria-hidden />
      </Link>
      <ul className="flex flex-col items-center gap-1">
        {SCREENS.map(({ href, label, note, icon: Icon }) => {
          const here = isHere(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-label={label}
                title={`${label}: ${note}`}
                aria-current={here ? "page" : undefined}
                className={item(here)}
              >
                <Icon className="size-[18px]" aria-hidden />
              </Link>
            </li>
          );
        })}
      </ul>
      <ul className="mt-auto flex flex-col items-center gap-1">
        {MENU.map(({ href, label, note, icon: Icon }) => {
          const here = isHere(pathname, href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-label={label}
                title={`${label}: ${note}`}
                aria-current={here ? "page" : undefined}
                className={item(here)}
              >
                <Icon className="size-[18px]" aria-hidden />
              </Link>
            </li>
          );
        })}
        <li>
          <ThemeToggle />
        </li>
      </ul>
    </nav>
  );
}

// The household at the foot of the sidebar opens a small menu above it: the system check, the
// documentation, and who the household is (docs/architecture.md, "The documentation screen").
const MENU: { href: string; label: string; note: string; icon: LucideIcon; badge?: string }[] = [
  { href: "/system", label: "System check", note: "Postgres, Meko and the models, live", icon: Activity },
  { href: "/docs", label: "Documentation", note: "How Kako works and uses Meko", icon: BookOpen, badge: "new" },
];

function HouseholdMenu({ onNavigate }: { onNavigate?: () => void }) {
  const { household } = useShell();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const go = () => {
    setOpen(false);
    onNavigate?.();
  };

  return (
    <div ref={box} className="relative border-t border-line px-3 py-2.5">
      {open && (
        <div
          id={menuId}
          className="absolute right-3 bottom-[calc(100%+6px)] left-3 z-20 rounded-[14px] border border-line-strong bg-surface p-1.5 shadow-[0_20px_50px_-20px_rgba(0,0,0,0.6)]"
        >
          <ul>
            {MENU.map(({ href, label, note, icon: Icon, badge }) => {
              const here = isHere(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={go}
                    aria-current={here ? "page" : undefined}
                    className={`flex items-start gap-2.5 rounded-[10px] px-2.5 py-2 text-sm transition-colors ${
                      here ? "bg-raised" : "hover:bg-raised"
                    }`}
                  >
                    <Icon className={`mt-0.5 size-4 shrink-0 ${here ? "text-teal" : "text-muted"}`} aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{label}</span>
                      <span className="block text-xs text-muted">{note}</span>
                    </span>
                    {badge && <span className="chip chip-meko px-1.5 py-0 text-[10.5px]">{badge}</span>}
                  </Link>
                </li>
              );
            })}
          </ul>
          {household.kind === "ready" && household.value.people.length > 0 && (
            <div className="mt-1 flex items-start gap-2.5 border-t border-line px-2.5 pt-2.5 pb-1.5 text-sm">
              <Users className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
              <span>
                <span className="block font-medium">The household</span>
                <span className="block text-xs text-muted">
                  {listOf(household.value.people.map((p) => p.display_name))}
                </span>
              </span>
            </div>
          )}
        </div>
      )}
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center gap-2.5 rounded-[10px] border px-2.5 py-2 text-left text-xs transition-colors ${
          open ? "border-line bg-raised" : "border-transparent hover:border-line hover:bg-raised"
        }`}
      >
        <span className="min-w-0 flex-1">
          {household.kind === "ready" ? (
            <>
              <span className="block truncate text-[13px] font-semibold text-fg">{household.value.name}</span>
              <span className="num block text-muted">{formatDay(household.value.as_of_date)}</span>
            </>
          ) : household.kind === "error" ? (
            <span className="block text-rose">{household.message}</span>
          ) : (
            <span className="skeleton block h-4 w-40" />
          )}
          <span className="sr-only">: system check, documentation and the household</span>
        </span>
        <ChevronUp
          className={`size-4 shrink-0 text-muted transition-transform ${open ? "" : "rotate-180"}`}
          aria-hidden
        />
      </button>
    </div>
  );
}
