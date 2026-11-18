import { describe, expect, it } from "vitest";

import { formatDate, modeLabel, nextStep, recordText, resultFor, statusLabel, winRate } from "./labels";

const now = new Date("2026-11-18T12:00:00Z");
const ago = (ms: number) => new Date(now.getTime() - ms).toISOString();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

describe("modeLabel", () => {
  it("names each kind of match in words", () => {
    expect(modeLabel("sim")).toBe("Simulation");
    expect(modeLabel("sparring")).toBe("Sparring");
    expect(modeLabel("ranked")).toBe("Ranked");
  });
});

describe("statusLabel", () => {
  it("says where a match is in plain words", () => {
    expect(statusLabel("queued")).toBe("Waiting");
    expect(statusLabel("running")).toBe("Playing");
    expect(statusLabel("finished")).toBe("Finished");
    expect(statusLabel("failed")).toBe("Failed");
  });
});

describe("formatDate", () => {
  it("is empty when there is no date, or it is not one", () => {
    expect(formatDate(null, now)).toBe("");
    expect(formatDate("not a date", now)).toBe("");
  });

  it("is relative for the last week", () => {
    expect(formatDate(ago(20_000), now)).toBe("just now");
    expect(formatDate(ago(MINUTE), now)).toBe("1 minute ago");
    expect(formatDate(ago(5 * MINUTE), now)).toBe("5 minutes ago");
    expect(formatDate(ago(HOUR), now)).toBe("1 hour ago");
    expect(formatDate(ago(3 * HOUR), now)).toBe("3 hours ago");
    expect(formatDate(ago(DAY), now)).toBe("yesterday");
    expect(formatDate(ago(3 * DAY), now)).toBe("3 days ago");
  });

  it("is a calendar date after that, the same on the server and in the browser", () => {
    expect(formatDate("2026-11-08T23:30:00Z", now)).toBe("8 Nov 2026");
  });

  it("does not claim a time in the future", () => {
    expect(formatDate(ago(-5 * MINUTE), now)).toBe("just now");
  });
});

describe("resultFor", () => {
  it("is a win, loss or draw from the point of view of the side you were", () => {
    expect(resultFor("a", "a", true)).toBe("W");
    expect(resultFor("a", "b", true)).toBe("L");
    expect(resultFor("b", "b", true)).toBe("W");
    expect(resultFor("b", "a", true)).toBe("L");
    expect(resultFor("a", null, true)).toBe("D");
  });

  it("is nothing until the match has finished", () => {
    expect(resultFor("a", null, false)).toBeNull();
  });
});

const fighter = { verified: false, ranked_opt_in: false, games: 0 };

describe("nextStep", () => {
  it("starts with a spar, which is what proves the key and model work", () => {
    expect(nextStep(fighter).id).toBe("spar");
    expect(nextStep({ ...fighter, ranked_opt_in: true }).id).toBe("spar");
  });

  it("asks a verified fighter to join the ranked pool before it can play", () => {
    expect(nextStep({ ...fighter, verified: true }).id).toBe("join");
  });

  it("suggests the first ranked match, then more of them", () => {
    const ready = { ...fighter, verified: true, ranked_opt_in: true };
    expect(nextStep(ready).id).toBe("play");
    expect(nextStep({ ...ready, games: 3 }).id).toBe("keep");
  });

  it("always says what to do in words", () => {
    for (const f of [fighter, { ...fighter, verified: true }, { ...fighter, verified: true, ranked_opt_in: true }]) {
      expect(nextStep(f).title).toMatch(/^Next:/);
      expect(nextStep(f).text.length).toBeGreaterThan(20);
    }
  });
});

describe("winRate", () => {
  it("is a whole percentage of ranked games, or a dash before the first", () => {
    expect(winRate(0, 0)).toBe("–");
    expect(winRate(1, 3)).toBe("33%");
    expect(winRate(2, 3)).toBe("67%");
    expect(winRate(4, 4)).toBe("100%");
  });
});

describe("recordText", () => {
  it("reads as wins, draws and losses", () => {
    expect(recordText({ wins: 3, draws: 1, losses: 2, games: 6 })).toBe("3 won · 1 drawn · 2 lost");
  });

  it("says so when there are no ranked games", () => {
    expect(recordText({ wins: 0, draws: 0, losses: 0, games: 0 })).toBe("No ranked games yet");
  });
});
