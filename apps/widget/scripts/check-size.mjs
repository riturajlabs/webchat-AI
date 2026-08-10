/**
 * Bundle size gate (plan §5, ADR-008).
 *
 * Hard-fails when the gzipped IIFE exceeds 100 KB, warns above 90 KB.
 * Run after `pnpm build`:
 *
 *     node scripts/check-size.mjs
 */
import { gzipSync } from 'node:zlib';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HARD_LIMIT_BYTES = 100 * 1024;
const WARN_LIMIT_BYTES = 90 * 1024;

const root = resolve(fileURLToPath(import.meta.url), '..', '..');
const file = resolve(root, 'dist', 'webchat-widget.iife.min.js');

const source = readFileSync(file);
const gzipped = gzipSync(source, { level: 9 });
const size = gzipped.length;

console.log(`webchat-widget.iife.min.js gzip: ${(size / 1024).toFixed(2)} kB`);

if (size > HARD_LIMIT_BYTES) {
  console.error(
    `FAIL: gzipped bundle ${(size / 1024).toFixed(2)} kB exceeds hard limit ${HARD_LIMIT_BYTES / 1024} kB`,
  );
  process.exit(1);
}

if (size > WARN_LIMIT_BYTES) {
  console.warn(
    `WARN: gzipped bundle ${(size / 1024).toFixed(2)} kB is above the ${WARN_LIMIT_BYTES / 1024} kB warning threshold`,
  );
}
