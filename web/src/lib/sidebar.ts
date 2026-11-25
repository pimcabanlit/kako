// The sidebar on a wide screen: open, as it starts, or collapsed to a rail of icons, as chat apps
// do. The choice is kept on this device, like the theme, and set before the first paint by the
// layout's script, so the page never opens one way and jumps to the other.

export type SidebarState = "open" | "collapsed";

export const SIDEBAR_KEY = "kako-sidebar";

/** What a saved value means: only "collapsed" collapses; anything else, or nothing, is open. */
export function sidebarFrom(saved: string | null | undefined): SidebarState {
  return saved === "collapsed" ? "collapsed" : "open";
}

/** The other state, for the one button that switches. */
export function flipped(state: SidebarState): SidebarState {
  return state === "collapsed" ? "open" : "collapsed";
}
