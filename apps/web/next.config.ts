import type { NextConfig } from "next";

const API = process.env.SUPPLYLENS_API_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  reactStrictMode: true,
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
