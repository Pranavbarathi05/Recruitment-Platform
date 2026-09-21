/**
 * Ensure the local DuckDB-WASM runtime exists in `public/duckdb/`.
 *
 * Mirrors the pyodideRuntimePlugin — ensures the WASM and worker files are
 * present however the app is served (bare `vite`, `vite preview`, container CMD).
 *
 * @returns {import('vite').Plugin}
 */
import { copyDuckdbTo } from './copy-duckdb.mjs';

export function duckdbRuntimePlugin() {
  return {
    name: 'ensure-local-duckdb-runtime',
    enforce: 'pre',
    configResolved() {
      try {
        copyDuckdbTo();
      } catch (err) {
        console.warn(
          '[duckdb-runtime] could not refresh public/duckdb — ' +
            'run `npm run copy-duckdb` if the SQL runner fails to load. ' +
            `(${err && err.message ? err.message : err})`
        );
      }
    },
  };
}
