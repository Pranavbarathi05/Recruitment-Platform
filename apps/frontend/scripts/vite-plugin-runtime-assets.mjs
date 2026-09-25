/**
 * Serve the local WASM runtimes (`/pyodide/*` and `/duckdb/*`) straight from
 * `public/`, registered BEFORE Vite's own middlewares.
 *
 * Why this exists:
 *
 * Vite's dev server keeps an in-memory index of `public/` files that is built
 * once at startup and then maintained only by filesystem watch events. The
 * copy scripts (and `npm run build`) refresh these runtime directories, and
 * when an add/unlink event is missed the index goes stale: `servePublicMiddleware`
 * then rejects the request and the SPA fallback answers with `index.html`
 * (200, text/html) instead of the asset. That produced both observed failures:
 *
 *   - `GET /pyodide/pyodide.mjs`  → index.html
 *       → "Failed to fetch dynamically imported module"
 *   - `GET /duckdb/duckdb-browser-eh.worker.js` → index.html
 *       → the DuckDB worker never parses, `instantiate()` never settles
 *       → the SQL challenge hangs forever on "Preparing SQL environment..."
 *
 * This middleware resolves the exact file on disk on every request, so asset
 * serving is deterministic regardless of the state of Vite's index. It is
 * dev-time only in practice (production is served by nginx), but harmless
 * everywhere: it only claims GET/HEAD requests under the two runtime prefixes
 * and never shadows Vite's `?url`/`?import`/`?raw` asset-import handling.
 */
import { createReadStream, statSync } from 'node:fs';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PUBLIC_DIR = resolve(ROOT, 'public');
const PREFIXES = ['/pyodide/', '/duckdb/'];

// Asset-import queries Vite itself must answer (?url, ?import, ?raw, ...).
const VITE_ASSET_QUERY = /[?&](url|import|raw|inline|no-inline)([=&]|$)/;

const MIME_TYPES = {
  '.mjs': 'text/javascript; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.wasm': 'application/wasm',
  '.json': 'application/json',
  '.zip': 'application/zip',
  '.whl': 'application/octet-stream',
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.map': 'application/json',
  '.ts': 'text/plain; charset=utf-8',
  '.md': 'text/plain; charset=utf-8',
};

/**
 * @returns {import('vite').Plugin}
 */
export function runtimeAssetsPlugin() {
  return {
    name: 'serve-local-wasm-runtimes',
    enforce: 'pre',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') return next();

        const url = req.url || '';
        const qIdx = url.indexOf('?');
        const pathname = qIdx === -1 ? url : url.slice(0, qIdx);
        const query = qIdx === -1 ? '' : url.slice(qIdx);

        if (!PREFIXES.some((prefix) => pathname.startsWith(prefix))) return next();
        // Let Vite handle its own asset-import requests (e.g.
        // `/duckdb/duckdb-eh.wasm?import&url` must return a URL module).
        if (VITE_ASSET_QUERY.test(query)) return next();

        let decoded;
        try {
          decoded = decodeURIComponent(pathname);
        } catch {
          return next();
        }

        const filePath = join(PUBLIC_DIR, decoded);
        if (!filePath.startsWith(PUBLIC_DIR + sep)) return next();

        let stat;
        try {
          stat = statSync(filePath);
        } catch {
          stat = null;
        }
        if (!stat || !stat.isFile()) {
          // A missing runtime file should be a loud 404, not a silent
          // index.html that surfaces as a confusing dynamic-import error.
          res.statusCode = 404;
          res.setHeader('Content-Type', 'text/plain; charset=utf-8');
          res.end('Not found');
          return;
        }

        const ext = filePath.slice(filePath.lastIndexOf('.')).toLowerCase();
        res.statusCode = 200;
        res.setHeader('Content-Type', MIME_TYPES[ext] || 'application/octet-stream');
        res.setHeader('Content-Length', stat.size);
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Last-Modified', stat.mtime.toUTCString());
        if (req.method === 'HEAD') {
          res.end();
          return;
        }
        createReadStream(filePath).pipe(res);
      });
    },
  };
}
