import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // `public/` is served byte-for-byte and holds vendored bundles we do not
    // author -- `maplibre-gl-worker.mjs` alone accounted for 42 of 48 findings,
    // all of them about minified code no one here will edit. Linting it buried
    // the seven real errors in source under warnings nobody could act on.
    "public/**",
  ]),
]);

export default eslintConfig;
