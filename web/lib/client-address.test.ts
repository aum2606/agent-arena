import { describe, expect, it } from "vitest";

import { forwardedAddress } from "./client-address";

describe("forwardedAddress", () => {
  it("passes on the header the deployer named, with the visitor's address", () => {
    const incoming = new Headers({ "x-real-ip": "203.0.113.5", cookie: "session=1" });

    expect(forwardedAddress("x-real-ip", incoming)).toEqual({ "x-real-ip": "203.0.113.5" });
  });

  it("passes on nothing when no header is named, so a made-up one is never relayed", () => {
    const incoming = new Headers({ "x-real-ip": "203.0.113.5" });

    expect(forwardedAddress(undefined, incoming)).toEqual({});
    expect(forwardedAddress("", incoming)).toEqual({});
  });

  it("passes on nothing when the visitor request carries no such header", () => {
    expect(forwardedAddress("x-real-ip", new Headers())).toEqual({});
  });
});
