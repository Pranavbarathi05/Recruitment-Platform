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
import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const SRC = resolve(ROOT, 'node_modules/pyodide');
const DEFAULT_DEST = resolve(ROOT, 'public/pyodide');

export function copyPyodideTo(dest = DEFAULT_DEST) {
  if (!existsSync(SRC)) {
    throw new Error(
      'pyodide package not found. Run `npm install` in apps/frontend first.'
    );
  }

  rmSync(dest, { recursive: true, force: true });
  mkdirSync(dest, { recursive: true });

  // Copy everything the runtime needs at load time. Source maps are skipped to
  // keep the bundle lean. `pyodide.mjs`, `pyodide.asm.mjs`, `pyodide.asm.wasm`,
  // `python_stdlib.zip`, `python.wasm` and `pyodide-lock.json` are all fetched
  // relative to this directory by `loadPyodide({ indexURL: '/pyodide/' })`.
  cpSync(SRC, dest, {
    recursive: true,
    filter: (src) => !src.endsWith('.map'),
  });

  return dest;
}

// CLI entry point: `node scripts/copy-pyodide.mjs`
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const dest = copyPyodideTo();
  console.log(`Copied pyodide runtime assets -> ${dest}`);
}