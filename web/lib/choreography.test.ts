import { describe, expect, it } from "vitest";

import type { Turn } from "./api";
import { planMatch, planTurn, type Plan } from "./choreography";

const FULL = { a: 100, b: 100 };

function turn(over: Partial<Turn> = {}): Turn {
  return {
    n: 1,
    attacker: "a",
    outcome: "block",
    target: null,
    damage: 0,
    damage_math: "no damage",
    problem: "p",
    stated_answer: "1",
    code: "print(1)",
    defender_answer: "1",
    score: 1,
    timed_out: false,
    retried: false,
    first_attempt: null,
    failure_reason: null,
    hp_a: 100,
    hp_b: 100,
    duration_ms: 1000,
    ...over,
  };
}

const hit = (over: Partial<Turn> = {}) =>
  turn({ outcome: "hit", target: "b", damage: 20, score: 0, hp_b: 80, ...over });
const backfire = (over: Partial<Turn> = {}) =>
  turn({ outcome: "backfire", target: "a", damage: 10, hp_a: 90, ...over });

const kinds = (plan: Plan) => plan.steps.map((s) => s.kind);

describe("planTurn", () => {
  it("a block has no hp step, since nothing changes", () => {
    expect(kinds(planTurn(turn(), FULL))).toEqual(["windup", "projectile", "think", "block"]);
  });

  it("a hit lands on the defender and then moves the hp bar", () => {
    const plan = planTurn(hit(), FULL);

    expect(kinds(plan)).toEqual(["windup", "projectile", "think", "hit", "hp"]);
    expect(plan.steps.find((s) => s.kind === "hit")).toMatchObject({ side: "b", damage: 20 });
  });

  it("a backfire returns the attack to the attacker, who takes the damage", () => {
    const plan = planTurn(backfire(), FULL);

    expect(kinds(plan)).toEqual(["windup", "rebound", "hit", "hp"]);
    expect(plan.steps.find((s) => s.kind === "hit")).toMatchObject({ side: "a", damage: 10 });
  });

  it("a defender that timed out freezes instead of thinking", () => {
    const plan = planTurn(hit({ timed_out: true }), FULL);

    expect(kinds(plan)).toEqual(["windup", "projectile", "timeout", "hit", "hp"]);
  });

  it("a retried attack starts with a retry flash on the attacker", () => {
    const plan = planTurn(turn({ retried: true, attacker: "b" }), FULL);

    expect(plan.steps[0]).toMatchObject({ kind: "retry", side: "b" });
    expect(kinds(plan).slice(1)).toEqual(["windup", "projectile", "think", "block"]);
  });

  it("the defender is the fighter who is not attacking", () => {
    const plan = planTurn(hit({ attacker: "b", target: "a", hp_a: 80, hp_b: 100 }), FULL);

    const sides = Object.fromEntries(plan.steps.map((s) => [s.kind, s.side]));
    expect(sides).toMatchObject({ windup: "b", projectile: "b", think: "a", hit: "a" });
  });

  it("steps run back to back and the plan ends when the last one does", () => {
    const plan = planTurn(hit({ retried: true }), FULL);

    let clock = 0;
    for (const step of plan.steps) {
      expect(step.at).toBeCloseTo(clock);
      clock += step.duration;
    }
    expect(plan.length).toBeCloseTo(clock);
  });

  it("every outcome plays for 3 to 6 seconds", () => {
    for (const make of [turn, hit, backfire]) {
      for (const retried of [false, true]) {
        for (const timed_out of [false, true]) {
          const { length } = planTurn(make({ retried, timed_out }), FULL);
          expect(length).toBeGreaterThanOrEqual(3);
          expect(length).toBeLessThanOrEqual(6);
        }
      }
    }
  });

  it("a knockout ends the plan with the loser falling", () => {
    const plan = planTurn(hit({ hp_b: 0 }), { a: 100, b: 20 });

    expect(plan.steps.at(-1)).toMatchObject({ kind: "ko", side: "b" });
    expect(plan.length).toBeLessThanOrEqual(6);
  });

  it("no knockout while the loser still has hp", () => {
    expect(kinds(planTurn(hit(), FULL))).not.toContain("ko");
  });

  it("carries the hp before and after the turn", () => {
    const plan = planTurn(hit(), FULL);

    expect(plan.hpBefore).toEqual({ a: 100, b: 100 });
    expect(plan.hpAfter).toEqual({ a: 100, b: 80 });
  });
});

describe("planMatch", () => {
  it("starts from full hp and carries each turn's result into the next", () => {
    const plans = planMatch([hit(), backfire({ n: 2, attacker: "b", target: "b", hp_a: 100, hp_b: 70, damage: 10 })], 100);

    expect(plans[0].hpBefore).toEqual({ a: 100, b: 100 });
    expect(plans[1].hpBefore).toEqual({ a: 100, b: 80 });
    expect(plans[1].hpAfter).toEqual({ a: 100, b: 70 });
  });
});
