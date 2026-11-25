// What the documentation says about Meko on this machine, from the health check: off (the laptop's
// sandbox, KAKO_MEKO_OFF), local Meko, Meko Cloud, or out of reach. Pure.

import type { HealthReport } from "../health.ts";

export type MekoHere = "off" | "local" | "cloud" | "unreachable";

/** The backend says Meko is off with this detail (backend/src/kako/meko/health.py). */
const OFF_DETAIL = "off here";

export function mekoHere(report: HealthReport): MekoHere {
  if (report.meko.detail.startsWith(OFF_DETAIL)) return "off";
  if (!report.meko.ok) return "unreachable";
  return report.meko.target;
}

export const HERE_WORDS: Record<MekoHere, string> = {
  off: "Meko is switched off here (`KAKO_MEKO_OFF`), so new questions on this machine are kept in Kako only. Everything below describes Kako against Meko: local Meko in development, Meko Cloud for the demo.",
  local:
    "This Kako talks to local Meko on this machine, as development and tests do. The demo's datapack is on Meko Cloud.",
  cloud: "This Kako talks to Meko Cloud, where the demo's datapack lives.",
  unreachable:
    "Kako can't reach Meko from here right now (see [System check](/system)). Everything below describes Kako against Meko.",
};
