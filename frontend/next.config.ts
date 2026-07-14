import type { NextConfig } from "next";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Same-origin /api/* in the browser; Next proxies to FastAPI. Avoids CORS
  // headaches entirely in dev and lets one reverse proxy serve prod.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
  // standalone is for the Docker image only; Vercel uses its native builder.
  output: process.env.DOCKER_BUILD ? "standalone" : undefined,
  // konva's node entry `require`s the optional native 'canvas' package.
  // Next bundles the server graph even for ssr:false dynamic imports, so the
  // build fails with "Can't resolve 'canvas'" unless it's marked external
  // (docs/ERRORS-AND-FIXES.md #17). We never render Konva on the server.
  webpack: (config) => {
    config.externals = [...(config.externals ?? []), { canvas: "commonjs canvas" }];
    return config;
  },
};

export default nextConfig;
