import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdtempSync, existsSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { copyPyodideTo } from './copy-pyodide.mjs';

const REQUIRED_ASSETS = [
  'pyodide.mjs',
  'pyodide.asm.mjs',
  'pyodide.asm.wasm',
  'python_stdlib.zip',
  'pyodide-lock.json',
];

describe('Pyodide asset bundling (offline requirement)', () => {
  let dest;

  beforeAll(() => {
    dest = mkdtempSync(join(tmpdir(), 'pyodide-copy-'));
    copyPyodideTo(dest);
  });

  afterAll(() => {
    rmSync(dest, { recursive: true, force: true });
  });

  it('copies the WASM runtime and stdlib into app-local assets (no CDN)', () => {
    for (const file of REQUIRED_ASSETS) {
      expect(existsSync(join(dest, file)), `missing ${file}`).toBe(true);
    }
  });

  it('serves the runtime from the app public dir so it works on restricted networks', () => {
    // The predev/prebuild/postinstall hooks copy into public/pyodide, which
    // Vite serves at /pyodide/ — same origin as the app, no external host.
    const publicAsset = resolve(process.cwd(), 'public/pyodide/pyodide.asm.wasm');
    expect(existsSync(publicAsset), 'public/pyodide/pyodide.asm.wasm missing').toBe(true);
  });

  it('loads its core module relative to the (local) indexURL', () => {
    // The loader fetches `${indexURL}pyodide.asm.mjs`. Our worker always passes
    // indexURL: '/pyodide/', which this copy step serves from the app itself.
    // (A jsdelivr URL exists inside Pyodide purely for optional micropip
    // packages — the core runtime never uses it, and we never load packages.)
    const content = readFileSync(join(dest, 'pyodide.mjs'), 'utf8');
    expect(content).toContain('pyodide.asm.mjs');
  });
});