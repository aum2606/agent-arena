import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",
  // The browser only ever talks to this origin, so the API's session cookie is a same-site cookie.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
  // No Content-Security-Policy yet: Next injects inline scripts, and a policy needs nonces (D-050).
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
