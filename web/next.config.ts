import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  // Next 16 blocks the dev server's websocket from any origin it does not list, so a page opened at
  // 127.0.0.1 (the address the docs use) never became interactive under `npm run dev`.
  allowedDevOrigins: ["127.0.0.1"],
  // The browser only ever talks to this origin, so the API's session cookie is a same-site cookie.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  // The Content-Security-Policy needs a nonce per request, so proxy.ts sets it (D-064).
  // HTTPS and Strict-Transport-Security belong to the reverse proxy in front of this server.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
