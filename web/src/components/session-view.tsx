"use client";

import { CircleX, Flag, LoaderCircle, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { type Loaded, useShell } from "@/components/app-shell";
import { Composer } from "@/components/composer";
import { TopBar } from "@/components/top-bar";
import { KeptTurnView, PendingTurnView } from "@/components/turn";
import { api, ApiError } from "@/lib/api";
import { formatDay } from "@/lib/text";
import type { Proposal, SessionTurns } from "@/lib/types";

type View = Loaded<SessionTurns> | { kind: "missing" };

// How often the screen reads the running turn's steps while Kako answers.
const LIVE_MS = 1500;

/** One session as a conversation: its kept turns, the turn on its way, and the composer. */
export function SessionView({ id }: { id: string }) {
  const { pending, turnsVersion, sendTurn, retryTurn, dismissTurn, household, noteChange } =
    useShell();
  const [view, setView] = useState<View>({ kind: "loading" });
  const [proposals, setProposals] = useState<Loaded<Proposal[]>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [proposalsVersion, setProposalsVersion] = useState(0);
  const mine = pending?.sessionId === id ? pending : null;
  const live = mine?.status === "running";
  const answered = mine?.status === "done";

  // The session's turns: at first, after each turn or decision, and every moment while one runs
  // (for its steps). A failed read keeps what is on screen if there is any.
  useEffect(() => {
    const controller = new AbortController();
    const read = () =>
      api.turns(id, controller.signal).then(
        (value) => setView({ kind: "ready", value }),
        (error: unknown) => {
          if (controller.signal.aborted) return;
          if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
            setView({ kind: "missing" });
            return;
          }
          if (!(error instanceof ApiError)) console.error("Reading the session failed", error);
          const message =
            error instanceof ApiError ? error.message : "Couldn't read this session.";
          setView((v) => (v.kind === "ready" ? v : { kind: "error", message }));
        },
      );
    void read();
    const timer = live ? setInterval(read, LIVE_MS) : undefined;
    return () => {
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [id, attempt, turnsVersion, live]);

  // The household's proposals: what each approval card shows and whether it is decided.
  useEffect(() => {
    const controller = new AbortController();
    api.proposals(controller.signal).then(
      (value) => setProposals({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (!(error instanceof ApiError)) console.error("Reading proposals failed", error);
        setProposals({
          kind: "error",
          message: error instanceof ApiError ? error.message : "Couldn't read the changes.",
        });
      },
    );
    return () => controller.abort();
  }, [proposalsVersion, turnsVersion]);

  const onDecided = useCallback(() => setProposalsVersion((n) => n + 1), []);

  // An answered turn stays on its way until this screen has read it back as a kept turn.
  const kept =
    answered && view.kind === "ready" && view.value.turns.some((t) => t.seed === mine?.seed);
  useEffect(() => {
    if (kept) dismissTurn();
  }, [kept, dismissTurn]);

  // Keep the newest message in view, as chat apps do.
  const end = useRef<HTMLDivElement>(null);
  const turnCount = view.kind === "ready" ? view.value.turns.length : 0;
  const stepCount = view.kind === "ready" ? (view.value.running?.steps.length ?? 0) : 0;
  useLayoutEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [turnCount, mine?.message, mine?.status, stepCount]);

  const people = household.kind === "ready" ? household.value.people : [];
  const nameOf = (personId: string | null) =>
    people.find((p) => p.id === personId)?.display_name ?? null;

  if (view.kind === "loading") return <Skeleton />;
  if (view.kind === "missing") return <Missing />;
  if (view.kind === "error")
    return (
      <>
        <TopBar />
        <main className="grid flex-1 place-items-center px-4">
          <div role="alert" className="panel edge edge-rose max-w-md space-y-3 text-sm">
            <p className="flex items-start gap-2 text-rose">
              <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden />
              {view.message}
            </p>
            <button type="button" className="btn px-3 py-1.5 text-sm" onClick={() => setAttempt((n) => n + 1)}>
              <RefreshCw className="size-3.5" aria-hidden />
              Try again
            </button>
          </div>
        </main>
      </>
    );

  const { session, turns, running } = view.value;
  const ended = session.ended_at !== null;
  const someoneElse = pending?.status === "running" && pending.sessionId !== id;
  // The running turn's steps, from the server; shown only once (never beside its kept turn).
  const runningSteps = live && running ? running.steps : [];

  return (
    <>
      <TopBar>
        <h1 className="min-w-0 truncate text-[15px] font-semibold">{session.title}</h1>
        <span className="chip num shrink-0">{formatDay(session.household_date)}</span>
        {ended && <span className="chip shrink-0">Ended</span>}
        <div className="ml-auto shrink-0">
          {!ended && (
            <EndSession
              sessionId={id}
              disabled={live || turns.length === 0}
              onEnded={() => {
                setAttempt((n) => n + 1);
                noteChange();
              }}
            />
          )}
        </div>
      </TopBar>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-10 px-4 pt-8 pb-10">
          {turns.length === 0 && !mine && (
            <div className="py-16 text-center">
              <p className="display text-[22px]">
                {ended ? "No turns kept in this session" : "Ask the first question"}
              </p>
              <p className="mx-auto mt-2 max-w-md text-muted">
                {ended
                  ? "This session ended without any turns kept here."
                  : "Kako answers with options and the figures behind them. Any change you mention waits for an adult's yes."}
              </p>
            </div>
          )}
          {turns.map((t) => (
            <KeptTurnView key={t.seed} turn={t} proposals={proposals} onDecided={onDecided} />
          ))}
          {mine && !kept && (
            <PendingTurnView
              name={nameOf(mine.saidBy)}
              message={mine.message}
              steps={runningSteps}
              error={mine.status === "failed" ? mine.error : undefined}
              onRetry={retryTurn}
              onDismiss={dismissTurn}
            />
          )}
          <div ref={end} />
        </div>
      </main>
      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        {ended ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-surface/70 px-4 py-3 text-sm">
            <p className="text-muted">This session has ended. Its dreaming run looks for what to remember.</p>
            <Link href="/" className="btn btn-primary px-3 py-1.5 text-sm">
              <Plus className="size-4" aria-hidden />
              New session
            </Link>
          </div>
        ) : (
          <Composer
            onSend={(message) => sendTurn(id, message)}
            busy={live || answered}
            disabledReason={
              household.kind === "error"
                ? household.message
                : someoneElse
                  ? "Kako is still answering in another session."
                  : null
            }
          />
        )}
      </div>
    </>
  );
}

function EndSession({
  sessionId,
  disabled,
  onEnded,
}: {
  sessionId: string;
  disabled: boolean;
  onEnded: () => void;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A question left open on a screen you leave closes (the route stays mounted but hidden).
  useLayoutEffect(() => () => setAsking(false), []);

  const end = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.endSession(sessionId);
      setAsking(false);
      onEnded();
    } catch (e) {
      if (!(e instanceof ApiError)) console.error("Ending the session failed", e);
      setError(e instanceof ApiError ? e.message : "The session didn't end.");
    } finally {
      setBusy(false);
    }
  };

  if (!asking)
    return (
      <button
        type="button"
        className="btn btn-ghost px-2.5 py-1.5 text-[13px] text-muted"
        disabled={disabled}
        onClick={() => setAsking(true)}
        title="End the session: no more turns, and Kako's dreaming looks over it"
      >
        <Flag className="size-3.5" aria-hidden />
        <span className="hidden sm:inline">End session</span>
        <span className="sr-only sm:hidden">End session</span>
      </button>
    );
  return (
    <span className="flex items-center gap-2 text-[13px]">
      {error ? <span className="text-rose">{error}</span> : <span className="hidden text-muted sm:inline">No more turns after this.</span>}
      <button type="button" className="btn px-2.5 py-1 text-[13px]" disabled={busy} onClick={end}>
        {busy && <LoaderCircle className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden />}
        End it
      </button>
      <button type="button" className="btn btn-ghost px-2.5 py-1 text-[13px]" onClick={() => setAsking(false)}>
        Cancel
      </button>
    </span>
  );
}

export function Skeleton() {
  return (
    <>
      <TopBar>
        <div className="skeleton h-5 w-48" />
      </TopBar>
      <main className="flex-1 overflow-hidden" aria-busy="true" aria-label="Loading the session">
        <div className="mx-auto w-full max-w-3xl space-y-8 px-4 pt-8">
          <div className="ml-auto h-12 w-2/3 skeleton" />
          <div className="space-y-2.5">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-11/12" />
            <div className="skeleton h-4 w-3/4" />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="skeleton h-40" />
            <div className="skeleton h-40" />
          </div>
        </div>
      </main>
    </>
  );
}

function Missing() {
  return (
    <>
      <TopBar />
      <main className="grid flex-1 place-items-center px-4 text-center">
        <div className="space-y-3">
          <p className="display text-[22px]">No such session</p>
          <p className="text-muted">It may belong to another household, or the link is wrong.</p>
          <Link href="/" className="btn btn-primary">
            <Plus className="size-4" aria-hidden />
            New session
          </Link>
        </div>
      </main>
    </>
  );
}
