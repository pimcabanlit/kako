"use client";

// The app's frame, laid out like the chat apps people already know: the sessions down the left,
// the conversation in the middle, the composer at the bottom. It also holds what every screen
// shares: the household and its people, who is writing, the sessions list, and the one turn that
// can run at a time (so it survives moving from the new-session screen to the session).

import {
  createContext,
  type ReactNode,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { Sidebar, SidebarRail } from "@/components/sidebar";
import { SIDEBAR_ID } from "@/components/sidebar-toggle";
import { api, ApiError } from "@/lib/api";
import { landed, mayHaveLanded } from "@/lib/turns";
import type { Household, SessionSummary } from "@/lib/types";

export type Loaded<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; value: T };

export type PendingTurn = {
  sessionId: string;
  message: string;
  saidBy: string | null;
  /** running; done once answered (until the session's screen reads the kept turn); failed. */
  status: "running" | "done" | "failed";
  seed?: string;
  error?: string;
};

type Shell = {
  household: Loaded<Household>;
  reloadHousehold: () => void;
  sessions: Loaded<SessionSummary[]>;
  reloadSessions: () => void;
  speakerId: string | null;
  setSpeakerId: (id: string) => void;
  pending: PendingTurn | null;
  /** Bumped when a session's turns change, so its screen reads them again. */
  turnsVersion: number;
  sendTurn: (sessionId: string, message: string) => Promise<void>;
  retryTurn: () => void;
  dismissTurn: () => void;
  noteChange: () => void;
  openDrawer: () => void;
};

const ShellContext = createContext<Shell | null>(null);

export function useShell(): Shell {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error("useShell outside AppShell");
  return shell;
}

const SPEAKER_KEY = "kako-speaker";

// How often, and for how long, a turn whose request ended with no answer is looked for.
const LANDED_POLL_MS = 2000;
const LANDED_POLLS = 150;

/** The session's kept turns before a turn is sent; null when they can't be read. */
async function seedsOf(sessionId: string): Promise<string[] | null> {
  try {
    return (await api.turns(sessionId)).turns.map((t) => t.seed);
  } catch {
    return null; // the turn's own request will say what is wrong
  }
}

/** The seed of the turn if the backend kept it after all, waiting while it still runs. */
async function keptAnyway(turn: PendingTurn, before: string[]): Promise<string | null> {
  for (let i = 0; i < LANDED_POLLS; i++) {
    let now;
    try {
      now = await api.turns(turn.sessionId);
    } catch {
      return null;
    }
    const found = landed(before, now, turn.message);
    if (found.kind === "kept") return found.seed;
    if (found.kind === "lost") return null;
    await new Promise((resolve) => setTimeout(resolve, LANDED_POLL_MS));
  }
  return null;
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  console.error(fallback, error);
  return fallback;
}

function useLoaded<T>(
  load: (signal: AbortSignal) => Promise<T>,
  what: string,
): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (value) => setState({ kind: "ready", value }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "error", message: errorMessage(error, `Couldn't read ${what}.`) });
      },
    );
    return () => controller.abort();
  }, [attempt, load, what]);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return [state, reload];
}

export function AppShell({ children }: { children: ReactNode }) {
  const [household, reloadHousehold] = useLoaded(api.household, "the household");
  const [sessions, reloadSessions] = useLoaded(api.sessions, "the sessions");
  const [chosen, setChosen] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingTurn | null>(null);
  const [turnsVersion, setTurnsVersion] = useState(0);
  const [drawer, setDrawer] = useState(false);

  // Who is writing: as chosen, else as last saved on this device, else the first adult.
  const people = household.kind === "ready" ? household.value.people : [];
  const saved = useMemo(() => {
    try {
      return typeof window === "undefined" ? null : localStorage.getItem(SPEAKER_KEY);
    } catch {
      return null; // storage blocked: fall back to the first adult
    }
  }, []);
  const speakerId =
    [chosen, saved].find((id) => id && people.some((p) => p.id === id)) ??
    people.find((p) => p.role === "adult")?.id ??
    people[0]?.id ??
    null;
  const setSpeakerId = useCallback((id: string) => {
    setChosen(id);
    try {
      localStorage.setItem(SPEAKER_KEY, id);
    } catch {
      // storage blocked: the choice holds for this visit only
    }
  }, []);

  const noteChange = useCallback(() => {
    setTurnsVersion((n) => n + 1);
    reloadSessions();
  }, [reloadSessions]);

  const run = useCallback(
    async (turn: PendingTurn) => {
      setPending({ ...turn, status: "running", error: undefined });
      const before = await seedsOf(turn.sessionId);
      try {
        const answer = await api.takeTurn(turn.sessionId, turn.message, turn.saidBy);
        // Held until the session's screen has read the kept turn, so the answer never blinks.
        setPending({ ...turn, status: "done", seed: answer.seed });
      } catch (error) {
        // The connection may have ended before a long turn did: look before calling it failed.
        const seed =
          before && error instanceof ApiError && mayHaveLanded(error.status)
            ? await keptAnyway(turn, before)
            : null;
        setPending(
          seed
            ? { ...turn, status: "done", seed }
            : {
                ...turn,
                status: "failed",
                error: errorMessage(error, "The turn stopped before Kako could answer."),
              },
        );
      }
      noteChange();
    },
    [noteChange],
  );

  const sendTurn = useCallback(
    (sessionId: string, message: string) =>
      run({ sessionId, message, saidBy: speakerId, status: "running" }),
    [run, speakerId],
  );
  const retryTurn = useCallback(() => {
    if (pending && pending.status === "failed") void run(pending);
  }, [pending, run]);
  const dismissTurn = useCallback(() => setPending(null), []);

  // The drawer closes on Escape, as a dialog does.
  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer]);

  const shell: Shell = {
    household,
    reloadHousehold,
    sessions,
    reloadSessions,
    speakerId,
    setSpeakerId,
    pending,
    turnsVersion,
    sendTurn,
    retryTurn,
    dismissTurn,
    noteChange,
    openDrawer: () => setDrawer(true),
  };

  return (
    <ShellContext.Provider value={shell}>
      <div className="flex h-dvh overflow-hidden">
        {/* Open or collapsed to the rail, as the page says (data-sidebar on <html>): CSS picks the
            side, so the choice holds from the first paint. */}
        <aside
          id={SIDEBAR_ID}
          className="hidden w-[272px] shrink-0 overflow-hidden border-r border-line bg-surface/60 backdrop-blur transition-[width] duration-200 ease-out motion-reduce:transition-none md:flex collapsed:w-[60px]"
        >
          <div className="flex w-[272px] shrink-0 collapsed:hidden">
            <Suspense fallback={null}>
              <Sidebar />
            </Suspense>
          </div>
          <div className="hidden w-[60px] shrink-0 collapsed:flex">
            <Suspense fallback={null}>
              <SidebarRail />
            </Suspense>
          </div>
        </aside>
        {drawer && (
          <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Sessions">
            <button
              type="button"
              aria-label="Close the sessions"
              className="absolute inset-0 bg-black/50"
              onClick={() => setDrawer(false)}
            />
            <aside className="relative flex h-full w-[82%] max-w-[300px] border-r border-line bg-surface">
              <Suspense fallback={null}>
                <Sidebar onNavigate={() => setDrawer(false)} onClose={() => setDrawer(false)} />
              </Suspense>
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
    </ShellContext.Provider>
  );
}
