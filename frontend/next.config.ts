import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle in .next/standalone, which the
  // Dockerfile's runner stage copies on its own. Without this the production
  // image would have to carry the whole node_modules tree.
  output: "standalone",

  // A silently-broken build is worse than a red one: fail on type errors rather
  // than shipping them to the demo URL judges will open.
  typescript: { ignoreBuildErrors: false },

  // `eslint` was removed from NextConfig in Next 16, and leaving it here was not
  // a warning — it failed the type check of this very file, so `next build`
  // could not complete at all. The app had only ever been run by `next dev`,
  // which does not type-check the config, so nothing surfaced it until the
  // production image was built for the first time.
  //
  // Linting now runs in CI and in `npm run lint`, which is where it belongs:
  // a build is for producing an artefact, and coupling it to lint means a style
  // rule can block a deploy.
};

export default nextConfig;
