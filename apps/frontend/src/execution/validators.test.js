import { describe, it, expect } from 'vitest';
import { validateSql, validatePandas, validateWasmResult } from './validators';

// ============================================================
// SQL Validator Tests
// ============================================================

describe('SQL Validator', () => {
  it('passes when columns match', () => {
    const result = {
      columns: ['department', 'avg_salary'],
      rows: [['Engineering', 80000], ['Marketing', 60000]],
      duration: 10,
      error: null,
    };
    const spec = { expected_columns: ['department', 'avg_salary'] };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
    expect(v.score).toBe(1);
  });

  it('fails when columns are missing', () => {
    const result = {
      columns: ['department'],
      rows: [['Engineering']],
      duration: 10,
      error: null,
    };
    const spec = { expected_columns: ['department', 'avg_salary'] };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
    expect(v.details).toContain('Missing columns');
  });

  it('passes order-insensitive row comparison', () => {
    const result = {
      columns: ['dept', 'avg'],
      rows: [['Marketing', 60000], ['Engineering', 80000]],
      duration: 10,
      error: null,
    };
    const spec = {
      expected_rows: [['Engineering', 80000], ['Marketing', 60000]],
      order_sensitive: false,
    };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('fails order-sensitive row comparison when order differs', () => {
    const result = {
      columns: ['dept', 'avg'],
      rows: [['Marketing', 60000], ['Engineering', 80000]],
      duration: 10,
      error: null,
    };
    const spec = {
      expected_rows: [['Engineering', 80000], ['Marketing', 60000]],
      order_sensitive: true,
    };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
  });

  it('passes with numeric tolerance', () => {
    const result = {
      columns: ['val'],
      rows: [[100.005]],
      duration: 10,
      error: null,
    };
    const spec = {
      expected_rows: [[100.0]],
      numeric_tolerance: 0.01,
    };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('fails outside numeric tolerance', () => {
    const result = {
      columns: ['val'],
      rows: [[100.5]],
      duration: 10,
      error: null,
    };
    const spec = {
      expected_rows: [[50.0]],
      numeric_tolerance: 0.01,
    };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
  });

  it('passes empty result when expect_empty is true', () => {
    const result = { columns: [], rows: [], duration: 1, error: null };
    const spec = { expect_empty: true };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('fails when empty result but row count expected', () => {
    const result = { columns: [], rows: [], duration: 1, error: null };
    const spec = { expected_row_count: 5 };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
  });

  it('passes expected error', () => {
    const result = { columns: [], rows: [], duration: 1, error: 'Syntax error near SELECT' };
    const spec = { expect_error: true };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('fails when error expected but query succeeded', () => {
    const result = { columns: ['id'], rows: [[1]], duration: 1, error: null };
    const spec = { expect_error: true };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
  });

  it('passes error pattern match', () => {
    const result = { columns: [], rows: [], duration: 1, error: 'Table "xyz" does not exist' };
    const spec = { expect_error: true, error_pattern: 'does not exist' };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('passes row count validation', () => {
    const result = { columns: ['id'], rows: [[1], [2], [3]], duration: 1, error: null };
    const spec = { expected_row_count: 3 };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(true);
  });

  it('fails row count mismatch', () => {
    const result = { columns: ['id'], rows: [[1], [2]], duration: 1, error: null };
    const spec = { expected_row_count: 3 };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
  });

  it('returns error when query fails and no error expected', () => {
    const result = { columns: [], rows: [], duration: 1, error: 'Some error' };
    const spec = { expected_columns: ['id'] };
    const v = validateSql(result, spec);
    expect(v.passed).toBe(false);
    expect(v.details).toContain('Query error');
  });
});

// ============================================================
// Pandas Validator Tests
// ============================================================

describe('Pandas Validator', () => {
  it('passes when dataframe columns match', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: {
        columns: ['department', 'salary'],
        rows: [['Engineering', 85000], ['Marketing', 62500]],
      },
    };
    const spec = { expected_columns: ['department', 'salary'] };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(true);
  });

  it('passes with numeric tolerance in dataframe', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: {
        columns: ['dept', 'avg'],
        rows: [['Engineering', 88333.34], ['Marketing', 62500.0]],
      },
    };
    const spec = {
      expected_values: [['Engineering', 88333.33], ['Marketing', 62500.0]],
      numeric_tolerance: 1.0,
      order_sensitive: false,
    };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(true);
  });

  it('fails when dataframe has error', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: "NameError: name 'df' is not defined",
      duration: 10,
      dataframe: null,
    };
    const spec = { expected_columns: ['department'] };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(false);
    expect(v.details).toContain('Execution error');
  });

  it('fails when dataframe expected but not returned', () => {
    const execResult = {
      result: '42',
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: null,
    };
    const spec = { expected_columns: ['department'] };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(false);
    expect(v.details).toContain('DataFrame');
  });

  it('passes shape validation', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: {
        columns: ['a', 'b'],
        rows: [[1, 2], [3, 4]],
      },
    };
    const spec = { expected_shape: [2, 2] };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(true);
  });

  it('fails shape mismatch', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: {
        columns: ['a', 'b'],
        rows: [[1, 2]],
      },
    };
    const spec = { expected_shape: [2, 2] };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(false);
  });

  it('order-insensitive value comparison works', () => {
    const execResult = {
      result: null,
      stdout: '',
      stderr: '',
      error: null,
      duration: 10,
      dataframe: {
        columns: ['dept', 'sal'],
        rows: [['Marketing', 62500], ['Engineering', 88333.33]],
      },
    };
    const spec = {
      expected_values: [['Engineering', 88333.33], ['Marketing', 62500]],
      order_sensitive: false,
      numeric_tolerance: 1.0,
    };
    const v = validatePandas(execResult, spec);
    expect(v.passed).toBe(true);
  });
});

// ============================================================
// Unified validator dispatch
// ============================================================

describe('validateWasmResult', () => {
  it('dispatches to SQL validator', () => {
    const result = { columns: ['a'], rows: [[1]], duration: 1, error: null };
    const v = validateWasmResult('sql_wasm', result, { expected_columns: ['a'] });
    expect(v.passed).toBe(true);
  });

  it('dispatches to Pandas validator', () => {
    const result = {
      result: null, stdout: '', stderr: '', error: null, duration: 1,
      dataframe: { columns: ['a'], rows: [[1]] },
    };
    const v = validateWasmResult('pandas_wasm', result, { expected_columns: ['a'] });
    expect(v.passed).toBe(true);
  });

  it('returns error for unknown type', () => {
    const v = validateWasmResult('unknown', {}, {});
    expect(v.passed).toBe(false);
  });
});
