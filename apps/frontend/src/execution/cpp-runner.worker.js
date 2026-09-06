/**
 * C++ WASM Compilation + Execution Worker (scaffold)
 *
 * Parallels codeRunner.worker.js in structure and message protocol.
 * Currently a placeholder: Emscripten toolchain is NOT bundled here.
 * The intended flow once Emscripten WASM assets are available:
 *
 *   main -> worker  { type: 'execute', runId, payload }
 *   worker -> main  { type: 'loading', runId }            (toolchain init)
 *   worker -> main  { type: 'started', runId }            (execution began)
 *   worker -> main  { type: 'result', runId, result }     (structured result)
 *   worker -> main  { type: 'busy', runId }               (overlapping execution)
 *
 * Toolchain assets would be served locally from the app (e.g. /cpp-wasm/),
 * analogous to how Pyodide assets are served from /pyodide/.
 */

import { buildCppHarness } from './cpp-harness.js';

const STDOUT_MAX = 65536;
const STDERR_MAX = 65536;

let stdoutBuf = '';
let stderrBuf = '';

function capture(text, isStderr) {
  const buf = isStderr ? stderrBuf : stdoutBuf;
  if (buf.length >= (isStderr ? STDERR_MAX : STDOUT_MAX)) return;
  const room = (isStderr ? STDERR_MAX : STDOUT_MAX) - buf.length;
  const chunk = text.length <= room ? text : text.slice(0, room);
  if (isStderr) {
    stderrBuf += chunk;
  } else {
    stdoutBuf += chunk;
  }
}

// Placeholder: in a real implementation this would be the Emscripten WASM
// runtime loader (e.g. a standalone .wasm + generated JS glue, or a full
// Emscripten Module that we instantiate in this worker).
//
// For the scaffold we just return a clear "not-implemented" result so the
// harness pipeline can be unit-tested without a C++ compiler present.
async function compileAndRun({
  sourceCode,
  functionName = 'solve',
  className = null,
  testCases = [],
  timeLimitMs = 2000,
}) {
  stdoutBuf = '';
  stderrBuf = '';

  const harnessSource = buildCppHarness({
    sourceCode,
    functionName,
    className,
    testCases,
  });

  // In a real implementation:
  // 1. Write solution + harness to virtual FS files.
  // 2. Invoke the Emscripten toolchain (emcc / wasm-ld) available in the
  //    worker's asset bundle to compile to a standalone .wasm.
  // 3. Instantiate the WebAssembly.Module and call the harness entry point.
  // 4. Capture stdout/stderr, read results back.
  //
  // For now, report that this path requires the Emscripten toolchain bundle.
  return {
    all_passed: false,
    results: [],
    error: 'C++ client-side execution is not yet implemented. This requires an Emscripten (or equivalent WASM) toolchain bundle in the browser.',
    stdout: '',
    stderr: stderrBuf || '',
    compilation_error: null,
    message: 'C++ local execution not available',
  };
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

  return compileAndRun({
    sourceCode,
    functionName,
    className,
    testCases,
    timeLimitMs,
  });
}

// ---- worker message handling (parallel to codeRunner.worker.js) ----

self.onmessage = async (event) => {
  const msg = event.data;
  if (!msg || typeof msg !== 'object') return;

  switch (msg.type) {
    case 'execute': {
      const { runId, payload } = msg;
      try {
        self.postMessage({ type: 'loading', runId });
        const result = await executeRun(payload);
        self.postMessage({ type: 'result', runId, result });
      } catch (err) {
        self.postMessage({
          type: 'result',
          runId,
          result: {
            all_passed: false,
            results: [],
            error: err && err.message ? err.message : 'Execution failed',
            stdout: '',
            stderr: '',
            compilation_error: null,
            message: 'Execution failed',
          },
        });
      }
      break;
    }
    default:
      break;
  }
};
