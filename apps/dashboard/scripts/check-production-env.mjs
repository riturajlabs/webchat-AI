#!/usr/bin/env node
/**
 * Build-time guard against placeholder / loopback hosts leaking into the
 * production bundle.
 *
 * Runs before `next build`. `NEXT_PUBLIC_*` values are inlined into the client
 * bundle, so a deployment with `https://cdn.webchatai.example/...`,
 * `http://localhost:8000` or `http://127.0.0.1:8080` would ship a broken or
 * misleading snippet to every page.
 *
 * Rules (fail hard on offenders):
 *   - `.example` placeholder domains are NEVER acceptable.
 *   - localhost / 127.0.0.1 / 0.0.0.0 / ::1 loopback hosts are rejected unless
 *     `WEBCHAT_ALLOW_LOCALHOST_BUILD=true` is set explicitly (local preview
 *     builds against a local backend).
 *   - URL-valued variables must be absolute http(s).
 *
 * Values are resolved with normal env precedence: real process env wins over
 * env files; among files, .env.local wins (matches Next.js behavior).
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = dirname(dirname(fileURLToPath(import.meta.url)));

const LOOPBACK = /localhost|127\.0\.0\.1|0\.0\.0\.0|::1/i;
const PLACEHOLDER = /\.example(?:[/:.?]|$)/i;
const IS_URL_VAR = /^NEXT_PUBLIC_(?:WIDGET_SCRIPT_URL|WIDGET_API_URL|DASHBOARD_URL|SITE_URL|API_URL)$/;

const allowLocalhost = process.env.WEBCHAT_ALLOW_LOCALHOST_BUILD === 'true';

function loadEnvFile(name) {
  try {
    return readFileSync(join(root, name), 'utf8')
      .split('\n')
      .filter((line) => line && !line.trim().startsWith('#') && line.includes('='));
  } catch {
    return [];
  }
}

function parseEnv(lines) {
  const values = new Map();
  for (const line of lines) {
    const sep = line.indexOf('=');
    if (sep === -1) continue;
    const key = line.slice(0, sep).trim();
    const value = line.slice(sep + 1).trim();
    if (key.startsWith('NEXT_PUBLIC_')) values.set(key, value);
  }
  return values;
}

// Real env vars take precedence over every env file.
const resolved = new Map();
for (const file of ['.env.local', '.env.production', '.env.development', '.env', '.env.example']) {
  for (const [key, value] of parseEnv(loadEnvFile(file))) {
    if (!resolved.has(key)) resolved.set(key, value);
  }
}
for (const [key, value] of Object.entries(process.env)) {
  if (key.startsWith('NEXT_PUBLIC_')) resolved.set(key, value);
}

const offenders = [];
for (const [key, value] of resolved) {
  const inline = !value || value.startsWith('"$') || value === '';
  const normalized = String(value);

  if (PLACEHOLDER.test(normalized)) {
    offenders.push(`${key}=${normalized}  (placeholder .example domain would be baked into the bundle)`);
  }

  if (LOOPBACK.test(normalized) && !allowLocalhost) {
    offenders.push(
      `${key}=${normalized}  (loopback host; set WEBCHAT_ALLOW_LOCALHOST_BUILD=true only for local preview builds)`,
    );
  }

  if (IS_URL_VAR.test(key) && !/^https?:\/\//i.test(normalized)) {
    offenders.push(`${key}=${normalized}  (must be an absolute http(s) URL)`);
  }
  void inline;
}

if (offenders.length > 0) {
  console.error(
    '\n[check-production-env] Rejecting build: NEXT_PUBLIC_* values would leak unsafe hosts into the bundle.\n',
  );
  for (const offender of offenders) console.error(`  - ${offender}`);
  console.error(
    '\nFix the values, or for a local preview build only set WEBCHAT_ALLOW_LOCALHOST_BUILD=true.\n',
  );
  process.exit(1);
}

console.log('[check-production-env] NEXT_PUBLIC_* hosts look production-safe.');