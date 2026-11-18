import { describe, expect, it } from "vitest";

import { formatDate, modeLabel, resultFor, statusLabel } from "./labels";

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
