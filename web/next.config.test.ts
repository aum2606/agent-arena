import { describe, expect, it } from "vitest";

import config from "./next.config";

describe("next.config", () => {
  it("does not announce the framework", () => {
    expect(config.poweredByHeader).toBe(false);
  });

  it("sends the security headers on every page", async () => {
    const rules = await config.headers!();
    const names = rules.flatMap((rule) => rule.headers.map((h) => h.key));

    expect(rules[0].source).toBe("/:path*");
    for (const name of [
      "X-Content-Type-Options",
      "X-Frame-Options",
      "Referrer-Policy",
      "Permissions-Policy",
      "Cross-Origin-Opener-Policy",
      "Cross-Origin-Resource-Policy",
    ]) {
      expect(names).toContain(name);
    }
  });
});
