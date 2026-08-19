import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle in .next/standalone, which the
  // Dockerfile's runner stage copies on its own. Without this the production
  // image would have to carry the whole node_modules tree.
  output: "standalone",

  // A silently-broken build is worse than a red one: fail on type and lint
  // errors rather than shipping them to the demo URL judges will open.
  typescript: { ignoreBuildErrors: false },
  eslint: { ignoreDuringBuilds: false },
};

export default nextConfig;
