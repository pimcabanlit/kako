"use client";

import { Menu } from "lucide-react";
import type { ReactNode } from "react";

import { useShell } from "@/components/app-shell";

/** The bar above the conversation: on a phone, the button that opens the sessions. */
export function TopBar({ children }: { children?: ReactNode }) {
  const { openDrawer } = useShell();
  return (
    <header className="flex min-h-14 items-center gap-2 border-b border-line/70 px-3 md:px-6">
      <button
        type="button"
        onClick={openDrawer}
        className="btn btn-ghost size-9 p-0 md:hidden"
        aria-label="Open the sessions"
      >
        <Menu className="size-5" aria-hidden />
      </button>
      <div className="flex min-w-0 flex-1 items-center gap-3">{children}</div>
    </header>
  );
}
