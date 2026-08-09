import { copyFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';

/**
 * Copy MapLibre's worker bundle into `public/` so it is served from a stable URL
 * with a correct `application/javascript` MIME type.
 *
 * Why this exists
 * ---------------
 * MapLibre GL spawns a Web Worker to parse and tile geometry off the main
 * thread. Under Turbopack the worker's module URL does not resolve, the server
 * answers with its HTML 404 page, and the worker's module load fails with
 * "Failed to load module script: ... non-JavaScript MIME type of text/html".
 *
 * MapLibre swallows that failure and silently falls back to parsing on the main
 * thread. The map still renders, so nothing looks broken — but at the ~7,000
 * tiles a 10 mi² AOI produces at 60 m granularity, single-threaded parsing is
 * precisely the frontend performance risk SRS §21.2 identifies. A silent
 * fallback is worse than a loud failure.
 *
 * Resolving from `node_modules` instead of hardcoding a path keeps this correct
 * across dependency upgrades.
 */

const require = createRequire(import.meta.url);

const WORKER_ENTRY = 'maplibre-gl/dist/maplibre-gl-worker.mjs';
const PUBLIC_DIR = new URL('../public/', import.meta.url);
const DEST_NAME = 'maplibre-gl-worker.mjs';

async function main() {
  const source = require.resolve(WORKER_ENTRY);
  await mkdir(PUBLIC_DIR, { recursive: true });
  await copyFile(source, new URL(DEST_NAME, PUBLIC_DIR));
  console.log(`[maplibre] worker copied -> public/${DEST_NAME}`);
}

main().catch((error) => {
  console.error('[maplibre] failed to copy worker bundle');
  console.error(error);
  process.exitCode = 1;
});
