import type { NextConfig } from "next";

// The dashboard talks to the API on the same origin: /api/v1/* is proxied to the FastAPI backend
// (in staging the TLS proxy sends /api/* straight to the API), so the HttpOnly session cookie and
// the CSRF cookie work without cross-origin requests.
// The Content-Security-Policy is set per request with a nonce in src/proxy.ts.
const apiOrigin = process.env.MIXT_API_ORIGIN ?? "http://localhost:8000";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
        ],
      },
    ];
  },
};

export default config;
