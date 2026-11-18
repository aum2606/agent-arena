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
  /** Other players' ranked matches may spend this fighter's key. */
  ranked_opt_in: boolean;
  /** Null until the fighter's first ranked game. */
  rating: number | null;
  games: number;
  wins: number;
  draws: number;
  losses: number;
}

export interface ProviderOption {
  name: string;
  /** Model ids this server's config already uses with the provider: suggestions only. */
  models: string[];
  /** Where to get a key for the provider, when the server says. */
  key_url: string | null;
}

export interface Options {
  providers: ProviderOption[];
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

/** One ranked match from a fighter's own side, as `GET /fighters/{id}/ranked` returns it. */
export interface RankedEntry {
  id: string;
  status: MatchStatus["status"];
  opponent: string | null;
  result: "W" | "D" | "L" | null;
  /** This fighter's rating change, once finished. */
  rating_delta: number | null;
  error: string | null;
}

/** One of the signed-in user's own spars or ranked matches, as `GET /matches/mine` returns it. */
export interface MyMatch {
  id: string;
  mode: "sparring" | "ranked";
  status: MatchStatus["status"];
  /** "a" when you asked for the match, "b" when your fighter was the ranked opponent. */
  you: "a" | "b";
  name_a: string | null;
  name_b: string | null;
  /** The rest is null until the match has finished. */
  winner: "a" | "b" | null;
  hp_a: number | null;
  hp_b: number | null;
  turn_count: number | null;
  ended_at: string | null;
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
