/**
 * Bundled-asset self-containment gate (production hardening audit).
 *
 * The widget must ship fully self-contained and embeddable from any origin:
 *  - no `localhost` / `127.0.0.1` / loopback host baked into the bundle
 *    (a fixed localhost API/script URL would break every real embed), and
 *  - no external asset references in the injected CSS (`url(`, `@import`,
 *    `@font-face`), which would leak through the shadow boundary as network
 *    fetches and fail under a strict embedding-page CSP.
 *
 * The stable-name copy is checked (content-identical to the hashed bundle);
 * the hashed bundle must also exist so a CDN can serve it immutable.
 *
 * Run after `pnpm build`:
 *
 *     node scripts/check-assets.mjs
 */
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(import.meta.url), '..', '..');
const dist = resolve(root, 'dist');
const file = resolve(dist, 'webchat-widget.iife.min.js');

const source = readFileSync(file, 'utf8');
const failures = [];

const loopback = /localhost|127\.0\.0\.1|0\.0\.0\.0|(^|[^0-9])::1([^0-9]|$)/i;
if (loopback.test(source)) {
  failures.push('bundle references a loopback host (localhost/127.0.0.1)');
}
if (/url\s*\(/.test(source)) {
  failures.push('bundle CSS references external assets via url()');
}
if (/@import|@font-face/.test(source)) {
  failures.push('bundle CSS uses @import/@font-face (external fetch)');
}

const hashedIife = readdirSync(dist).find(
  (name) => /^webchat-widget\.iife\.min\.[A-Za-z0-9_-]{8,}\.js$/.test(name),
);
if (!hashedIife) {
  failures.push('no content-hashed IIFE bundle found (webchat-widget.iife.min.<hash>.js)');
}

for (const failure of failures) {
  console.error(`FAIL: ${file} — ${failure}`);
}

if (failures.length > 0) {
  process.exit(1);
}

if (hashedIife) {
  console.log(
    `webchat-widget.iife.min.js: self-contained (no loopback hosts, no external asset refs)`,
  );
  console.log(
    `Production WIDGET_SCRIPT_URL should point at the hashed bundle: ${hashedIife}`,
  );
}
