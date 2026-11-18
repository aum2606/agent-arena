import { describe, expect, it } from "vitest";

import { contentSecurityPolicy } from "./csp";

const directives = (policy: string): Map<string, string> =>
  new Map(
    policy
      .split(";")
      .map((d) => d.trim())
      .filter(Boolean)
      .map((d) => [d.split(" ")[0], d.split(" ").slice(1).join(" ")]),
  );

describe("contentSecurityPolicy", () => {
  it("lets only this request's nonce run scripts and styles", () => {
    const policy = directives(contentSecurityPolicy("abc123", false));

    expect(policy.get("script-src")).toBe("'self' 'nonce-abc123' 'strict-dynamic'");
    expect(policy.get("style-src")).toBe("'self' 'nonce-abc123'");
  });

  it("allows no eval and no inline code in production", () => {
    const policy = contentSecurityPolicy("abc123", false);

    expect(policy).not.toContain("unsafe-eval");
    expect(policy).not.toContain("unsafe-inline");
  });

  it("allows eval in development only, where React needs it for debugging", () => {
    expect(contentSecurityPolicy("abc123", true)).toContain("'unsafe-eval'");
  });

  it("lets the development overlay style itself, which carries no nonce, and nothing else changes", () => {
    const dev = directives(contentSecurityPolicy("abc123", true));

    // A nonce would make browsers ignore 'unsafe-inline', so the dev policy has none for styles.
    expect(dev.get("style-src")).toBe("'self' 'unsafe-inline'");
    expect(dev.get("script-src")).toContain("'nonce-abc123'");
  });

  it("keeps everything else on this origin and out of frames and plugins", () => {
    const policy = directives(contentSecurityPolicy("abc123", false));

    expect(policy.get("default-src")).toBe("'self'");
    expect(policy.get("object-src")).toBe("'none'");
    expect(policy.get("base-uri")).toBe("'self'");
    expect(policy.get("form-action")).toBe("'self'");
    expect(policy.get("frame-ancestors")).toBe("'none'");
    expect(policy.get("img-src")).toBe("'self' blob: data:");
  });

  it("is one line, so it fits in a header", () => {
    expect(contentSecurityPolicy("abc123", false)).not.toContain("\n");
  });
});
