import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';
import { runCodeLocally } from '../execution/runner';

vi.mock('../execution/runner', () => ({
  runCodeLocally: vi.fn(),
  isClientRunnable: (language) => language === 'python3',
}));

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

vi.mock('../components/CodeEditor', () => ({
  default: () => <textarea data-testid="code-editor" readOnly />,
}));

const FUTURE = new Date(Date.now() + 3600_000).toISOString();

const PUBLIC_TEST_CASES = [
  { id: 'tc-1', arguments: [2], expected_output: 4 },
  { id: 'tc-2', arguments: [3], expected_output: 9 },
];

const PROBLEM_ONE = {
  id: 'prob-1',
  title: 'Square It',
  difficulty: 'easy',
  points: 10,
  description: 'Return n squared.',
  function_name: 'solve',
  class_name: null,
  supported_languages: ['python3', 'cpp', 'java'],
  time_limit_ms: 2000,
  test_cases: PUBLIC_TEST_CASES,
};

const PROBLEM_TWO = {
  id: 'prob-2',
  title: 'Double It',
  difficulty: 'easy',
  points: 10,
  description: 'Return n doubled.',
  function_name: 'solve',
  class_name: null,
  supported_languages: ['python3'],
  time_limit_ms: 2000,
  test_cases: [{ id: 'tc-3', arguments: [4], expected_output: 8 }],
};

function mockFetchFor(problems) {
  return vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      return {
        ok: true,
        json: async () => ({ questions: [], answers: {}, expires_at: FUTURE }),
      };
    }
    if (u.includes('/coding/attempt/attempt-1/problems')) {
      return {
        ok: true,
        json: async () => ({ problems, expires_at: FUTURE }),
      };
    }
    return { ok: true, json: async () => ({}) };
  });
}

function renderWorkspace(problems = [PROBLEM_ONE]) {
  globalThis.fetch = mockFetchFor(problems);
  return render(
    <MemoryRouter initialEntries={['/assessment/attempt-1']}>
      <Routes>
        <Route path="/assessment/:attemptId" element={<MCQTest />} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  cleanup();
  runCodeLocally.mockReset();
});

describe('Coding Run — client-side execution', () => {
  it('clicking Run executes locally and does not call the server run endpoint', async () => {
    runCodeLocally.mockResolvedValue({
      all_passed: true,
      results: [
        { id: 'tc-1', passed: true, status: 'passed', expected_output: 4, actual_output: 4 },
        { id: 'tc-2', passed: true, status: 'passed', expected_output: 9, actual_output: 9 },
      ],
      stdout: '',
    });

    renderWorkspace();

    const runButton = await screen.findByRole('button', { name: /run code/i });
    fireEvent.click(runButton);

    expect(await screen.findByText(/All Passed ✓/)).toBeInTheDocument();

    expect(runCodeLocally).toHaveBeenCalledTimes(1);
    expect(runCodeLocally).toHaveBeenCalledWith(
      expect.objectContaining({
        language: 'python3',
        sourceCode: expect.any(String),
        testCases: PUBLIC_TEST_CASES,
        functionName: 'solve',
        className: null,
        timeLimitMs: 2000,
      })
    );

    const runFetches = globalThis.fetch.mock.calls.filter(([url]) =>
      String(url).includes('/coding/attempt/attempt-1/run')
    );
    expect(runFetches).toHaveLength(0);
  });

  it('Run never invokes the submission flow', async () => {
    runCodeLocally.mockResolvedValue({ all_passed: true, results: [] });
    renderWorkspace();

    const runButton = await screen.findByRole('button', { name: /run code/i });
    fireEvent.click(runButton);

    await screen.findByText(/Test Results/);

    const submitFetches = globalThis.fetch.mock.calls.filter(([url]) =>
      String(url).includes('/coding/attempt/attempt-1/submit')
    );
    expect(submitFetches).toHaveLength(0);
  });

  it('renders passed, wrong answer, compile error, runtime error, and timeout results', async () => {
    runCodeLocally.mockResolvedValue({
      all_passed: false,
      stdout: 'candidate printed this',
      results: [
        { id: 'a', passed: true, status: 'passed', expected_output: 1, actual_output: 1, execution_time_ms: 3 },
        { id: 'b', passed: false, status: 'failed', expected_output: 'yes', actual_output: 'no', input: 'q1' },
        { id: 'c', passed: false, status: 'compile_error', expected_output: '', actual_output: '', stderr: 'SyntaxError: bad syntax' },
        { id: 'd', passed: false, status: 'runtime_error', expected_output: '', actual_output: '', stderr: 'ZeroDivisionError: division by zero' },
        { id: 'e', passed: false, status: 'timeout', expected_output: '', actual_output: '', execution_time_ms: 2000 },
      ],
    });

    renderWorkspace();
    fireEvent.click(await screen.findByRole('button', { name: /run code/i }));

    expect(await screen.findByText(/candidate printed this/)).toBeInTheDocument();
    expect(screen.getAllByText('Passed').length).toBeGreaterThan(0);
    expect(screen.getByText('Wrong Answer')).toBeInTheDocument();
    expect(screen.getByText('Expected:')).toBeInTheDocument();
    expect(screen.getByText('yes')).toBeInTheDocument();
    expect(screen.getByText('Got:')).toBeInTheDocument();
    expect(screen.getByText('no')).toBeInTheDocument();
    expect(screen.getAllByText('Input:').length).toBeGreaterThan(0);
    expect(screen.getByText('q1')).toBeInTheDocument();
    expect(screen.getByText('Compilation Error')).toBeInTheDocument();
    expect(screen.getByText(/SyntaxError: bad syntax/)).toBeInTheDocument();
    expect(screen.getByText('Runtime Error')).toBeInTheDocument();
    expect(screen.getByText(/ZeroDivisionError: division by zero/)).toBeInTheDocument();
    expect(screen.getByText('Time Limit Exceeded')).toBeInTheDocument();
  });

  it('renders top-level compilation diagnostics from a syntax error', async () => {
    runCodeLocally.mockResolvedValue({
      all_passed: false,
      results: [
        { id: 'tc-1', passed: false, status: 'compile_error', expected_output: 4, actual_output: '', stderr: 'line 1: SyntaxError' },
      ],
      compilation_error: 'Traceback ...\nSyntaxError: invalid syntax',
      stdout: '',
    });

    renderWorkspace();
    fireEvent.click(await screen.findByRole('button', { name: /run code/i }));

    expect(await screen.findByText(/invalid syntax/)).toBeInTheDocument();
  });

  it('shows an error message when the local run fails', async () => {
    runCodeLocally.mockRejectedValue(new Error('Could not initialize the in-browser Python runtime'));

    renderWorkspace();
    fireEvent.click(await screen.findByRole('button', { name: /run code/i }));

    expect(await screen.findByText(/Could not initialize the in-browser Python runtime/)).toBeInTheDocument();
  });

  it('switching problems clears stale results', async () => {
    runCodeLocally.mockResolvedValue({
      all_passed: false,
      results: [{ id: 'tc-1', passed: false, status: 'failed', expected_output: 4, actual_output: 5 }],
    });

    renderWorkspace([PROBLEM_ONE, PROBLEM_TWO]);
    fireEvent.click(await screen.findByRole('button', { name: /run code/i }));
    expect(await screen.findByText(/Test Results/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(screen.queryByText(/Test Results/)).not.toBeInTheDocument();
  });

  it('only sends the visible (public) test cases to the executor', async () => {
    runCodeLocally.mockResolvedValue({ all_passed: true, results: [] });
    renderWorkspace();

    fireEvent.click(await screen.findByRole('button', { name: /run code/i }));
    await screen.findByText(/Test Results/);

    const payload = runCodeLocally.mock.calls[0][0];
    expect(payload.testCases).toEqual(PUBLIC_TEST_CASES);
    // None of the sent test cases are hidden/private.
    expect(payload.testCases.every((tc) => tc.is_public !== false)).toBe(true);
    // A hidden test (which the backend never includes in problem.test_cases)
    // must never reach the client executor.
    const HIDDEN = { id: 'hidden-1', arguments: [99], expected_output: 9801, is_public: false };
    expect(payload.testCases.some((tc) => tc.id === HIDDEN.id)).toBe(false);
  });
});