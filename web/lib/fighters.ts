export interface FighterView {
  id: number;
  name: string;
  version: number;
  provider: string;
  model: string;
  persona: string;
  key_hint: string;
  verified: boolean;
  daily_match_cap: number;
}

export interface Options {
  providers: string[];
  templates: { name: string; persona: string }[];
}

export interface MatchStatus {
  id: string;
  status: "queued" | "running" | "finished" | "failed";
  fighter_a: string | null;
  fighter_b: string | null;
  error: string | null;
  fighter_version: number | null;
  /** Ranked, once finished: how the requester's rating moved. */
  rating_delta: number | null;
}

export interface LeaderboardRow {
  handle: string;
  name: string;
  rating: number;
  games: number;
  wins: number;
  draws: number;
  losses: number;
  /** The last five results, newest first: W, D or L. */
  form: string;
}

/** The message from an API error body (a string, or a list of validation problems). */
export function errorText(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return `${detail[0].loc?.at(-1) ?? "input"}: ${detail[0].msg}`;
  return fallback;
}
