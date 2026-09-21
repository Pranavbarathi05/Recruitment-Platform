/**
 * Validators for WASM-based Hands-On challenges.
 *
 * These run entirely in the browser. Client-side validation is NOT a security
 * boundary — it's for candidate feedback only. The backend independently
 * validates submission lifecycle, ownership, and maximum score.
 *
 * SQL Validator:
 *   - column matching
 *   - row matching (order-sensitive and order-insensitive)
 *   - row count
 *   - numeric tolerance
 *   - empty-result validation
 *   - error expectations
 *
 * Pandas Validator:
 *   - column matching
 *   - shape (rows x cols)
 *   - dataframe values (order-sensitive and order-insensitive)
 *   - numeric tolerance
 */

// ============================================================
// Helpers
// ============================================================

/**
 * Check if two numeric values are within tolerance.
 */
function numbersClose(a, b, tolerance = 0.01) {
  if (a === b) return true;
  if (typeof a !== 'number' || typeof b !== 'number') return false;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  const diff = Math.abs(a - b);
  if (diff <= tolerance) return true;
  // Relative tolerance for large numbers
  const maxAbs = Math.max(Math.abs(a), Math.abs(b));
  return maxAbs > 0 ? diff / maxAbs <= tolerance : diff <= tolerance;
}

/**
 * Deep compare two values with numeric tolerance.
 */
function valuesEqual(a, b, tolerance = 0.01) {
  if (a === b) return true;
  if (a === null || b === null) return a === b;
  if (typeof a === 'number' && typeof b === 'number') {
    return numbersClose(a, b, tolerance);
  }
  if (typeof a === 'string' && typeof b === 'string') {
    return a.trim() === b.trim();
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false;
    return a.every((v, i) => valuesEqual(v, b[i], tolerance));
  }
  return false;
}

/**
 * Sort rows by a stable key for order-insensitive comparison.
 */
function stableSort(rows) {
  return [...rows].sort((a, b) => {
    const aStr = JSON.stringify(a);
    const bStr = JSON.stringify(b);
    return aStr < bStr ? -1 : aStr > bStr ? 1 : 0;
  });
}

// ============================================================
// SQL Validator
// ============================================================

/**
 * Validate SQL execution results against a specification.
 *
 * @param {Object} spec - Validation specification:
 *   spec.type: 'sql' (default)
 *   spec.expected_columns: string[] — column names that must be present
 *   spec.expected_rows: any[][] — expected result rows
 *   spec.expected_row_count: number — exact row count
 *   spec.order_sensitive: boolean — whether row order matters (default: true)
 *   spec.numeric_tolerance: number — tolerance for numeric comparisons (default: 0.01)
 *   spec.expect_empty: boolean — expect zero rows
 *   spec.expect_error: boolean — expect an error (query should fail)
 *   spec.error_pattern: string — regex pattern that error message should match
 *
 * @param {{ columns: string[], rows: any[][], duration: number, error: string|null }} result
 * @returns {{ passed: boolean, details: string, score: number, maxScore: number }}
 */
export function validateSql(result, spec = {}) {
  const {
    expected_columns,
    expected_rows,
    expected_row_count,
    order_sensitive = true,
    numeric_tolerance = 0.01,
    expect_empty = false,
    expect_error = false,
    error_pattern,
  } = spec;

  const maxScore = 1;
  const details = [];

  // Handle error expectation
  if (expect_error) {
    if (!result.error) {
      return {
        passed: false,
        details: 'Expected an error but the query executed successfully.',
        score: 0,
        maxScore,
      };
    }
    if (error_pattern) {
      const regex = new RegExp(error_pattern, 'i');
      if (!regex.test(result.error)) {
        return {
          passed: false,
          details: `Error occurred but did not match expected pattern: ${result.error}`,
          score: 0,
          maxScore,
        };
      }
    }
    return {
      passed: true,
      details: 'Query correctly produced an error.',
      score: maxScore,
      maxScore,
    };
  }

  // If we expect an error but got success
  if (result.error) {
    return {
      passed: false,
      details: `Query error: ${result.error}`,
      score: 0,
      maxScore,
    };
  }

  // Check expected columns
  if (expected_columns && expected_columns.length > 0) {
    const resultCols = result.columns.map((c) => c.toLowerCase());
    const expectedCols = expected_columns.map((c) => c.toLowerCase());
    const missingCols = expectedCols.filter((c) => !resultCols.includes(c));
    if (missingCols.length > 0) {
      details.push(`Missing columns: ${missingCols.join(', ')}`);
    }
    const extraCols = resultCols.filter((c) => !expectedCols.includes(c));
    if (extraCols.length > 0) {
      details.push(`Extra columns: ${extraCols.join(', ')}`);
    }
    if (missingCols.length > 0 || extraCols.length > 0) {
      return {
        passed: false,
        details: details.join('; '),
        score: 0,
        maxScore,
      };
    }
  }

  // Check empty result
  if (expect_empty) {
    if (result.rows.length > 0) {
      return {
        passed: false,
        details: `Expected empty result but got ${result.rows.length} row(s).`,
        score: 0,
        maxScore,
      };
    }
    return {
      passed: true,
      details: 'Query correctly returned empty result.',
      score: maxScore,
      maxScore,
    };
  }

  // Check expected row count
  if (expected_row_count !== undefined && expected_row_count !== null) {
    if (result.rows.length !== expected_row_count) {
      return {
        passed: false,
        details: `Expected ${expected_row_count} row(s) but got ${result.rows.length}.`,
        score: 0,
        maxScore,
      };
    }
  }

  // Check expected rows
  if (expected_rows && expected_rows.length > 0) {
    if (result.rows.length !== expected_rows.length) {
      return {
        passed: false,
        details: `Expected ${expected_rows.length} row(s) but got ${result.rows.length}.`,
        score: 0,
        maxScore,
      };
    }

    let actualRows = result.rows;
    let expected = expected_rows;

    if (!order_sensitive) {
      actualRows = stableSort(actualRows);
      expected = stableSort(expected);
    }

    for (let i = 0; i < expected.length; i++) {
      const expRow = expected[i];
      const actRow = actualRows[i];
      if (!actRow) {
        return {
          passed: false,
          details: `Missing row at index ${i}.`,
          score: 0,
          maxScore,
        };
      }
      if (expRow.length !== actRow.length) {
        return {
          passed: false,
          details: `Row ${i}: expected ${expRow.length} columns but got ${actRow.length}.`,
          score: 0,
          maxScore,
        };
      }
      for (let j = 0; j < expRow.length; j++) {
        if (!valuesEqual(expRow[j], actRow[j], numeric_tolerance)) {
          return {
            passed: false,
            details: `Row ${i}, Column ${j}: expected "${expRow[j]}" but got "${actRow[j]}".`,
            score: 0,
            maxScore,
          };
        }
      }
    }
  }

  return {
    passed: true,
    details: 'All checks passed.',
    score: maxScore,
    maxScore,
  };
}

// ============================================================
// Pandas Validator
// ============================================================

/**
 * Validate Pandas execution results against a specification.
 *
 * @param {Object} spec - Validation specification:
 *   spec.type: 'pandas'
 *   spec.expected_columns: string[] — column names
 *   spec.expected_shape: [number, number] — [rows, cols]
 *   spec.expected_values: any[][] — expected DataFrame values
 *   spec.order_sensitive: boolean — row order matters (default: false)
 *   spec.numeric_tolerance: number — tolerance for numeric comparisons (default: 0.01)
 *
 * @param {{ result: string|null, dataframe: {columns: string[], rows: any[][]}|null }} executionResult
 * @returns {{ passed: boolean, details: string, score: number, maxScore: number }}
 */
export function validatePandas(executionResult, spec = {}) {
  const {
    expected_columns,
    expected_shape,
    expected_values,
    order_sensitive = false,
    numeric_tolerance = 0.01,
  } = spec;

  const maxScore = 1;

  // Check for execution errors
  if (executionResult.error) {
    return {
      passed: false,
      details: `Execution error: ${executionResult.error}`,
      score: 0,
      maxScore,
    };
  }

  // If we expect a DataFrame, check that we got one
  if (expected_columns || expected_shape || expected_values) {
    if (!executionResult.dataframe) {
      return {
        passed: false,
        details: 'Expected a DataFrame result but none was returned. Make sure your code assigns a DataFrame to a variable named `result`.',
        score: 0,
        maxScore,
      };
    }

    const { columns, rows } = executionResult.dataframe;

    // Check columns
    if (expected_columns && expected_columns.length > 0) {
      const resultCols = columns.map((c) => c.toLowerCase());
      const expectedCols = expected_columns.map((c) => c.toLowerCase());
      const missingCols = expectedCols.filter((c) => !resultCols.includes(c));
      const extraCols = resultCols.filter((c) => !expectedCols.includes(c));
      if (missingCols.length > 0 || extraCols.length > 0) {
        return {
          passed: false,
          details: [
            missingCols.length > 0 ? `Missing columns: ${missingCols.join(', ')}` : '',
            extraCols.length > 0 ? `Extra columns: ${extraCols.join(', ')}` : '',
          ].filter(Boolean).join('; '),
          score: 0,
          maxScore,
        };
      }
    }

    // Check shape
    if (expected_shape) {
      const [expectedRows, expectedCols] = expected_shape;
      if (rows.length !== expectedRows) {
        return {
          passed: false,
          details: `Expected ${expectedRows} rows but got ${rows.length}.`,
          score: 0,
          maxScore,
        };
      }
      if (columns.length !== expectedCols) {
        return {
          passed: false,
          details: `Expected ${expectedCols} columns but got ${columns.length}.`,
          score: 0,
          maxScore,
        };
      }
    }

    // Check values
    if (expected_values && expected_values.length > 0) {
      let actualRows = rows;
      let expected = expected_values;

      if (!order_sensitive) {
        actualRows = stableSort(rows);
        expected = stableSort(expected_values);
      }

      if (actualRows.length !== expected.length) {
        return {
          passed: false,
          details: `Expected ${expected.length} rows but got ${actualRows.length}.`,
          score: 0,
          maxScore,
        };
      }

      for (let i = 0; i < expected.length; i++) {
        const expRow = expected[i];
        const actRow = actualRows[i];
        if (!actRow || expRow.length !== actRow.length) {
          return {
            passed: false,
            details: `Row ${i}: column count mismatch.`,
            score: 0,
            maxScore,
          };
        }
        for (let j = 0; j < expRow.length; j++) {
          if (!valuesEqual(expRow[j], actRow[j], numeric_tolerance)) {
            return {
              passed: false,
              details: `Row ${i}, Column ${columns[j] || j}: expected "${expRow[j]}" but got "${actRow[j]}".`,
              score: 0,
              maxScore,
            };
          }
        }
      }
    }
  }

  return {
    passed: true,
    details: 'All checks passed.',
    score: maxScore,
    maxScore,
  };
}

// ============================================================
// Unified validator dispatch
// ============================================================

/**
 * Validate results for any WASM challenge type.
 *
 * @param {string} challengeType - 'sql_wasm' or 'pandas_wasm'
 * @param {Object} result - Execution result
 * @param {Object} spec - Validation specification
 * @returns {{ passed: boolean, details: string, score: number, maxScore: number }}
 */
export function validateWasmResult(challengeType, result, spec) {
  switch (challengeType) {
    case 'sql_wasm':
      return validateSql(result, spec);
    case 'pandas_wasm':
      return validatePandas(result, spec);
    default:
      return { passed: false, details: `Unknown challenge type: ${challengeType}`, score: 0, maxScore: 0 };
  }
}
