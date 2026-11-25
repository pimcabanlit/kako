"use client";

import { PanelLeft } from "lucide-react";

import { BrandMark } from "@/components/brand";
import { flipped, SIDEBAR_KEY, sidebarFrom } from "@/lib/sidebar";

export const SIDEBAR_ID = "kako-sidebar";

/** Collapses or opens the sidebar. The page holds the state (`data-sidebar` on <html>, which the
 * layout's script sets before the first paint) and CSS shows the matching side, so the buttons
 * never disagree with what is on screen. Focus moves to the button that undoes it. */
function toggleSidebar() {
  const root = document.documentElement;
  const next = flipped(sidebarFrom(root.getAttribute("data-sidebar")));
  root.setAttribute("data-sidebar", next);
  try {
    localStorage.setItem(SIDEBAR_KEY, next);
  } catch {
    // storage blocked: the choice holds for this visit only
  }
  const undo = next === "collapsed" ? "open" : "collapse";
  document.querySelector<HTMLButtonElement>(`[data-sidebar-toggle="${undo}"]`)?.focus();
}

/** In the sidebar's header, beside the theme switch: collapse it to the rail. In the phone's
 * drawer the same button closes the drawer (`onClose`). */
export function CollapseSidebar({ onClose }: { onClose?: () => void }) {
  const label = onClose ? "Close the sidebar" : "Collapse the sidebar";
  return (
    <button
      type="button"
      onClick={onClose ?? toggleSidebar}
      data-sidebar-toggle={onClose ? undefined : "collapse"}
      aria-controls={onClose ? undefined : SIDEBAR_ID}
      aria-expanded={onClose ? undefined : true}
      className="btn btn-ghost size-9 p-0 text-muted hover:text-fg"
      aria-label={label}
      title={label}
    >
      <PanelLeft className="size-[18px]" aria-hidden />
    </button>
  );
}

/** At the top of the rail: the mark, which turns into the sidebar icon under the pointer or the
 * keyboard's focus, as ChatGPT's does. Opens the sidebar again. */
export function OpenSidebar() {
  return (
    <button
      type="button"
      onClick={toggleSidebar}
      data-sidebar-toggle="open"
      aria-controls={SIDEBAR_ID}
      aria-expanded={false}
      className="group btn btn-ghost size-10 p-0"
      aria-label="Open the sidebar"
      title="Open the sidebar"
    >
      <BrandMark size={26} className="group-hover:hidden group-focus-visible:hidden" />
      <PanelLeft
        className="hidden size-[18px] text-muted group-hover:block group-hover:text-fg group-focus-visible:block group-focus-visible:text-fg"
        aria-hidden
      />
    </button>
  );
}
