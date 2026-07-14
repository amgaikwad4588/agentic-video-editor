import type { NextConfig } from "next";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Same-origin /api/* in the browser; Next proxies to FastAPI. Avoids CORS
  // headaches entirely in dev and lets one reverse proxy serve prod.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
  output: "standalone",
};

export default nextConfig;
