import type { NextConfig } from "next";

// Where the FastAPI backend listens. The web app never talks to the database or Meko itself:
// every /api/v1 request is passed through to the backend (docs/architecture.md, Components).
const apiUrl = (process.env.KAKO_API_URL ?? "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` },
    ];
  },
};

export default nextConfig;
