import type { NextConfig } from "next";

const API = process.env.SUPPLYLENS_API_URL ?? "http://127.0.0.1:8000";

// Content-Security-Policy. Next.js inlines its hydration scripts, so script-src needs 'unsafe-inline' unless a
// per-request nonce is introduced (middleware + dynamic rendering). Everything else is locked to this origin; the
// browser never talks to the API host directly (same-origin proxy below), so connect-src stays 'self'.
const dev = process.env.NODE_ENV !== "production";
const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${dev ? " ws:" : ""}`,
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const config: NextConfig = {
  reactStrictMode: true,
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "Content-Security-Policy", value: CSP },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
    ] }];
  },
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  // Same-origin proxy: the browser never talks to the API host directly, so the session
  // cookie stays HttpOnly/SameSite and CORS can remain closed.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API}/api/:path*` },
      { source: "/health", destination: `${API}/health` },
    ];
  },
};

export default config;
