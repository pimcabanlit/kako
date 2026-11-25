"use client";

import { Check, LoaderCircle, X } from "lucide-react";
import { useId, useState } from "react";

import { type Loaded, useShell } from "@/components/app-shell";
import { api, ApiError } from "@/lib/api";
import { formatDay } from "@/lib/text";
import type { Change, Proposal } from "@/lib/types";
import { lifeEvent, proposalTitle } from "@/lib/words";

type CardState = "pending" | "approved" | "rejected" | "expired" | "mixed" | "unknown";

function stateOf(found: Proposal[]): CardState {
  if (found.length === 0) return "unknown";
  const statuses = new Set(found.map((p) => p.status));
  if (statuses.size > 1) return "mixed";
  const [only] = statuses;
  return only === "pending" || only === "approved" || only === "rejected" || only === "expired"
    ? only
    : "mixed";
}

function Row({ change, proposal }: { change: Change; proposal: Proposal | undefined }) {
  const event = proposal ? lifeEvent(proposal) : null;
  if (proposal?.change) {
    const c = proposal.change;
    return (
      <li className="space-y-1">
        <p className="text-sm font-semibold">{proposalTitle(proposal)}</p>
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          {c.before && (
            <>
              <s className="num text-base text-muted decoration-[1.5px]">{c.before}</s>
              <span className="text-muted" aria-hidden>
                →
              </span>
            </>
          )}
          {c.after ? (
            <span className="display num text-[26px] leading-tight md:text-[30px]">{c.after}</span>
          ) : (
            <span className="text-sm text-rose">retracted</span>
          )}
          {c.from_day && <span className="text-[13px] text-muted">from {c.from_day}</span>}
        </p>
      </li>
    );
  }
  if (proposal && event) {
    return (
      <li className="flex flex-wrap items-center gap-2">
        <span className="chip chip-orange chip-dot">{proposalTitle(proposal)}</span>
        <span className="text-sm">
          {event.description}, <span className="num text-muted">{formatDay(event.on)}</span>
        </span>
      </li>
    );
  }
  return <li className="text-sm">{proposal?.shown ?? change.shown}</li>;
}

/** The changes a turn held for the household's yes, inline in the conversation. Gold, its edge
 * sweeping, while it waits; emerald and "Current" once approved; nothing is written before. The
 * changes of one turn are approved or rejected together: a life event goes with its facts. */
export function ApprovalCard({
  changes,
  proposals,
  onDecided,
}: {
  changes: Change[];
  proposals: Loaded<Proposal[]>;
  onDecided: () => void;
}) {
  const { household, speakerId, noteChange } = useShell();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const titleId = useId();

  const all = proposals.kind === "ready" ? proposals.value : [];
  const byId = new Map(all.map((p) => [p.id, p]));
  const found = changes.map((c) => byId.get(c.proposal_id)).filter((p): p is Proposal => !!p);
  const state = proposals.kind === "ready" ? stateOf(found) : "unknown";
  const evidence = found.flatMap((p) => p.evidence).find((e) => e.quote);
  const decidedBy = found.find((p) => p.decided_by)?.decided_by;
  const people = household.kind === "ready" ? household.value.people : [];
  const speaker = people.find((p) => p.id === speakerId);
  const isAdult = speaker?.role === "adult";
  const waiting = found.filter((p) => p.status === "pending").map((p) => p.id);

  const decide = async (action: "approve" | "reject") => {
    if (!speakerId || waiting.length === 0) return;
    setBusy(action);
    setError(null);
    try {
      await api.decide(action, waiting, speakerId);
      onDecided();
      noteChange();
    } catch (e) {
      if (!(e instanceof ApiError)) console.error("Deciding failed", e);
      setError(e instanceof ApiError ? e.message : "The decision wasn't saved.");
    } finally {
      setBusy(null);
    }
  };

  // The glow means state: none when the card's proposals are unread, expired or not found.
  const edge =
    state === "approved"
      ? "edge edge-emerald"
      : state === "rejected"
        ? "edge edge-rose"
        : state === "pending" || state === "mixed"
          ? "edge edge-gold sweep"
          : "";
  return (
    <section
      aria-labelledby={titleId}
      className={`panel ${edge} space-y-3.5`}
      data-state={state}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={titleId} className="display text-[17px]">
          {changes.length === 1 ? "A change to approve" : "Changes to approve together"}
        </h3>
        {state === "approved" && <span className="chip chip-emerald chip-dot">Current</span>}
        {state === "rejected" && <span className="chip chip-rose chip-dot">Rejected</span>}
        {state === "expired" && <span className="chip chip-dot">Expired</span>}
        {(state === "pending" || state === "mixed") && (
          <span className="chip chip-gold chip-dot">Waiting for your yes</span>
        )}
      </div>

      {proposals.kind === "loading" && <div className="skeleton h-12" />}
      <ul className="space-y-3">
        {changes.map((c) => (
          <Row key={c.proposal_id} change={c} proposal={byId.get(c.proposal_id)} />
        ))}
      </ul>

      {evidence && (
        <p className="quote">
          <q className="text-fg">{evidence.quote}</q>
          {evidence.said_by && <span> — {evidence.said_by}</span>}
        </p>
      )}

      {proposals.kind === "error" && <p className="text-sm text-rose">{proposals.message}</p>}
      {error && (
        <p role="alert" className="text-sm text-rose">
          {error}
        </p>
      )}

      {state === "approved" && (
        <p className="text-[13px] font-semibold text-emerald">
          Approved{decidedBy ? ` by ${decidedBy}` : ""}. Kako replans from it in this session&rsquo;s
          next turn.
        </p>
      )}
      {state === "rejected" && (
        <p className="text-[13px] text-muted">
          Rejected{decidedBy ? ` by ${decidedBy}` : ""}. Nothing was written.
        </p>
      )}
      {state === "expired" && (
        <p className="text-[13px] text-muted">Expired before anyone decided. Nothing was written.</p>
      )}
      {waiting.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={!isAdult || busy !== null}
            onClick={() => decide("approve")}
          >
            {busy === "approve" ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <Check className="size-4" aria-hidden />
            )}
            Approve{speaker ? ` as ${speaker.display_name}` : ""}
          </button>
          <button
            type="button"
            className="btn"
            disabled={!isAdult || busy !== null}
            onClick={() => decide("reject")}
          >
            {busy === "reject" ? (
              <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
            ) : (
              <X className="size-4" aria-hidden />
            )}
            Reject
          </button>
          {speaker && !isAdult && (
            <span className="text-[13px] text-muted">
              Only an adult can approve. Switch who is writing below.
            </span>
          )}
        </div>
      )}
    </section>
  );
}
