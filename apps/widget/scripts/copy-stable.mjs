/**
 * Emit stable-name copies of the content-hashed widget bundles.
 *
 * The production build emits `webchat-widget.iife.min.<hash>.js` (and siblings)
 * so the CDN can serve them immutable; a fixed `WIDGET_SCRIPT_URL` can point at
 * the current hashed file per release. Dev, the E2E stack, `check-assets.mjs` /
 * `check-size.mjs` and the package.json entry points (main/module/exports) all
 * reference the stable names, so this script keeps `dist/webchat-widget.js`,
 * `dist/webchat-widget.umd.cjs` and `dist/webchat-widget.iife.min.js` (plus
 * their sourcemaps) in sync with the latest build.
 *
 * Run after `pnpm build`:
 *
 *     node scripts/copy-stable.mjs
 */
import { copyFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = resolve(fileURLToPath(import.meta.url), '..', '..', 'dist');

/** Stable name -> hashed filename pattern for the same artifact. */
const STABLE_MAP = [
  { stable: 'webchat-widget.js', hashed: /^webchat-widget\.[A-Za-z0-9_-]{8,}\.js$/ },
  { stable: 'webchat-widget.umd.cjs', hashed: /^webchat-widget\.umd\.[A-Za-z0-9_-]{8,}\.cjs$/ },
  {
    stable: 'webchat-widget.iife.min.js',
    hashed: /^webchat-widget\.iife\.min\.[A-Za-z0-9_-]{8,}\.js$/,
  },
];

const files = readdirSync(dist);

for (const { stable, hashed } of STABLE_MAP) {
  const hashedFile = files.find((file) => hashed.test(file));
  if (!hashedFile) {
    throw new Error(`copy-stable: no hashed bundle found for ${stable} in ${dist}`);
  }
  copyFileSync(resolve(dist, hashedFile), resolve(dist, stable));
  // Keep the corresponding sourcemap in sync when present.
  const hashedMap = files.find(
    (file) => file.endsWith('.map') && hashed.test(file.replace(/\.map$/, '')),
  );
  if (hashedMap) {
    copyFileSync(resolve(dist, hashedMap), resolve(dist, `${stable}.map`));
  }
  console.log(`copy-stable: ${hashedFile} -> ${stable}`);
}
