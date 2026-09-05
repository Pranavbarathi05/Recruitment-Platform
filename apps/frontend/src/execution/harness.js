/**
 * Client-side execution harness + result normalization (pure functions).
 *
 * Mirrors the backend's function-based model (apps/backend/services/harness.py):
 * the candidate writes ONE function (or class), and a generated harness calls it
 * with each public test case's arguments, compares the JSON-serialized return
 * value against the expected output, and reports per-test results.
 *
 * Execution happens in a Web Worker running Pyodide (CPython compiled to WASM).
 * The harness writes its JSON results to the RESULTS_GLOBAL variable, which the
 * worker reads back after execution; everything the candidate prints is
 * surfaced as program stdout.
 */

// Global variable the harness writes its JSON results to. Read back from JS
// after runPython, so program stdout never has to be parsed to find results.
export const RESULTS_GLOBAL = '__FREEBUFF_PAYLOAD';

export const MAX_OUTPUT_CHARS = 65536;

/**
 * Normalized status vocabulary used by the result UI:
 *  - passed         accepted
 *  - failed         wrong answer
 *  - compile_error  compilation failed (syntax/diagnostics)
 *  - runtime_error  execution raised
 *  - timeout        time limit exceeded
 */
export const STATUS = {
  PASSED: 'passed',
  FAILED: 'failed',
  COMPILE_ERROR: 'compile_error',
  RUNTIME_ERROR: 'runtime_error',
  TIMEOUT: 'timeout',
};

/**
 * Derive the per-test arguments and expected outputs, mirroring the backend:
 * function arguments when present, otherwise a single legacy `input` string
 * wrapped as the only argument. Returned data is injected into the Python
 * namespace by the runner (avoids embedding/escaping JSON in source).
 */
export function harnessTestData(testCases = []) {
  const testArguments = testCases.map((tc) =>
    Array.isArray(tc.arguments) ? tc.arguments : [tc.input ?? '']
  );
  const testExpected = testCases.map((tc) => tc.expected_output ?? '');
  return { testArguments, testExpected };
}

/**
 * Build the full Python program executed in the browser.
 * Mirrors generate_python_harness() from the backend. TEST_ARGS and
 * TEST_EXPECTED are injected into the run namespace by the worker, so the
 * source only references them by name.
 */
export function buildPythonHarness({
  sourceCode,
  functionName = 'solve',
  className = null,
  testCases = [],
}) {
  const { testArguments } = harnessTestData(testCases);
  const argRefs = (testArguments[0] || [])
    .map((_, i) => `_tc_args[${i}]`)
    .join(', ');

  const lines = [
    'import json',
    'import time',
    '',
    '# TEST_ARGS / TEST_EXPECTED are injected into this namespace by the runner',
    '',
    '# === Candidate Solution ===',
    sourceCode,
    '',
    '# === Test Harness ===',
    'results = []',
    'for _tc_idx, (_tc_args, _tc_expected) in enumerate(zip(TEST_ARGS, TEST_EXPECTED)):',
    '    _tc_start = time.perf_counter()',
    '    try:',
  ];

  if (className) {
    lines.push(`        _instance = ${className}()`);
    lines.push(`        _result = _instance.${functionName}(${argRefs})`);
  } else {
    lines.push(`        _result = ${functionName}(${argRefs})`);
  }

  lines.push(
    '        _result_json = json.dumps(_result, ensure_ascii=False)',
    '        _expected_json = json.dumps(_tc_expected, ensure_ascii=False)',
    '        _passed = _result_json == _expected_json',
    '        results.append({"passed": _passed, "actual": _result, "expected": _tc_expected, "time_ms": (time.perf_counter() - _tc_start) * 1000})',
    '    except Exception as e:',
    '        results.append({"passed": False, "error": str(e), "expected": _tc_expected, "time_ms": (time.perf_counter() - _tc_start) * 1000})',
    '',
    `${RESULTS_GLOBAL} = json.dumps(results, ensure_ascii=False)`
  );

  return lines.join('\n');
}

/** Human-friendly display value for expected/actual/input cells. */
export function formatValue(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Build structured per-test results from the harness JSON payload.
 */
export function buildResultsFromHarness({ parsed, testCases = [], totalMs = 0 }) {
  const results = [];
  let allPassed = true;

  testCases.forEach((tc, idx) => {
    const hr = parsed && Array.isArray(parsed) ? parsed[idx] : null;
    const tcExpected = tc.expected_output ?? '';

    if (!hr) {
      results.push({
        id: tc.id,
        is_public: true,
        passed: false,
        status: STATUS.RUNTIME_ERROR,
        expected_output: tcExpected,
        actual_output: '',
        input: tc.arguments ?? tc.input ?? null,
        stderr: 'No result was produced for this test case.',
        execution_time_ms: totalMs,
      });
      allPassed = false;
      return;
    }

    if (hr.error !== undefined && hr.error !== null) {
      results.push({
        id: tc.id,
        is_public: true,
        passed: false,
        status: STATUS.RUNTIME_ERROR,
        expected_output: tcExpected,
        actual_output: '',
        input: tc.arguments ?? tc.input ?? null,
        stderr: String(hr.error),
        execution_time_ms: Math.round(hr.time_ms ?? totalMs),
      });
      allPassed = false;
      return;
    }

    if (hr.passed) {
      results.push({
        id: tc.id,
        is_public: true,
        passed: true,
        status: STATUS.PASSED,
        expected_output: hr.expected ?? tcExpected,
        actual_output: hr.actual,
        input: tc.arguments ?? tc.input ?? null,
        stderr: null,
        execution_time_ms: Math.round(hr.time_ms ?? totalMs),
      });
      return;
    }

    results.push({
      id: tc.id,
      is_public: true,
      passed: false,
      status: STATUS.FAILED,
      expected_output: hr.expected ?? tcExpected,
      actual_output: hr.actual ?? '',
      input: tc.arguments ?? tc.input ?? null,
      stderr: null,
      execution_time_ms: Math.round(hr.time_ms ?? totalMs),
    });
    allPassed = false;
  });

  return { results, all_passed: allPassed };
}

/**
 * Classify a Python execution failure (raised out of the harness).
 * Syntax problems -> compile_error; interrupts -> timeout; everything else is a
 * runtime error.
 */
export function classifyRunError(error, interrupted = false) {
  const message =
    (error && (error.message || String(error))) || 'Unknown execution error';
  if (interrupted) {
    return { status: STATUS.TIMEOUT, message };
  }
  if (/(SyntaxError|IndentationError|TabError)/.test(message)) {
    return { status: STATUS.COMPILE_ERROR, message };
  }
  return { status: STATUS.RUNTIME_ERROR, message };
}

/**
 * Structured result for a failed run (compile/runtime error raised outside the
 * per-test harness, e.g. a syntax error in the candidate's function).
 */
export function buildErrorResults({ errorMessage, interrupted, testCases = [], timeLimitMs = 0 }) {
  const { status, message } = classifyRunError(
    { message: errorMessage },
    interrupted
  );

  const payload = {
    all_passed: false,
    results: [],
    error: null,
    message: null,
    stdout: '',
    stderr: '',
    compilation_error: null,
  };

  if (status === STATUS.COMPILE_ERROR) {
    payload.compilation_error = message;
    payload.results = testCases.map((tc) => ({
      id: tc.id,
      is_public: true,
      passed: false,
      status: STATUS.COMPILE_ERROR,
      expected_output: tc.expected_output ?? '',
      actual_output: '',
      input: tc.arguments ?? tc.input ?? null,
      stderr: message,
      execution_time_ms: 0,
    }));
    return payload;
  }

  if (status === STATUS.TIMEOUT) {
    return buildTimeoutResults(testCases, timeLimitMs);
  }

  // Runtime error raised outside the per-test harness (e.g. module-level code
  // in the candidate's solution). Surface it per test so the result panel
  // renders it; top-level `error` is reserved for catastrophic failures such
  // as runtime initialization problems.
  payload.stderr = message;
  payload.results = testCases.map((tc) => ({
    id: tc.id,
    is_public: true,
    passed: false,
    status: STATUS.RUNTIME_ERROR,
    expected_output: tc.expected_output ?? '',
    actual_output: '',
    input: tc.arguments ?? tc.input ?? null,
    stderr: message,
    execution_time_ms: 0,
  }));
  return payload;
}

/**
 * Structured TLE result. Used both when Pyodide raises KeyboardInterrupt and
 * when the main thread is forced to terminate the worker.
 */
export function buildTimeoutResults(testCases = [], timeLimitMs = 0) {
  return {
    all_passed: false,
    results: testCases.map((tc) => ({
      id: tc.id,
      is_public: true,
      passed: false,
      status: STATUS.TIMEOUT,
      expected_output: tc.expected_output ?? '',
      actual_output: '',
      input: tc.arguments ?? tc.input ?? null,
      stderr: null,
      execution_time_ms: timeLimitMs,
    })),
    error: null,
    message: `Time limit exceeded (${timeLimitMs}ms)`,
    stdout: '',
    stderr: '',
    compilation_error: null,
  };
}