import { describe, it, expect } from 'vitest';
import {
  buildPythonHarness,
  harnessTestData,
  buildResultsFromHarness,
  buildErrorResults,
  buildTimeoutResults,
  classifyRunError,
  formatValue,
  RESULTS_GLOBAL,
} from './harness';

describe('harnessTestData', () => {
  it('uses function arguments when present', () => {
    const { testArguments, testExpected } = harnessTestData([
      { id: 't1', arguments: [1, 2], expected_output: 3 },
      { id: 't2', arguments: [4, 5], expected_output: 9 },
    ]);
    expect(testArguments).toEqual([[1, 2], [4, 5]]);
    expect(testExpected).toEqual([3, 9]);
  });

  it('wraps a legacy input string as the single argument (backend parity)', () => {
    const { testArguments } = harnessTestData([
      { id: 't1', input: 'hello', expected_output: 'hello' },
    ]);
    expect(testArguments).toEqual([['hello']]);
  });
});

describe('buildPythonHarness', () => {
  it('embeds the candidate solution and references injected test data', () => {
    const source = buildPythonHarness({
      sourceCode: 'def solve(a, b):\n    return a + b',
      functionName: 'solve',
      className: null,
      testCases: [
        { id: 't1', arguments: [1, 2], expected_output: 3 },
        { id: 't2', arguments: [4, 5], expected_output: 9 },
      ],
    });

    expect(source).toContain('def solve(a, b):\n    return a + b');
    expect(source).toContain('_result = solve(_tc_args[0], _tc_args[1])');
    expect(source).toContain('enumerate(zip(TEST_ARGS, TEST_EXPECTED))');
    expect(source).toContain(`${RESULTS_GLOBAL} = json.dumps(results, ensure_ascii=False)`);
  });

  it('instantiates the class-based harness when className is provided', () => {
    const source = buildPythonHarness({
      sourceCode: 'class Solution:\n    def twoSum(self, nums, target):\n        return [0, 1]',
      functionName: 'twoSum',
      className: 'Solution',
      testCases: [
        { id: 't1', arguments: [[2, 7, 11, 15], 9], expected_output: [0, 1] },
      ],
    });
    expect(source).toContain('_instance = Solution()');
    expect(source).toContain('_instance.twoSum(_tc_args[0], _tc_args[1])');
  });
});

describe('buildResultsFromHarness', () => {
  const testCases = [
    { id: 't1', arguments: [2], expected_output: 4 },
    { id: 't2', arguments: [3], expected_output: 9 },
  ];

  it('marks passing tests as passed', () => {
    const { results, all_passed } = buildResultsFromHarness({
      parsed: [
        { passed: true, actual: 4, expected: 4, time_ms: 1.2 },
        { passed: true, actual: 9, expected: 9, time_ms: 0.8 },
      ],
      testCases,
      totalMs: 5,
    });
    expect(all_passed).toBe(true);
    expect(results[0].status).toBe('passed');
    expect(results[0].passed).toBe(true);
    expect(results[0].actual_output).toBe(4);
  });

  it('reports wrong answers with expected and actual output', () => {
    const { results, all_passed } = buildResultsFromHarness({
      parsed: [
        { passed: true, actual: 4, expected: 4, time_ms: 1 },
        { passed: false, actual: 8, expected: 9, time_ms: 1 },
      ],
      testCases,
      totalMs: 5,
    });
    expect(all_passed).toBe(false);
    expect(results[1].status).toBe('failed');
    expect(results[1].passed).toBe(false);
    expect(results[1].expected_output).toBe(9);
    expect(results[1].actual_output).toBe(8);
    expect(results[1].input).toEqual([3]);
  });

  it('reports per-test runtime errors with the exception message', () => {
    const { results } = buildResultsFromHarness({
      parsed: [{ passed: false, error: 'division by zero', expected: 4, time_ms: 1 }],
      testCases,
      totalMs: 5,
    });
    expect(results[0].status).toBe('runtime_error');
    expect(results[0].stderr).toBe('division by zero');
  });
});

describe('buildErrorResults', () => {
  const testCases = [{ id: 't1', arguments: [1], expected_output: 2 }];

  it('classifies syntax errors as compile_error with diagnostics', () => {
    const result = buildErrorResults({
      errorMessage: 'Traceback ...\nSyntaxError: invalid syntax',
      interrupted: false,
      testCases,
      timeLimitMs: 2000,
    });
    expect(result.all_passed).toBe(false);
    expect(result.compilation_error).toContain('SyntaxError');
    expect(result.results[0].status).toBe('compile_error');
  });

  it('classifies non-syntax failures as runtime_error', () => {
    const result = buildErrorResults({
      errorMessage: 'Traceback ...\nRuntimeError: boom',
      interrupted: false,
      testCases,
      timeLimitMs: 2000,
    });
    expect(result.results[0].status).toBe('runtime_error');
    expect(result.stderr).toContain('RuntimeError');
  });

  it('classifies interrupts as timeout', () => {
    const result = buildErrorResults({
      errorMessage: 'KeyboardInterrupt',
      interrupted: true,
      testCases,
      timeLimitMs: 2000,
    });
    expect(result.results[0].status).toBe('timeout');
  });
});

describe('buildTimeoutResults', () => {
  it('produces per-test TLE results', () => {
    const result = buildTimeoutResults(
      [{ id: 't1', arguments: [1], expected_output: 2 }],
      2000
    );
    expect(result.all_passed).toBe(false);
    expect(result.message).toContain('2000ms');
    expect(result.results[0].status).toBe('timeout');
    expect(result.results[0].execution_time_ms).toBe(2000);
  });
});

describe('classifyRunError', () => {
  it('maps interrupt to timeout', () => {
    expect(classifyRunError({ message: 'KeyboardInterrupt' }, true).status).toBe('timeout');
  });
  it('maps SyntaxError/IndentationError/TabError to compile_error', () => {
    expect(classifyRunError({ message: 'SyntaxError: x' }).status).toBe('compile_error');
    expect(classifyRunError({ message: 'IndentationError: y' }).status).toBe('compile_error');
  });
  it('maps anything else to runtime_error', () => {
    expect(classifyRunError({ message: 'ZeroDivisionError' }).status).toBe('runtime_error');
    expect(classifyRunError(null).status).toBe('runtime_error');
  });
});

describe('formatValue', () => {
  it('renders strings and JSON values for the UI', () => {
    expect(formatValue('hello')).toBe('hello');
    expect(formatValue([1, 2])).toBe('[1,2]');
    expect(formatValue(null)).toBe('');
    expect(formatValue(undefined)).toBe('');
  });
});