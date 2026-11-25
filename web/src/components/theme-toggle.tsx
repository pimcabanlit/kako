"use client";

import { Moon, Sun } from "lucide-react";

import { THEME_KEY } from "@/lib/theme";

/** Dark first, light just as finished. The choice is kept on this device; the layout's script
 * applies it before the first paint. Reads the theme from the page, so it never disagrees. */
export function ThemeToggle() {
  const toggle = () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // storage blocked: the theme holds for this visit only
    }
  };
  return (
    <button
      type="button"
      onClick={toggle}
      className="btn btn-ghost size-9 p-0"
      aria-label="Switch between dark and light"
      title="Switch between dark and light"
    >
      {/* Both icons are drawn; CSS shows the one for the theme you'd switch to. */}
      <Sun className="size-4 [[data-theme=light]_&]:hidden" aria-hidden />
      <Moon className="hidden size-4 [[data-theme=light]_&]:block" aria-hidden />
    </button>
  );
}
