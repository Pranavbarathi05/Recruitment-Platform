/**
 * Code Runner Worker
 *
 * Executes candidate code in a separate thread using Pyodide (CPython compiled
 * to WASM). All runtime assets are served locally by the application from
 * /pyodide/ (see scripts/copy-pyodide.mjs) — no CDN, no external compiler.
 *
 * Protocol (messages to/from the main thread):
 *   main -> worker  { type: 'execute', runId, payload }
 *   worker -> main  { type: 'loading', runId }          (Pyodide initializing)
 *   worker -> main  { type: 'started', runId }          (execution began)
 *   worker -> main  { type: 'result', runId, result }   (structured result)
 *   worker -> main  { type: 'busy', runId }             (overlapping execution)
 *
 * The worker processes one execution at a time. A synchronous infinite loop in
 * the candidate's code blocks this thread only — the main thread enforces the
 * time limit and terminates the worker when needed, so the page never freezes.
 * (Pyodide cannot process messages while a synchronous run is in progress, so
 * timeouts are enforced from the main thread via worker.terminate().)
 */
import {
  buildPythonHarness,
  harnessTestData,
  buildResultsFromHarness,
  buildErrorResults,
  RESULTS_GLOBAL,
  MAX_OUTPUT_CHARS,
} from './harness';

// Served locally by the application (copied from node_modules/pyodide).
const PYODIDE_INDEX_URL = '/pyodide/';
// Referenced through a variable so bundlers leave the runtime import alone.
const PYODIDE_ENTRY_URL = `${PYODIDE_INDEX_URL}pyodide.mjs`;

let pyodidePromise = null;
let runningRunId = null;

// Captured output for the CURRENT run (runs are serialized by the manager).
let stdoutBuf = '';
let stderrBuf = '';

function capture(text, isStderr) {
  const buffer = isStderr ? stderrBuf : stdoutBuf;
  if (buffer.length >= MAX_OUTPUT_CHARS) return;
  const room = MAX_OUTPUT_CHARS - buffer.length;
  const chunk = text.length <= room ? text : text.slice(0, room);
  if (isStderr) {
    stderrBuf += chunk;
  } else {
    stdoutBuf += chunk;
  }
}

function getPyodide() {
  if (!pyodidePromise) {
    // Loaded at runtime from the app's own static assets so the ~9.6MB wasm +
    // stdlib are never bundled into JS chunks and always served locally
    // (works offline / on restricted networks).
    pyodidePromise = import(/* @vite-ignore */ PYODIDE_ENTRY_URL)
      .then((mod) =>
        mod.loadPyodide({
          indexURL: PYODIDE_INDEX_URL,
          stdout: (text) => capture(text, false),
          stderr: (text) => capture(text, true),
        })
      )
      .catch((err) => {
        pyodidePromise = null; // allow retry on next run
        throw err;
      });
  }
  return pyodidePromise;
}

async function executeRun(payload) {
  const {
    sourceCode,
    functionName = 'solve',
    className = null,
    testCases = [],
    timeLimitMs = 2000,
  } = payload || {};

  if (!testCases || testCases.length === 0) {
    return { all_passed: true, results: [], message: 'No public test cases' };
  }

  let pyodide;
  try {
    pyodide = await getPyodide();
  } catch (err) {
    return {
      all_passed: false,
      results: [],
      error:
        'Could not initialize the in-browser Python runtime. ' +
        `(${err && err.message ? err.message : err})`,
    };
  }

  stdoutBuf = '';
  stderrBuf = '';

  const harnessSource = buildPythonHarness({
    sourceCode,
    functionName,
    className,
    testCases,
  });

  // Fresh namespace per run so globals cannot leak between executions.
  const globals = pyodide.globals.get('dict')();
  const { testArguments, testExpected } = harnessTestData(testCases);
  globals.set('TEST_ARGS', pyodide.toPy(testArguments));
  globals.set('TEST_EXPECTED', pyodide.toPy(testExpected));

  const start = performance.now();
  let payloadStr = null;
  try {
    pyodide.runPython(harnessSource, { globals });
    const payload = globals.get(RESULTS_GLOBAL);
    if (payload !== undefined && payload !== null) {
      payloadStr = String(payload);
    }
  } catch (err) {
    // Python raised out of the harness: syntax error, top-level exception, or
    // KeyboardInterrupt from an interrupted run. The error message carries the
    // traceback; stderr holds interpreter diagnostics.
    const interrupted = /KeyboardInterrupt/.test(err && err.message ? err.message : String(err));
    const result = buildErrorResults({
      errorMessage: err && err.message ? err.message : String(err),
      interrupted,
      testCases,
      timeLimitMs,
    });
    result.stdout = trimOutput(stdoutBuf);
    if (!result.stderr) result.stderr = trimOutput(stderrBuf);
    return result;
  } finally {
    globals.destroy();
  }

  const totalMs = performance.now() - start;

  let parsed = null;
  if (payloadStr) {
    try {
      parsed = JSON.parse(payloadStr);
    } catch {
      parsed = null;
    }
  }

  if (!parsed) {
    return {
      all_passed: false,
      results: testCases.map((tc) => ({
        id: tc.id,
        is_public: true,
        passed: false,
        status: 'runtime_error',
        expected_output: tc.expected_output ?? '',
        actual_output: '',
        input: tc.arguments ?? tc.input ?? null,
        stderr: stderrBuf || 'Could not parse harness output.',
        execution_time_ms: Math.round(totalMs),
      })),
      stdout: trimOutput(stdoutBuf),
      stderr: trimOutput(stderrBuf),
    };
  }

  const built = buildResultsFromHarness({ parsed, testCases, totalMs });
  return {
    ...built,
    stdout: trimOutput(stdoutBuf),
    stderr: trimOutput(stderrBuf),
    error: null,
    message: null,
    compilation_error: null,
  };
}

function trimOutput(text) {
  return (text || '').trim();
}

self.onmessage = async (event) => {
  const msg = event && event.data;
  if (!msg || typeof msg !== 'object') return;

  if (msg.type !== 'execute') return;

  if (runningRunId !== null) {
    self.postMessage({ type: 'busy', runId: msg.runId });
    return;
  }

  runningRunId = msg.runId;
  try {
    // Let the manager know the runtime is still initializing so it can use a
    // generous init timeout instead of counting against the execution limit.
    if (!pyodidePromise) {
      self.postMessage({ type: 'loading', runId: msg.runId });
    }
    await getPyodide();
    self.postMessage({ type: 'started', runId: msg.runId });
    const result = await executeRun(msg.payload);
    self.postMessage({ type: 'result', runId: msg.runId, result });
  } catch (err) {
    self.postMessage({
      type: 'result',
      runId: msg.runId,
      result: {
        all_passed: false,
        results: [],
        error: (err && err.message) || String(err),
      },
    });
  } finally {
    runningRunId = null;
  }
};