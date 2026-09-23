import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

vi.mock('../components/CodeEditor', () => ({
  default: ({ value }) => <textarea data-testid="code-editor" readOnly value={value} />,
}));

// The WASM challenges load DuckDB/Pyodide; the workspace-level plumbing under
// test is what they report on submit, so they are stubbed with a button that
// reports exactly what the real components report.
vi.mock('../components/SqlWasmChallenge', () => ({
  default: ({ problem, onSubmit }) => (
    <button
      type="button"
      onClick={() => onSubmit({
        questionId: problem.id,
        submittedCode: 'SELECT department FROM employees;',
        validationPassed: globalThis.__wasmVerdict,
      })}
    >
      Submit SQL WASM
    </button>
  ),
}));

vi.mock('../components/PandasWasmChallenge', () => ({
  default: ({ problem, onSubmit }) => (
    <button
      type="button"
      onClick={() => onSubmit({
        questionId: problem.id,
        submittedCode: 'result = df.groupby("department").size()',
        validationPassed: globalThis.__wasmVerdict,
      })}
    >
      Submit Pandas WASM
    </button>
  ),
}));

const FUTURE = new Date(Date.now() + 3600_000).toISOString();

function challenge(type) {
  return {
    id: `hands-${type}`,
    title: type === 'sql_wasm' ? 'Employee Analytics — SQL' : 'Employee Analytics — Pandas',
    description: 'Solve it.',
    difficulty: 'easy',
    points: 100,
    challenge_type: type,
    schema_sql: null,
    dataset_json: [{ table: 'employees', columns: ['id'], rows: [[1]] }],
    starter_code: 'starter',
    validation_spec: {},
  };
}

function mockFetch({ challengeType, putStatus = 200 }) {
  const fetchMock = vi.fn(async (url, options) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          questions: [],
          answers: {},
          descriptive_questions: [],
          descriptive_answers: {},
          hands_on_questions: [challenge(challengeType)],
          hands_on_results: [],
          total_hands_on_questions: 1,
          expires_at: FUTURE,
        }),
      };
    }
    if (u.includes('/hands-on') && options?.method === 'PUT') {
      fetchMock.putCalls.push(JSON.parse(options.body));
      return {
        ok: putStatus === 200,
        status: putStatus,
        json: async () => (putStatus === 200 ? { status: 'submitted' } : { detail: 'nope' }),
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
  fetchMock.putCalls = [];
  return fetchMock;
}

function renderWorkspace(fetchMock) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={['/assessment/attempt-1']}>
      <Routes>
        <Route path="/assessment/:attemptId" element={<MCQTest />} />
      </Routes>
    </MemoryRouter>
  );
}

async function submitWasmChallenge(label) {
  fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));
  const submit = await screen.findByRole('button', { name: label });
  await act(async () => { fireEvent.click(submit); });
}

beforeEach(() => {
  cleanup();
  globalThis.__wasmVerdict = true;
});

describe('MCQTest — WASM hands-on submission payload', () => {
  it('sends a sql_wasm verdict and its code — no flag, no client score', async () => {
    const fetchMock = mockFetch({ challengeType: 'sql_wasm' });
    renderWorkspace(fetchMock);

    await submitWasmChallenge('Submit SQL WASM');

    expect(fetchMock.putCalls).toHaveLength(1);
    const body = fetchMock.putCalls[0];
    expect(body).toEqual({
      question_id: 'hands-sql_wasm',
      submitted_input: 'SELECT department FROM employees;',
      submitted_flag: '',
      validation_passed: true,
      submitted_code: 'SELECT department FROM employees;',
    });
    // The browser never reports points; the backend awards them.
    expect(body).not.toHaveProperty('client_score');
    expect(body).not.toHaveProperty('score');
  });

  it('sends a failing sql_wasm verdict as validation_passed: false', async () => {
    globalThis.__wasmVerdict = false;
    const fetchMock = mockFetch({ challengeType: 'sql_wasm' });
    renderWorkspace(fetchMock);

    await submitWasmChallenge('Submit SQL WASM');

    expect(fetchMock.putCalls[0].validation_passed).toBe(false);
    expect(fetchMock.putCalls[0].submitted_flag).toBe('');
  });

  it('sends a pandas_wasm verdict and its code', async () => {
    const fetchMock = mockFetch({ challengeType: 'pandas_wasm' });
    renderWorkspace(fetchMock);

    await submitWasmChallenge('Submit Pandas WASM');

    expect(fetchMock.putCalls[0]).toEqual({
      question_id: 'hands-pandas_wasm',
      submitted_input: 'result = df.groupby("department").size()',
      submitted_flag: '',
      validation_passed: true,
      submitted_code: 'result = df.groupby("department").size()',
    });
  });

  it('marks the challenge submitted after a successful WASM PUT', async () => {
    const fetchMock = mockFetch({ challengeType: 'pandas_wasm' });
    renderWorkspace(fetchMock);

    await submitWasmChallenge('Submit Pandas WASM');

    expect(await screen.findByText('Submitted')).toBeInTheDocument();
  });
});
