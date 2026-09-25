import { describe, it, expect } from 'vitest';
import { existsSync } from 'node:fs';
import { Writable } from 'node:stream';
import { runtimeAssetsPlugin } from './vite-plugin-runtime-assets.mjs';

/**
 * The middleware that fixed the DEV runtime loading failures.
 *
 * Vite's public/ index went stale when the copy scripts wiped and re-created
 * public/pyodide and public/duckdb, so `/pyodide/pyodide.mjs` and the DuckDB
 * worker were answered with index.html (200, text/html). This middleware
 * resolves the file on disk per request instead, which is what makes
 * `Browser -> DuckDB-WASM` and `Browser -> Pyodide` work in DEV.
 */

/** Pull the middleware out of the plugin without booting a real Vite server. */
function captureMiddleware() {
  let middleware;
  const plugin = runtimeAssetsPlugin();
  plugin.configureServer({ middlewares: { use: (fn) => { middleware = fn; } } });
  return middleware;
}

/** Minimal ServerResponse stand-in that records status, headers and body. */
function makeRes() {
  const headers = {};
  const chunks = [];
  const res = new Writable({
    write(chunk, _enc, cb) {
      chunks.push(chunk);
      cb();
    },
  });
  res.statusCode = 0;
  res.setHeader = (key, value) => { headers[key.toLowerCase()] = value; };
  res.getHeader = (key) => headers[key.toLowerCase()];
  res.headers = headers;
  res.body = () => Buffer.concat(chunks).toString('utf8');
  res.bodyBytes = () => Buffer.concat(chunks).length;
  return res;
}

/** Invoke the middleware and settle when either it responds or calls next(). */
async function run(middleware, url, method = 'GET') {
  const res = makeRes();
  let nextCalled = false;
  await new Promise((resolve) => {
    const settle = () => resolve();
    res.on('finish', settle);
    middleware({ method, url }, res, () => { nextCalled = true; settle(); });
  });
  return { res, nextCalled };
}

const middleware = captureMiddleware();

describe('runtime assets middleware — serves /pyodide and /duckdb from public/', () => {
  it('serves the DuckDB WASM binary with the application/wasm MIME', async () => {
    expect(existsSync('public/duckdb/duckdb-mvp.wasm')).toBe(true);
    const { res, nextCalled } = await run(middleware, '/duckdb/duckdb-mvp.wasm');
    expect(nextCalled).toBe(false);
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toBe('application/wasm');
    // The whole binary, not a 683-byte index.html.
    expect(res.bodyBytes()).toBeGreaterThan(1_000_000);
  });

  it('serves the DuckDB worker script as JavaScript', async () => {
    const { res } = await run(middleware, '/duckdb/duckdb-browser-eh.worker.js');
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toBe('text/javascript; charset=utf-8');
    expect(res.bodyBytes()).toBeGreaterThan(1000);
  });

  it('serves pyodide.mjs as JavaScript, not HTML', async () => {
    const { res } = await run(middleware, '/pyodide/pyodide.mjs');
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toBe('text/javascript; charset=utf-8');
    expect(res.body()).toContain('loadPyodide');
  });

  it('serves the Pyodide wasm, stdlib and lock file with correct MIMEs', async () => {
    const wasm = await run(middleware, '/pyodide/pyodide.asm.wasm');
    expect(wasm.res.statusCode).toBe(200);
    expect(wasm.res.headers['content-type']).toBe('application/wasm');

    const stdlib = await run(middleware, '/pyodide/python_stdlib.zip');
    expect(stdlib.res.headers['content-type']).toBe('application/zip');

    const lock = await run(middleware, '/pyodide/pyodide-lock.json');
    expect(lock.res.headers['content-type']).toBe('application/json');
  });

  it('answers a missing runtime file with a loud 404 instead of index.html', async () => {
    const { res, nextCalled } = await run(middleware, '/pyodide/does-not-exist.wasm');
    expect(nextCalled).toBe(false);
    expect(res.statusCode).toBe(404);
    expect(res.headers['content-type']).toBe('text/plain; charset=utf-8');
  });

  it('supports HEAD so a probe gets the headers without the body', async () => {
    const { res } = await run(middleware, '/pyodide/pyodide.mjs', 'HEAD');
    expect(res.statusCode).toBe(200);
    expect(res.headers['content-length']).toBeGreaterThan(0);
    expect(res.bodyBytes()).toBe(0);
  });

  it('leaves Vite asset-import queries (?url / ?import / ?raw) to Vite', async () => {
    for (const url of [
      '/duckdb/duckdb-eh.wasm?import&url',
      '/duckdb/duckdb-browser-eh.worker.js?url',
      '/pyodide/pyodide.mjs?raw',
    ]) {
      const { nextCalled } = await run(middleware, url);
      expect(nextCalled, url).toBe(true);
    }
  });

  it('ignores requests outside the two runtime prefixes', async () => {
    for (const url of ['/', '/index.html', '/src/main.jsx', '/assets/logo.svg']) {
      const { nextCalled } = await run(middleware, url);
      expect(nextCalled, url).toBe(true);
    }
  });

  it('never serves a file from outside public/ (path traversal stays behind)', async () => {
    const { nextCalled } = await run(middleware, '/pyodide/../../package.json');
    expect(nextCalled).toBe(true);
  });
});
