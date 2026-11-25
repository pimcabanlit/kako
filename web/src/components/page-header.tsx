"use client";

import type { ReactNode } from "react";

/** A screen's title, large at the top left, with a line under it and, below, its view chips. */
export function PageHeader({
  title,
  note,
  children,
}: {
  title: string;
  note?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="space-y-5">
      <div className="space-y-1.5">
        <h1 className="display text-[28px] leading-tight md:text-[34px]">{title}</h1>
        {note && <p className="text-[14px] text-muted">{note}</p>}
      </div>
      {children}
    </header>
  );
}

export type View<T extends string> = { id: T; label: string };

/** A screen's views as chips ("What happened", "Each thing"): one chosen at a time. Tabs for
 * assistive technology, arrow keys moving between them. */
export function ViewChips<T extends string>({
  label,
  views,
  chosen,
  onChoose,
}: {
  label: string;
  views: readonly View<T>[];
  chosen: T;
  onChoose: (id: T) => void;
}) {
  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const at = views.findIndex((v) => v.id === chosen);
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = views[(at + step + views.length) % views.length];
    if (!next) return;
    event.preventDefault();
    onChoose(next.id);
    document.getElementById(`tab-${next.id}`)?.focus();
  }
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-2" onKeyDown={onKeyDown}>
      {views.map((v) => {
        const on = v.id === chosen;
        return (
          <button
            key={v.id}
            type="button"
            role="tab"
            id={`tab-${v.id}`}
            aria-selected={on}
            aria-controls={`panel-${v.id}`}
            tabIndex={on ? 0 : -1}
            onClick={() => onChoose(v.id)}
            className={`rounded-full border px-4 py-1.5 text-[14px] font-semibold whitespace-nowrap transition-colors ${
              on
                ? "border-line-strong bg-raised text-fg"
                : "border-transparent text-muted hover:bg-raised/60 hover:text-fg"
            }`}
          >
            {v.label}
          </button>
        );
      })}
    </div>
  );
}
