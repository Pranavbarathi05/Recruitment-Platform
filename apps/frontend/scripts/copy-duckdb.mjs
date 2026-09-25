/**
 * Copy DuckDB-WASM runtime assets into `public/duckdb/`.
 *
 * DuckDB-WASM ships ~4MB of WASM + worker scripts. We serve these from OUR
 * OWN application (no CDN), so candidates on restricted networks can still
 * use the SQL-WASM runner.
 *
 * Hooked into postinstall, predev, and prebuild so the copy is always fresh
 * relative to the installed @duckdb/duckdb-wasm version.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = resolve(ROOT, 'node_modules/@duckdb/duckdb-wasm/dist');
const DEFAULT_DEST = resolve(ROOT, 'public/duckdb');

// Files needed at runtime by the browser bundle
const ASSET_PATTERNS = [
  'duckdb-mvp.wasm',
  'duckdb-eh.wasm',
  'duckdb-browser-mvp.worker.js',
  'duckdb-browser-eh.worker.js',
  'duckdb-browser-coi.pthread.worker.js',
  'duckdb-browser-coi.worker.js',
];

export function copyDuckdbTo(dest = DEFAULT_DEST) {
  if (!existsSync(SRC)) {
    throw new Error(
      '@duckdb/duckdb-wasm package not found. Run `npm install` in apps/frontend first.',
    );
  }

  // NOTE: the destination directory is intentionally NEVER deleted wholesale.
  // A running Vite dev server keeps an index of public/ files that is kept in
  // sync by filesystem watch events; wiping + re-creating the directory made
  // that index lose entries, after which Vite served index.html for the
  // DuckDB worker/wasm files and the SQL runner hung at "Preparing SQL
  // environment...". Overwriting in place only produces `change` events,
  // which never affect index membership.
  mkdirSync(dest, { recursive: true });

  const expected = new Set();

  // Copy only the files we actually need at runtime
  for (const name of ASSET_PATTERNS) {
    const srcPath = resolve(SRC, name);
    if (existsSync(srcPath)) {
      cpSync(srcPath, resolve(dest, name), { force: true });
      expected.add(name);
    }
  }

  // Prune individual stale files only — never the directory itself.
  for (const name of readdirSync(dest)) {
    if (!expected.has(name)) {
      rmSync(resolve(dest, name), { recursive: true, force: true });
    }
  }

  return dest;
}

// CLI entry point
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const dest = copyDuckdbTo();
  console.log(`Copied duckdb-wasm runtime assets -> ${dest}`);
}
