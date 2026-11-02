import type { Side, Turn } from "./api";

export type StepKind =
  | "retry" // the attacker's first attempt failed its check and is being redone
  | "windup" // the attacker winds up
  | "projectile" // the problem travels to the defender
  | "rebound" // a backfire: the problem comes back at the attacker
  | "think" // the defender works on the problem
  | "timeout" // the defender ran out of time or tokens
  | "block"
  | "hit"
  | "hp" // the health bars move to their new values
  | "ko";

/** `side` is the fighter the step happens to: who winds up, thinks, blocks, takes the hit. */
export interface Step {
  kind: StepKind;
  side: Side;
  at: number; // seconds from the start of the turn
  duration: number;
  damage?: number;
}

export interface Hp {
  a: number;
  b: number;
}

export interface Plan {
  steps: Step[];
  length: number; // seconds
  hpBefore: Hp;
  hpAfter: Hp;
}

// Fixed phase lengths: replays play a turn in 3 to 6 seconds however long the agents really took.
const SECONDS: Record<StepKind, number> = {
  retry: 0.5,
  windup: 0.6,
  projectile: 0.6,
  rebound: 0.9,
  think: 1.0,
  timeout: 1.0,
  block: 0.8,
  hit: 0.9,
  hp: 0.6,
  ko: 0.8,
};

const other = (side: Side): Side => (side === "a" ? "b" : "a");

/** What happens, in order, during one turn. Pure, so it can be tested without a canvas. */
export function planTurn(turn: Turn, hpBefore: Hp): Plan {
  const attacker = turn.attacker;
  const defender = other(attacker);
  const hpAfter: Hp = { a: turn.hp_a, b: turn.hp_b };
  const wanted: [StepKind, Side, number?][] = [];

  if (turn.retried) wanted.push(["retry", attacker]);
  wanted.push(["windup", attacker]);

  if (turn.outcome === "backfire") {
    wanted.push(["rebound", attacker], ["hit", attacker, turn.damage]);
  } else {
    wanted.push(["projectile", attacker], [turn.timed_out ? "timeout" : "think", defender]);
    wanted.push(turn.outcome === "hit" ? ["hit", defender, turn.damage] : ["block", defender]);
  }
  if (hpAfter.a !== hpBefore.a || hpAfter.b !== hpBefore.b) wanted.push(["hp", defender]);

  const loser = hpAfter.a <= 0 ? "a" : hpAfter.b <= 0 ? "b" : null;
  if (loser) wanted.push(["ko", loser]);

  let clock = 0;
  const steps = wanted.map(([kind, side, damage]): Step => {
    const step: Step = { kind, side, at: clock, duration: SECONDS[kind] };
    if (damage !== undefined) step.damage = damage;
    clock += step.duration;
    return step;
  });
  return { steps, length: clock, hpBefore, hpAfter };
}

/** One plan per turn, each starting from the previous turn's health. */
export function planMatch(turns: Turn[], maxHp: number): Plan[] {
  let hp: Hp = { a: maxHp, b: maxHp };
  return turns.map((turn) => {
    const plan = planTurn(turn, hp);
    hp = plan.hpAfter;
    return plan;
  });
}
