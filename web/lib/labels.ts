import type { Side } from "./api";

export type MatchMode = "sim" | "sparring" | "ranked";
export type MatchState = "queued" | "running" | "finished" | "failed";

const MODES: Record<MatchMode, string> = {
  sim: "Simulation",
  sparring: "Sparring",
  ranked: "Ranked",
};

const STATES: Record<MatchState, string> = {
  queued: "Waiting",
  running: "Playing",
  finished: "Finished",
  failed: "Failed",
};

export const modeLabel = (mode: MatchMode): string => MODES[mode];
export const statusLabel = (status: MatchState): string => STATES[status];

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;

/**
 * "5 minutes ago" for the last week, then a calendar date. The date is in UTC so the server and the
 * browser print the same text. Empty when there is no date.
 */
export function formatDate(iso: string | null, now: Date = new Date()): string {
  if (iso === null) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const age = Math.max(0, now.getTime() - then.getTime());
  if (age < MINUTE) return "just now";
  if (age < HOUR) return plural(Math.floor(age / MINUTE), "minute");
  if (age < DAY) return plural(Math.floor(age / HOUR), "hour");
  if (age < 2 * DAY) return "yesterday";
  if (age < 7 * DAY) return plural(Math.floor(age / DAY), "day");
  return then.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

/** Win, loss or draw for the side you were; null while the match is still going. */
export function resultFor(you: Side, winner: Side | null, finished: boolean): "W" | "L" | "D" | null {
  if (!finished) return null;
  if (winner === null) return "D";
  return winner === you ? "W" : "L";
}
