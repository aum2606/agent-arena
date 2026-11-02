export type Side = "a" | "b";
export type Outcome = "hit" | "block" | "backfire";

export interface Attempt {
  problem: string;
  answer: string;
  code: string;
  reason: string;
}

export interface FighterInfo {
  name: string;
  provider: string;
  model: string;
  persona: string;
}

export interface Turn {
  n: number;
  attacker: Side;
  outcome: Outcome;
  target: Side | null;
  damage: number;
  damage_math: string;
  problem: string | null;
  stated_answer: string | null;
  code: string | null;
  defender_answer: string | null;
  score: number | null;
  timed_out: boolean;
  retried: boolean;
  first_attempt: Attempt | null;
  failure_reason: string | null;
  hp_a: number;
  hp_b: number;
  duration_ms: number;
}

export interface ReplaySummary {
  id: string;
  winner: Side | null;
  reason: string | null;
  hp_a: number;
  hp_b: number;
  turn_count: number;
  name_a: string | null;
  name_b: string | null;
}

export interface Replay {
  summary: ReplaySummary;
  turns: Turn[];
  fighter_a: FighterInfo | null;
  fighter_b: FighterInfo | null;
}

const API_URL = process.env.API_URL ?? "http://localhost:8000";

/** The parsed JSON, or null when the API answers 404. Anything else is an error. */
export async function getJson<T>(path: string): Promise<T | null> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API ${path} returned ${response.status}`);
  return response.json();
}

/** The fighter's name, or "Fighter A"/"Fighter B" for older logs that have none. */
export function sideLabel(summary: ReplaySummary, side: Side): string {
  return (side === "a" ? summary.name_a : summary.name_b) ?? `Fighter ${side.toUpperCase()}`;
}

export function resultText(summary: ReplaySummary): string {
  if (summary.winner === null) return summary.reason ? `Draw by ${summary.reason}` : "Unfinished";
  return `${sideLabel(summary, summary.winner)} wins by ${summary.reason}`;
}
