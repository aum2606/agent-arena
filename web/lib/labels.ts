import type { Outcome, Side, Turn } from "./api";

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

export interface NextStep {
  id: "spar" | "join" | "play" | "keep";
  title: string;
  text: string;
}

/** What a fighter's owner should do next, in the order the site needs: spar, join the pool, play ranked. */
export function nextStep(fighter: { verified: boolean; ranked_opt_in: boolean; games: number }): NextStep {
  if (!fighter.verified) {
    return {
      id: "spar",
      title: "Next: spar once",
      text: "Spar against the house bot to check that your key and model work. It is unranked and takes a few minutes.",
    };
  }
  if (!fighter.ranked_opt_in) {
    return {
      id: "join",
      title: "Next: join the ranked pool",
      text: "Tick the box under Ranked so other players' matches can use this fighter. They spend its key, up to its daily limit. Then you can play ranked too.",
    };
  }
  if (fighter.games === 0) {
    return {
      id: "play",
      title: "Next: play your first ranked match",
      text: "You get paired with the closest-rated fighter of another player and start at a rating of 1200.",
    };
  }
  return {
    id: "keep",
    title: "Next: climb the leaderboard",
    text: "Play more ranked matches to move up. Edit the persona to try a different style: each save is a new version.",
  };
}

/** Wins as a whole percentage of games, or a dash before the first game. */
export function winRate(wins: number, games: number): string {
  return games === 0 ? "–" : `${Math.round((100 * wins) / games)}%`;
}

export function recordText(f: { wins: number; draws: number; losses: number; games: number }): string {
  return f.games === 0 ? "No ranked games yet" : `${f.wins} won · ${f.draws} drawn · ${f.losses} lost`;
}

const OUTCOMES: Record<Outcome, string> = { hit: "Hit", block: "Blocked", backfire: "Backfired" };

export const outcomeLabel = (outcome: Outcome): string => OUTCOMES[outcome];

const damageText = (damage: number): string => (Number.isInteger(damage) ? `${damage}` : damage.toFixed(1));

/** One sentence saying how a turn went, for someone who has not read the rules. */
export function whatHappened(
  turn: Pick<Turn, "attacker" | "outcome" | "damage" | "timed_out" | "review_overturned">,
  names: Record<Side, string>,
): string {
  const defender = names[turn.attacker === "a" ? "b" : "a"];
  const attacker = names[turn.attacker];
  const cost = `${damageText(turn.damage)} damage`;
  if (turn.outcome === "backfire") {
    return `${attacker}'s own check failed, so the attack backfired: ${attacker} took ${cost}.`;
  }
  if (turn.outcome === "block") {
    return turn.review_overturned
      ? `A reference panel judged ${defender}'s answer correct, so a hit was overturned: no damage.`
      : `${defender} answered correctly, so the attack was blocked.`;
  }
  return turn.timed_out
    ? `${defender} did not answer in time and took ${cost}.`
    : `${defender} gave a wrong answer and took ${cost}.`;
}
