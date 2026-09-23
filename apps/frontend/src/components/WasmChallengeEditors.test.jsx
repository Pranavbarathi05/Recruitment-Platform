import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, act } from '@testing-library/react';
import SqlWasmChallenge from './SqlWasmChallenge';
import PandasWasmChallenge from './PandasWasmChallenge';
import { validateSql, validatePandas } from '../execution/validators';

// Monaco is browser-only, so the editor is captured with its props instead.
vi.mock('./CodeEditor', () => ({
  default: ({ value, language, height, options }) => (
    // Mirrors the real component's wrapper, which sizes itself with h-full.
    <div className="code-editor-container h-full">
      <textarea
        data-testid="code-editor"
        data-language={language}
        data-height={height}
        data-readonly={String(!!(options && options.readOnly))}
        readOnly
        value={value}
      />
    </div>
  ),
}));

const initialize = vi.fn();
const dispose = vi.fn(async () => {});

vi.mock('../execution/sqlWasmRunner', () => ({
  SqlWasmRunner: class {
    initialize(...args) {
      return initialize(...args);
    }
    execute = vi.fn(async () => ({ columns: [], rows: [], error: null }));
    dispose(...args) {
      return dispose(...args);
    }
  },
}));

vi.mock('../execution/pandasWasmRunner', () => ({
  PandasWasmRunner: class {
    initialize(...args) {
      return initialize(...args);
    }
    execute = vi.fn(async () => ({ dataframe: { columns: [], rows: [] } }));
    dispose(...args) {
      return dispose(...args);
    }
  },
}));

vi.mock('../execution/validators', () => ({
  validateSql: vi.fn(() => ({ passed: true, details: 'All checks passed.' })),
  validatePandas: vi.fn(() => ({ passed: true, details: 'All checks passed.' })),
}));

// The canonical shapes stored in hands_on_questions.dataset_json — arrays of
// table/dataframe specs, NOT a dictionary.
const SQL_DATASET = [
  {
    table: 'employees',
    columns: ['id', 'name', 'department', 'salary'],
    rows: [[1, 'Alice', 'Engineering', 95000]],
  },
];

const PANDAS_DATASET = [
  {
    name: 'df',
    columns: ['id', 'name', 'department', 'salary'],
    data: [[1, 'Alice', 'Engineering', 95000]],
  },
];

const SQL_STARTER = 'SELECT department, AVG(salary) AS avg_salary\nFROM employees\nGROUP BY department;';
const PANDAS_STARTER = 'import pandas as pd\n\nresult = df.groupby("department").size()';

const SQL_PROBLEM = {
  id: 'sql-1',
  title: 'Employee Analytics — SQL',
  difficulty: 'easy',
  points: 100,
  challenge_type: 'sql_wasm',
  schema_sql: 'CREATE TABLE employees (id INTEGER, name VARCHAR, department VARCHAR, salary INTEGER);',
  dataset_json: SQL_DATASET,
  starter_code: SQL_STARTER,
  validation_spec: { expected_columns: ['department', 'avg_salary'] },
};

const PANDAS_PROBLEM = {
  id: 'pandas-1',
  title: 'Employee Analytics — Pandas',
  difficulty: 'easy',
  points: 100,
  challenge_type: 'pandas_wasm',
  dataset_json: PANDAS_DATASET,
  starter_code: PANDAS_STARTER,
  validation_spec: { expected_columns: ['department', 'headcount'] },
};

beforeEach(() => {
  cleanup();
  initialize.mockReset();
  initialize.mockResolvedValue(undefined);
  dispose.mockClear();
  validateSql.mockClear();
  validatePandas.mockClear();
  validateSql.mockReturnValue({ passed: true, details: 'All checks passed.' });
  validatePandas.mockReturnValue({ passed: true, details: 'All checks passed.' });
});

/**
 * Run then Submit, as a candidate would, and return what the challenge
 * reported to the workspace (the payload that reaches the backend).
 */
async function runAndSubmit() {
  const submitRun = screen.getByRole('button', { name: /run/i });
  await act(async () => { fireEvent.click(submitRun); });
  const submit = await screen.findByRole('button', { name: /submit/i });
  await act(async () => { fireEvent.click(submit); });
}

afterEach(() => {
  vi.restoreAllMocks();
});

/**
 * The editor only has a usable height when every ancestor in the chain is
 * sized (`h-full` resolves against a definite parent). Asserting the contract
 * here guards the markup that the assessment shell now provides a definite
 * height for.
 */
function assertEditorHeightContract(container) {
  const editor = container.querySelector('.code-editor-container');
  expect(editor).not.toBeNull();
  const wrapper = editor.parentElement;
  expect(wrapper.className).toMatch(/flex-1/);
  expect(wrapper.className).toMatch(/min-h-0/);
  const root = wrapper.parentElement;
  expect(root.className).toMatch(/h-full/);
  expect(root.className).toMatch(/flex-col/);
}

describe('SqlWasmChallenge', () => {
  it('mounts the editor with the starter SQL and no zero-height wrapper', async () => {
    const { container } = render(
      <SqlWasmChallenge problem={SQL_PROBLEM} onSubmit={vi.fn()} submitted={false} />
    );

    const editor = await screen.findByTestId('code-editor');
    expect(editor).toHaveValue(SQL_STARTER);
    expect(editor).toHaveAttribute('data-language', 'sql');
    expect(editor).toHaveAttribute('data-height', '100%');
    expect(editor).toHaveAttribute('data-readonly', 'false');
    assertEditorHeightContract(container);
  });

  it('passes the canonical array dataset (and schema) to the runner untouched', async () => {
    render(<SqlWasmChallenge problem={SQL_PROBLEM} onSubmit={vi.fn()} submitted={false} />);
    await screen.findByTestId('code-editor');

    expect(initialize).toHaveBeenCalledTimes(1);
    expect(initialize.mock.calls[0][0]).toEqual({
      schema: SQL_PROBLEM.schema_sql,
      dataset: SQL_DATASET,
    });
    expect(Array.isArray(initialize.mock.calls[0][0].dataset)).toBe(true);
  });

  it('makes the editor read-only once the challenge is submitted', async () => {
    render(<SqlWasmChallenge problem={SQL_PROBLEM} onSubmit={vi.fn()} submitted />);
    expect(await screen.findByTestId('code-editor')).toHaveAttribute('data-readonly', 'true');
  });

  it('reports the validator verdict — never a score and never a flag', async () => {
    const onSubmit = vi.fn();
    render(<SqlWasmChallenge problem={SQL_PROBLEM} onSubmit={onSubmit} submitted={false} />);
    await screen.findByTestId('code-editor');

    await runAndSubmit();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      questionId: SQL_PROBLEM.id,
      submittedCode: SQL_STARTER,
      validationPassed: true,
    });
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).not.toHaveProperty('clientScore');
    expect(payload).not.toHaveProperty('score');
    expect(payload).not.toHaveProperty('submittedFlag');
  });

  it('reports a failing validation as validationPassed: false (backend scores it)', async () => {
    validateSql.mockReturnValue({ passed: false, details: 'Missing columns: avg_salary' });
    const onSubmit = vi.fn();
    render(<SqlWasmChallenge problem={SQL_PROBLEM} onSubmit={onSubmit} submitted={false} />);
    await screen.findByTestId('code-editor');

    await runAndSubmit();

    expect(onSubmit).toHaveBeenCalledWith({
      questionId: SQL_PROBLEM.id,
      submittedCode: SQL_STARTER,
      validationPassed: false,
    });
  });
});

describe('PandasWasmChallenge', () => {
  it('mounts the editor with the starter Python and no zero-height wrapper', async () => {
    const { container } = render(
      <PandasWasmChallenge problem={PANDAS_PROBLEM} onSubmit={vi.fn()} submitted={false} />
    );

    const editor = await screen.findByTestId('code-editor');
    expect(editor).toHaveValue(PANDAS_STARTER);
    expect(editor).toHaveAttribute('data-language', 'python');
    expect(editor).toHaveAttribute('data-height', '100%');
    expect(editor).toHaveAttribute('data-readonly', 'false');
    assertEditorHeightContract(container);
  });

  it('passes the canonical array dataset to the runner untouched', async () => {
    render(<PandasWasmChallenge problem={PANDAS_PROBLEM} onSubmit={vi.fn()} submitted={false} />);
    await screen.findByTestId('code-editor');

    expect(initialize).toHaveBeenCalledTimes(1);
    expect(initialize.mock.calls[0][0]).toEqual({ dataset: PANDAS_DATASET });
    expect(Array.isArray(initialize.mock.calls[0][0].dataset)).toBe(true);
  });

  it('makes the editor read-only once the challenge is submitted', async () => {
    render(<PandasWasmChallenge problem={PANDAS_PROBLEM} onSubmit={vi.fn()} submitted />);
    expect(await screen.findByTestId('code-editor')).toHaveAttribute('data-readonly', 'true');
  });

  it('reports the validator verdict — never a score and never a flag', async () => {
    const onSubmit = vi.fn();
    render(<PandasWasmChallenge problem={PANDAS_PROBLEM} onSubmit={onSubmit} submitted={false} />);
    await screen.findByTestId('code-editor');

    await runAndSubmit();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      questionId: PANDAS_PROBLEM.id,
      submittedCode: PANDAS_STARTER,
      validationPassed: true,
    });
    const payload = onSubmit.mock.calls[0][0];
    expect(payload).not.toHaveProperty('clientScore');
    expect(payload).not.toHaveProperty('score');
  });

  it('reports a failing validation as validationPassed: false (backend scores it)', async () => {
    validatePandas.mockReturnValue({ passed: false, details: 'Expected 3 rows but got 1.' });
    const onSubmit = vi.fn();
    render(<PandasWasmChallenge problem={PANDAS_PROBLEM} onSubmit={onSubmit} submitted={false} />);
    await screen.findByTestId('code-editor');

    await runAndSubmit();

    expect(onSubmit).toHaveBeenCalledWith({
      questionId: PANDAS_PROBLEM.id,
      submittedCode: PANDAS_STARTER,
      validationPassed: false,
    });
  });
});
