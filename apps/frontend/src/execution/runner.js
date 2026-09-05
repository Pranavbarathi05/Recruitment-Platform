/**
 * WorkerRunner — main-thread manager for the code-execution Web Worker.
 *
 * Responsibilities:
 *  - unique run IDs so stale results can never overwrite a newer run
 *  - execution timeout (per problem time limit + overhead); on timeout the
 *    worker is terminated and a structured TLE result is produced
 *  - worker recreation after termination (the next run lazily spawns a fresh
 *    worker and re-initializes the runtime)
 *  - protection against overlapping executions (rejects while busy)
 *  - a separate, generous timeout for first-time Pyodide initialization so a
 *    slow runtime download does not count against the candidate's time limit
 *
 * The manager talks to the worker using the protocol documented in
 * codeRunner.worker.js. A worker factory is injected so tests can substitute a
 * fake worker; production uses a real module worker.
 */
import { isClientRunnable } from './languages';
import { buildTimeoutResults } from './harness';

export { isClientRunnable };
export { CLIENT_RUNNABLE_LANGUAGES } from './languages';

const EXECUTION_OVERHEAD_MS = 1500;
const INIT_TIMEOUT_MS = 60000;

export function createWorker() {
  return new Worker(new URL('./codeRunner.worker.js', import.meta.url), {
    type: 'module',
  });
}

export class WorkerRunner {
  constructor(workerFactory = createWorker) {
    this._workerFactory = workerFactory;
    this._worker = null;
    this._generation = 0;
    this._runSeq = 0;
    // { runId, resolve, reject, timers: { init, exec }, testCases, timeLimitMs }
    this._pending = null;
  }

  get busy() {
    return this._pending !== null;
  }

  /**
   * Execute candidate code entirely client-side.
   * @returns {Promise<object>} structured result (see harness.js)
   * @throws {Error} if the language has no client-side runtime or a run is
   *   already in progress.
   */
  async run({
    language,
    sourceCode,
    testCases = [],
    functionName = 'solve',
    className = null,
    timeLimitMs = 2000,
  }) {
    if (!isClientRunnable(language)) {
      throw new Error(`Language "${language}" has no client-side runtime`);
    }
    if (this.busy) {
      throw new Error('A run is already in progress');
    }

    const runId = ++this._runSeq;
    const worker = this._ensureWorker();

    return new Promise((resolve, reject) => {
      const timers = { init: null, exec: null };
      this._pending = { runId, resolve, reject, timers, testCases, timeLimitMs };

      // Covers Pyodide initialization on the first run (downloading ~10MB of
      // local assets + WASM instantiation). Failure here means the runtime
      // could not be loaded at all, so reject rather than report TLE.
      timers.init = setTimeout(() => {
        this._terminateWorker();
        this._settlePending(
          null,
          `In-browser runtime failed to initialize (${INIT_TIMEOUT_MS / 1000}s limit)`,
          'error'
        );
      }, INIT_TIMEOUT_MS);

      worker.postMessage({
        type: 'execute',
        runId,
        payload: {
          language,
          sourceCode,
          testCases,
          functionName,
          className,
          timeLimitMs,
        },
      });
    });
  }

  /** Create the worker if needed and attach listeners for this generation. */
  _ensureWorker() {
    if (this._worker) return this._worker;

    const generation = ++this._generation;
    const worker = this._workerFactory();
    worker.addEventListener('message', (event) =>
      this._onMessage(event, generation)
    );
    worker.addEventListener('error', (event) => {
      if (generation !== this._generation) return;
      const message =
        (event && (event.message || (event.error && event.error.message))) ||
        'Code execution worker crashed';
      this._settlePending(null, message, 'error');
    });
    this._worker = worker;
    return worker;
  }

  _onMessage(event, generation) {
    if (generation !== this._generation) return; // message from a stale worker

    const msg = event && event.data;
    if (!msg || typeof msg !== 'object') return;

    const pending = this._pending;
    // Ignore anything that does not belong to the current run: a late result
    // from a previous run must never resolve (or overwrite) a newer one.
    if (!pending || msg.runId !== pending.runId) return;

    switch (msg.type) {
      case 'loading':
        // Pyodide still initializing; keep the init timeout running.
        break;
      case 'started':
        // Execution began — switch to the per-run execution timeout.
        clearTimeout(pending.timers.init);
        pending.timers.exec = setTimeout(() => {
          // Infinite loop (or anything else that overruns): kill the worker so
          // the page stays responsive, then report TLE. The next run lazily
          // creates a fresh worker.
          this._terminateWorker();
          this._settlePending(
            buildTimeoutResults(pending.testCases, pending.timeLimitMs),
            null,
            'timeout'
          );
        }, pending.timeLimitMs + EXECUTION_OVERHEAD_MS);
        break;
      case 'busy':
        this._settlePending(null, 'A run is already in progress', 'error');
        break;
      case 'result':
        this._settlePending(msg.result, null, 'result');
        break;
      default:
        break;
    }
  }

  /** Terminate the current worker; a fresh one is created on the next run. */
  _terminateWorker() {
    if (this._worker) {
      this._worker.terminate();
      this._worker = null;
      this._generation += 1;
    }
  }

  _settlePending(result, errorMessage, kind) {
    const pending = this._pending;
    if (!pending) return;
    this._pending = null;
    clearTimeout(pending.timers.init);
    clearTimeout(pending.timers.exec);

    if (kind === 'timeout' || kind === 'result') {
      pending.resolve(result);
    } else {
      const err = new Error(errorMessage || 'Execution failed');
      err.runId = pending.runId;
      pending.reject(err);
    }
  }
}

// Singleton shared across the coding UI so the Pyodide runtime is initialized
// once and reused for every run.
let sharedRunner = null;

/**
 * Run candidate code entirely in the browser (Web Worker + WASM).
 *
 * Only languages in CLIENT_RUNNABLE_LANGUAGES are supported; callers should
 * check isClientRunnable() first and keep using the existing server-side run
 * endpoint as a fallback for other languages.
 *
 * Returns a structured result compatible with the existing run endpoint shape:
 * {
 *   all_passed: boolean,
 *   results: [{ id, is_public, passed, status, expected_output, actual_output,
 *               input, stderr, execution_time_ms }],
 *   stdout, stderr, compilation_error, error, message
 * }
 */
export async function runCodeLocally(request) {
  if (!sharedRunner) {
    sharedRunner = new WorkerRunner(createWorker);
  }
  return sharedRunner.run(request);
}