/**
 * Ensure the local Pyodide runtime exists in `public/pyodide/`.
 *
 * `npm run copy-pyodide` (postinstall/predev/prebuild) refreshes the runtime,
 * but any server started without npm — bare `vite`, `vite preview`, a
 * container CMD, a fresh checkout served directly — bypasses those hooks.
 * When `public/pyodide/` is missing, the coding worker's dynamic import of
 * `/pyodide/pyodide.mjs` fails at runtime with no build-time signal.
 *
 * This tiny inline plugin re-runs the copy at configure time when needed, so
 * the runtime is always present however the app is served. It stays fully
 * local/offline: assets come from the installed `pyodide` npm package only.
 * The copy is synchronous (cpSync) and cheap when already fresh.
 *
 * @returns {import('vite').Plugin}
 */
import { copyPyodideTo } from './copy-pyodide.mjs';

export function pyodideRuntimePlugin() {
  return {
    name: 'ensure-local-pyodide-runtime',
    // 'pre' so publicDir is populated before Vite serves the app.
    enforce: 'pre',
    configResolved() {
      try {
        copyPyodideTo();
      } catch (err) {
        // Non-fatal: npm hooks remain the primary path; surface a loud hint.
        console.warn(
          '[pyodide-runtime] could not refresh public/pyodide — ' +
            'run `npm run copy-pyodide` if the coding runner fails to load. ' +
            `(${err && err.message ? err.message : err})`
        );
      }
    },
  };
}
