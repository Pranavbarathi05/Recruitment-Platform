/**
 * PandasWasmRunner — Reusable browser-local Python/Pandas execution engine
 * using Pyodide (CPython compiled to WASM).
 *
 * Interface:
 *   initialize(problem)  — create Python environment, load pandas, create dataset
 *   execute(code)        — run candidate Python/Pandas code
 *   reset()              — reinitialize the environment
 *   dispose()            — tear down the Python environment
 *
 * All execution is 100% client-side. Candidate Python is NEVER sent to the backend.
 * Pyodide assets are served locally from /pyodide/ (no CDN).
 */

// Lazy-loaded Pyodide instance
let _pyodideInstance = null;
let _initPromise = null;

/**
 * Get or create the shared Pyodide instance.
 */
async function getPyodide() {
  if (_pyodideInstance) return _pyodideInstance;
  if (_initPromise) return _initPromise;

  _initPromise = (async () => {
    // Dynamically import Pyodide from the locally-served assets
    const pyodideHost = window.location.origin;
    const pyodideEntry = pyodideHost + '/pyodide/pyodide.mjs';
    const mod = await import(/* @vite-ignore */ pyodideEntry);
    const pyodide = await mod.loadPyodide({
      indexURL: '/pyodide/',
    });

    // Install pandas
    await pyodide.loadPackage('pandas');
    await pyodide.loadPackage('micropip');

    _pyodideInstance = pyodide;
    return pyodide;
  })();

  try {
    return await _initPromise;
  } catch (err) {
    _initPromise = null;
    throw err;
  }
}

/**
 * Convert a JS array of objects into a pandas DataFrame creation command.
 */
function buildDataFrameScript(dataset) {
  if (!dataset) return '';

  if (Array.isArray(dataset)) {
    // Array of { table, columns, rows } or { name, columns, data }
    const scripts = [];
    for (const entry of dataset) {
      const tableName = entry.table || entry.name || 'df';
      const columns = entry.columns || [];
      const rows = entry.rows || entry.data || [];

      if (!columns.length || !rows.length) continue;

      // Create a Python dict from the data
      const dataDict = {};
      for (let colIdx = 0; colIdx < columns.length; colIdx++) {
        const col = columns[colIdx];
        dataDict[col] = rows.map((row) => row[colIdx]);
      }

      const dictJson = JSON.stringify(dataDict);
      scripts.push(`
import json as _json
_${tableName}_data = _json.loads('${dictJson.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}')
${tableName} = pd.DataFrame(_${tableName}_data)
`);
    }
    return scripts.join('\n');
  }

  if (typeof dataset === 'string') {
    return dataset;
  }

  return '';
}

export class PandasWasmRunner {
  constructor() {
    this._pyodide = null;
    this._problem = null;
    this._initialized = false;
    this._globals = null;
  }

  /**
   * Initialize the runner with a problem definition.
   * Creates a Python environment, loads pandas, and creates the dataset.
   *
   * @param {Object} problem - Challenge definition with:
   *   problem.dataset - Array of { table, columns, rows } or Python code string
   *   problem.starter_code - Optional starter code shown to candidate
   */
  async initialize(problem) {
    this._problem = problem;
    this._pyodide = await getPyodide();

    // Create a fresh globals namespace
    this._globals = this._pyodide.globals.get('dict')();

    // Import pandas into the globals
    this._pyodide.runPython(`
import pandas as pd
import json
import time
import sys
import io
`, { globals: this._globals });

    // Load dataset
    const datasetScript = buildDataFrameScript(problem.dataset);
    if (datasetScript) {
      this._pyodide.runPython(datasetScript, { globals: this._globals });
    }

    this._initialized = true;
  }

  /**
   * Execute candidate Python/Pandas code and return structured results.
   *
   * @param {string} code - Candidate's Python code
   * @returns {{
   *   result: string|null,
   *   stdout: string,
   *   stderr: string,
   *   error: string|null,
   *   duration: number,
   *   dataframe: { columns: string[], rows: any[][] }|null
   * }}
   */
  async execute(code) {
    if (!this._initialized || !this._pyodide) {
      throw new Error('PandasWasmRunner not initialized. Call initialize() first.');
    }

    // Reset stdout/stderr capture
    let stdoutBuf = '';
    let stderrBuf = '';

    const captureStdout = (text) => { stdoutBuf += text; };
    const captureStderr = (text) => { stderrBuf += text; };

    // Set up stdout/stderr capture
    this._pyodide.setStdout({ batched: captureStdout });
    this._pyodide.setStderr({ batched: captureStderr });

    const startTime = performance.now();

    try {
      // Execute the candidate code
      this._pyodide.runPython(code, { globals: this._globals });

      const duration = performance.now() - startTime;

      // Try to capture the result - check common result variable names
      let result = null;
      let dataframe = null;

      try {
        // Check if there's a 'result' variable
        const hasResult = this._pyodide.runPython(
          `'result' in dir() or 'result' in globals()`,
          { globals: this._globals }
        );

        if (hasResult) {
          const resultObj = this._pyodide.runPython(`result`, { globals: this._globals });
          if (resultObj && resultObj.type !== 'undefined') {
            // Check if it's a DataFrame
            const isDf = this._pyodide.runPython(
              `isinstance(result, pd.DataFrame)`,
              { globals: this._globals }
            );

            if (isDf) {
              // Convert DataFrame to JSON
              const dfJson = this._pyodide.runPython(
                `result.to_json(orient='split')`,
                { globals: this._globals }
              );
              const parsed = JSON.parse(String(dfJson));
              dataframe = {
                columns: parsed.columns,
                rows: parsed.data,
              };
              result = null;
            } else {
              result = String(resultObj);
            }
          }
        }
      } catch {
        // No result variable, that's fine
      }

      // Clean up stdout/stderr
      this._pyodide.setStdout({ batched: () => {} });
      this._pyodide.setStderr({ batched: () => {} });

      return {
        result,
        stdout: stdoutBuf.trim(),
        stderr: stderrBuf.trim(),
        error: null,
        duration: Math.round(duration * 100) / 100,
        dataframe,
      };
    } catch (err) {
      const duration = performance.now() - startTime;
      const errorMsg = err.message || String(err);

      // Clean up stdout/stderr
      this._pyodide.setStdout({ batched: () => {} });
      this._pyodide.setStderr({ batched: () => {} });

      return {
        result: null,
        stdout: stdoutBuf.trim(),
        stderr: stderrBuf.trim(),
        error: errorMsg,
        duration: Math.round(duration * 100) / 100,
        dataframe: null,
      };
    }
  }

  /**
   * Reset the environment: reinitialize Python and reload dataset.
   */
  async reset() {
    if (!this._pyodide || !this._problem) return;

    // Create a fresh globals namespace
    this._globals = this._pyodide.globals.get('dict')();

    this._pyodide.runPython(`
import pandas as pd
import json
import time
import sys
import io
`, { globals: this._globals });

    const datasetScript = buildDataFrameScript(this._problem.dataset);
    if (datasetScript) {
      this._pyodide.runPython(datasetScript, { globals: this._globals });
    }
  }

  /**
   * Dispose of the runner. The shared Pyodide instance persists for reuse.
   */
  async dispose() {
    this._globals = null;
    this._initialized = false;
    this._problem = null;
  }
}

/**
 * Lazily initialize Pyodide. Called when a pandas_wasm challenge is first opened.
 */
export async function initPandasWasm() {
  return getPyodide();
}

/**
 * Check if Pyodide is available in this browser.
 */
export function isPandasWasmSupported() {
  return typeof WebAssembly !== 'undefined' && typeof SharedArrayBuffer !== 'undefined';
}
