/**
 * Copy Pyodide runtime assets into `public/pyodide/`.
 *
 * Pyodide ships a ~14MB WASM runtime (CPython compiled to WebAssembly) plus the
 * Python standard library. We serve these assets from OUR OWN application
 * (no CDN, no external compiler service), so candidates on restricted networks
 * can still Run code locally.
 *
 * Hooked into `postinstall`, `predev`, and `prebuild` so the copy is always
 * fresh relative to the installed pyodide version.
 */
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = resolve(ROOT, 'node_modules/pyodide');
const DEFAULT_DEST = resolve(ROOT, 'public/pyodide');

const WHEEL_SRC = resolve(ROOT, 'scripts/pyodide-packages');

export function copyPyodideTo(dest = DEFAULT_DEST) {
  if (!existsSync(SRC)) {
    throw new Error(
      'pyodide package not found. Run `npm install` in apps/frontend first.'
    );
  }

  // NOTE: the destination directory is intentionally NEVER deleted wholesale.
  // A running Vite dev server keeps an index of public/ files that is kept in
  // sync by filesystem watch events; `rmSync(dest)` + re-create made that
  // index lose every /pyodide/ entry (missed re-add events), after which
  // Vite served index.html for `pyodide.mjs` and the runtime could not load.
  // Overwriting in place only produces `change` events, which never affect
  // index membership.
  mkdirSync(dest, { recursive: true });

  const expected = new Set(
    readdirSync(SRC).filter((name) => !name.endsWith('.map'))
  );

  // Copy everything the runtime needs at load time. Source maps are skipped to
  // keep the bundle lean. `pyodide.mjs`, `pyodide.asm.mjs`, `pyodide.asm.wasm`,
  // `python_stdlib.zip`, `python.wasm` and `pyodide-lock.json` are all fetched
  // relative to this directory by `loadPyodide({ indexURL: '/pyodide/' })`.
  cpSync(SRC, dest, {
    recursive: true,
    force: true,
    filter: (src) => !src.endsWith('.map'),
  });

  // Copy pre-downloaded wheel packages (pandas, numpy, etc.) so Pyodide's
  // loadPackage resolves them locally without CDN access.
  if (existsSync(WHEEL_SRC)) {
    cpSync(WHEEL_SRC, dest, { recursive: true, force: true });
    for (const name of readdirSync(WHEEL_SRC)) expected.add(name);
  }

  // Prune only individual stale files (removed in a newer pyodide version) —
  // again, never the directory itself.
  for (const name of readdirSync(dest)) {
    if (!expected.has(name)) {
      rmSync(join(dest, name), { recursive: true, force: true });
    }
  }

  return dest;
}

// CLI entry point: `node scripts/copy-pyodide.mjs`
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const dest = copyPyodideTo();
  console.log(`Copied pyodide runtime assets -> ${dest}`);
}