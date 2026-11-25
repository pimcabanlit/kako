"use client";

import { CircleX, RefreshCw } from "lucide-react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { type RefObject, useEffect, useRef, useState } from "react";

import { useShell } from "@/components/app-shell";
import { Brand } from "@/components/brand";
import { Composer } from "@/components/composer";
import { TopBar } from "@/components/top-bar";
import { api, ApiError } from "@/lib/api";
import { titleFrom } from "@/lib/text";

// Questions any household could ask; none of them depends on the demo's data.
const STARTERS = [
  "How are we doing this month?",
  "Can we pay down a debt faster?",
  "How long until our emergency fund is full?",
];

/** A new session, empty, as chat apps open: a greeting, the composer, a few starters. The first
 * message starts the session (its title is that message) and is sent as its first turn. */
export function NewSession() {
  const router = useRouter();
  const { sendTurn, reloadSessions, pending, household } = useShell();
  const [starting, setStarting] = useState(false);
  const [failed, setFailed] = useState<{ message: string; error: string } | null>(null);
  const running = pending?.status === "running";
  const startersRow = useRef<HTMLDivElement>(null);
  const startersScroll = useScrolls(startersRow);
  const noHousehold = household.kind === "error" ? household.message : null;

  const start = async (message: string) => {
    setStarting(true);
    setFailed(null);
    try {
      const { id } = await api.startSession(titleFrom(message));
      reloadSessions();
      router.push(`/sessions/${id}`);
      void sendTurn(id, message);
    } catch (error) {
      if (!(error instanceof ApiError)) console.error("Starting a session failed", error);
      setFailed({
        message,
        error: error instanceof ApiError ? error.message : "Couldn't start the session.",
      });
    } finally {
      setStarting(false);
    }
  };

  return (
    <>
      <div className="md:hidden">
        <TopBar>
          <Brand size="sm" />
        </TopBar>
      </div>
      <main className="dust flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10">
          <div className="mx-auto mb-8 w-full max-w-[420px] overflow-hidden rounded-[20px] border border-line-strong shadow-[var(--shadow)]">
            <Image
              src="/swirl.jpg"
              alt="kako"
              width={1400}
              height={724}
              sizes="(min-width: 452px) 420px, calc(100vw - 32px)"
              priority
              className="block h-auto w-full"
            />
          </div>
          <h1 className="display text-center text-[28px] leading-tight md:text-[34px]">
            What should we <span className="grad-text">plan</span> today?
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-center text-muted">
            Ask about your budget, debts, savings or goals. Kako&rsquo;s specialists look into it,
            the engine checks every figure, and nothing changes until one of you says yes.
          </p>
          <div className="mt-8">
            <Composer
              onSend={start}
              busy={starting}
              autoFocus
              disabledReason={
                noHousehold ??
                (running ? "Kako is still answering in another session." : null)
              }
            />
          </div>
          {failed && (
            <div role="alert" className="panel edge edge-rose mt-4 flex flex-wrap items-center gap-3 text-sm">
              <CircleX className="size-4 text-rose" aria-hidden />
              <span className="min-w-0 flex-1">{failed.error}</span>
              <button type="button" className="btn px-3 py-1.5 text-sm" onClick={() => start(failed.message)}>
                <RefreshCw className="size-3.5" aria-hidden />
                Try again
              </button>
            </div>
          )}
          {/* One line, as chat apps show them (Pim, Nov 25): centred when they fit, as they do in
              the column's full width on a laptop, and on a narrower screen a row that scrolls
              sideways rather than a second line, in line with the composer and fading at its
              right edge to say there is more. */}
          <div
            ref={startersRow}
            className={`-mx-4 mt-6 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${
              startersScroll
                ? "[mask-image:linear-gradient(to_right,black_calc(100%-40px),transparent)]"
                : "md:px-0"
            }`}
          >
            <ul className="mx-auto flex w-max gap-1.5" aria-label="Questions to start with">
              {STARTERS.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    disabled={starting || running || Boolean(noHousehold)}
                    onClick={() => start(q)}
                    className="btn rounded-full px-3 py-1.5 text-[13.5px] font-medium whitespace-nowrap text-muted hover:text-fg"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </main>
    </>
  );
}

/** Whether a row is wider than its box, so it scrolls sideways; checked again whenever the box
 * changes size. */
function useScrolls(row: RefObject<HTMLElement | null>): boolean {
  const [scrolls, setScrolls] = useState(false);
  useEffect(() => {
    const el = row.current;
    if (!el) return;
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1);
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [row]);
  return scrolls;
}
