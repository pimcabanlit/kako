"use client";

import { ArrowUp, ChevronDown, LoaderCircle } from "lucide-react";
import { type FormEvent, type KeyboardEvent, useId, useRef, useState } from "react";

import { useShell } from "@/components/app-shell";

// The backend's limit on a message (agents/tools.py, MESSAGE_CHARS).
export const MESSAGE_CHARS = 2000;

/** The message box at the bottom, as in any chat app: Enter sends, Shift+Enter starts a new line.
 * Who is writing sits inside it, where chat apps put the model picker: Mara and Jun share the
 * household, so every message says who wrote it. */
export function Composer({
  onSend,
  busy,
  disabledReason,
  placeholder = "Ask Kako about your budget, debts, savings or goals",
  autoFocus = false,
}: {
  onSend: (message: string) => void | Promise<void>;
  busy: boolean;
  disabledReason?: string | null;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  const { household, speakerId, setSpeakerId } = useShell();
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const pickerId = useId();
  const people = household.kind === "ready" ? household.value.people : [];
  const message = text.trim();
  const blocked = Boolean(disabledReason) || busy;
  const canSend = !blocked && message.length > 0 && message.length <= MESSAGE_CHARS;

  const grow = () => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  };

  const send = (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    setText("");
    requestAnimationFrame(grow);
    void onSend(message);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send();
    }
  };

  return (
    <form onSubmit={send} className="w-full">
      <div className="rounded-[22px] border border-line-strong bg-surface/90 p-2 shadow-[var(--shadow)] backdrop-blur focus-within:border-teal/70">
        <label htmlFor={`${pickerId}-text`} className="sr-only">
          Message
        </label>
        <textarea
          id={`${pickerId}-text`}
          ref={box}
          rows={1}
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => {
            setText(e.target.value);
            grow();
          }}
          onKeyDown={onKeyDown}
          placeholder={disabledReason ?? placeholder}
          disabled={Boolean(disabledReason)}
          className="block max-h-60 w-full resize-none bg-transparent px-3 pt-2 pb-1 text-[15px] leading-6 text-fg outline-none placeholder:text-muted focus-visible:outline-none disabled:cursor-not-allowed"
        />
        <div className="flex items-center justify-between gap-2 px-1 pt-1">
          <div className="relative flex items-center">
            <label htmlFor={pickerId} className="sr-only">
              Writing as
            </label>
            <span className="pointer-events-none absolute left-3 text-xs text-muted" aria-hidden>
              Writing as
            </span>
            <select
              id={pickerId}
              value={speakerId ?? ""}
              onChange={(e) => setSpeakerId(e.target.value)}
              disabled={people.length === 0}
              className="appearance-none rounded-full border border-line bg-raised py-1.5 pr-8 pl-[5.4rem] text-sm font-semibold text-fg hover:border-line-strong"
            >
              {people.length === 0 && <option value="">…</option>}
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2.5 size-4 text-muted" aria-hidden />
          </div>
          <div className="flex items-center gap-3">
            {message.length > MESSAGE_CHARS - 200 && (
              <span className={`num text-xs ${message.length > MESSAGE_CHARS ? "text-rose" : "text-muted"}`}>
                {message.length}/{MESSAGE_CHARS}
              </span>
            )}
            <button
              type="submit"
              disabled={!canSend}
              aria-label={busy ? "Kako is answering" : "Send"}
              className="btn btn-primary size-9 rounded-full p-0 disabled:opacity-40 disabled:shadow-none"
            >
              {busy ? (
                <LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
              ) : (
                <ArrowUp className="size-4" aria-hidden />
              )}
            </button>
          </div>
        </div>
      </div>
      <Disclaimer />
    </form>
  );
}

/** The line every screen keeps (docs/look-and-feel.md, style rule 7). */
export function Disclaimer() {
  return (
    <p className="mt-2 text-center text-xs text-muted">
      Synthetic data. Not financial advice. Every figure comes from Kako&rsquo;s engine, never from the
      agents.
    </p>
  );
}
