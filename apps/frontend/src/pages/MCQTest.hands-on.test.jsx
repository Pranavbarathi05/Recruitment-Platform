import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

// Monaco is browser-only (it touches DOM APIs at import time) and cannot run in
// jsdom, so the editor is stubbed — same convention as MCQTest.test.jsx. These
// tests cover the hands-on section, never the editor itself.
vi.mock('../components/CodeEditor', () => ({
  default: ({ value }) => <textarea data-testid="code-editor" readOnly value={value} />,
}));

// The WASM challenge editors boot a real WASM runtime; the workspace behavior
// under test here is the header/navigation around them, so they are stubbed
// (same convention as MCQTest.wasm-submit.test.jsx).
vi.mock('../components/SqlWasmChallenge', () => ({
  default: ({ problem }) => <div data-testid="sql-wasm-stub">{problem.id}</div>,
}));
vi.mock('../components/PandasWasmChallenge', () => ({
  default: ({ problem }) => <div data-testid="pandas-wasm-stub">{problem.id}</div>,
}));

const FUTURE = new Date(Date.now() + 3600_000).toISOString();

const HANDS_ON_CHALLENGE = {
  id: 'hands-1',
  title: 'SQL Injection — Employee Portal',
  description: 'Gain access to the administrator account and retrieve the protected flag.',
  difficulty: 'medium',
  points: 100,
  challenge_type: 'sql_injection_employee_portal',
  challenge_url: 'http://127.0.0.1:8080',
  // NOTE: no expected_flag here — candidate APIs must never carry it.
};

function mockFetch({ withHandsOn = true, priorResult = null, putStatus = 200, handsOn = null } = {}) {
  const challenges = handsOn ?? (withHandsOn ? [HANDS_ON_CHALLENGE] : []);
  const fetchMock = vi.fn(async (url, options) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          questions: [
            { id: 'mcq-1', question_text: 'What is 2 + 2?', options: ['3', '4'] },
          ],
          answers: { 'mcq-1': '4' },
          descriptive_questions: [],
          descriptive_answers: {},
          hands_on_questions: challenges,
          // Candidate results carry evidence only — never verified/score.
          hands_on_results: priorResult
            ? [{
                question_id: priorResult.question_id,
                submitted_input: priorResult.submitted_input,
                submitted_flag: priorResult.submitted_flag,
                started_at: priorResult.started_at ?? null,
                completed_at: priorResult.completed_at ?? null,
              }]
            : [],
          total_hands_on_questions: challenges.length,
          expires_at: FUTURE,
        }),
      };
    }
    if (u.includes('/hands-on') && (options?.method === 'PUT' || options?.method === 'put')) {
      fetchMock.putCalls.push({ url: String(url), body: JSON.parse(options.body) });
      return {
        ok: putStatus === 200,
        status: putStatus,
        json: async () =>
          putStatus === 409
            ? { detail: 'Challenge has already been submitted' }
            : { status: 'submitted' },
      };
    }
    return { ok: true, json: async () => ({}), status: 200 };
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

async function openHandsOnTab() {
  fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));
  await screen.findByText('SQL Injection — Employee Portal');
}

function fillAndSubmit({ sql = "' OR 1=1 --", flag = 'FLAG{correct}' } = {}) {
  fireEvent.change(screen.getByPlaceholderText(/Paste the SQL input/i), {
    target: { value: sql },
  });
  fireEvent.change(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i), {
    target: { value: flag },
  });
  fireEvent.click(screen.getByRole('button', { name: /Submit Challenge/i }));
}

beforeEach(() => {
  cleanup();
});

describe('MCQTest — Hands-On section', () => {
  it('shows the Hands-On tab when the questions endpoint returns hands_on_questions', async () => {
    renderWorkspace(mockFetch({ withHandsOn: true }));

    const tab = await screen.findByRole('button', { name: /Hands-On \(1\)/i });
    expect(tab).toBeInTheDocument();
  });

  it('hides the Hands-On tab when no challenges are returned (count = 0 behaviour)', async () => {
    renderWorkspace(mockFetch({ withHandsOn: false }));

    await screen.findByRole('button', { name: /MCQ \(1\)/i });
    expect(screen.queryByRole('button', { name: /Hands-On/i })).not.toBeInTheDocument();
  });

  it('renders challenge metadata without ever exposing an expected flag', async () => {
    renderWorkspace(mockFetch({ withHandsOn: true }));

    await openHandsOnTab();

    expect(screen.getByText(/Gain access to the administrator account/i)).toBeInTheDocument();
    // Candidate-facing header: internal metadata (difficulty, points, type
    // labels) must never be shown — only question information.
    expect(screen.queryByText('100 pts')).not.toBeInTheDocument();
    expect(screen.queryByText('medium')).not.toBeInTheDocument();

    const iframe = screen.getByTitle('Hands-on challenge');
    expect(iframe).toHaveAttribute('src', '/challenge/');

    // The expected flag must never be rendered anywhere in the workspace.
    const bodyHtml = document.body.innerHTML;
    expect(bodyHtml).not.toContain('expected_flag');
  });

  it('provides exactly two submission inputs, sends both once, and locks after submit', async () => {
    const fetchMock = mockFetch({ withHandsOn: true });
    renderWorkspace(fetchMock);

    await openHandsOnTab();

    const sqlBox = await screen.findByPlaceholderText(/Paste the SQL input/i);
    const flagBox = screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i);
    expect(sqlBox.tagName).toBe('TEXTAREA');
    expect(flagBox.tagName).toBe('INPUT');

    fillAndSubmit({ sql: "' OR 1=1 --", flag: 'FLAG{correct}' });

    // Neutral confirmation — NO correctness, NO score
    expect(await screen.findByText(/Challenge submitted\. Your response has been recorded\./i)).toBeInTheDocument();
    expect(screen.queryByText(/✓ Correct/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/✗ Incorrect/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();

    const putCalls = fetchMock.putCalls;
    expect(putCalls).toHaveLength(1);
    expect(putCalls[0].body).toEqual({
      question_id: 'hands-1',
      submitted_input: "' OR 1=1 --",
      submitted_flag: 'FLAG{correct}',
    });

    // Fields are locked after submission
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toBeDisabled();
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Submit Challenge/i })).not.toBeInTheDocument();

    // A second click attempt is impossible (button gone); a second programmatic
    // submit does NOT send another PUT.
    const form = sqlBox.closest('form');
    fireEvent.submit(form);
    expect(fetchMock.putCalls).toHaveLength(1);
  });

  it('keeps the neutral confirmation identical for a wrong flag (no outcome leak)', async () => {
    renderWorkspace(mockFetch({ withHandsOn: true }));

    await openHandsOnTab();

    fillAndSubmit({ flag: 'FLAG{wrong}' });

    expect(await screen.findByText(/Challenge submitted\. Your response has been recorded\./i)).toBeInTheDocument();
    expect(screen.queryByText(/✗ Incorrect flag — score 0/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toBeDisabled();
  });

  it('reflects a previously submitted result after reload as read-only with no outcome', async () => {
    renderWorkspace(mockFetch({
      withHandsOn: true,
      priorResult: {
        question_id: 'hands-1',
        submitted_input: "' OR 1=1 --",
        submitted_flag: 'FLAG{correct}',
        // verified/score intentionally absent — the API no longer returns them
      },
    }));

    await openHandsOnTab();

    expect(screen.getByText('Submitted')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue("' OR 1=1 --");
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toHaveValue('FLAG{correct}');
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toBeDisabled();
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Submit Challenge/i })).not.toBeInTheDocument();
    // No outcome indicators anywhere
    expect(screen.queryByText(/✓ Completed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/✓ Correct/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Attempted/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
  });

  it('locks the form with the neutral confirmation when the backend answers 409', async () => {
    // A result already exists server-side (other tab / direct API call) but
    // this tab does not know it: the PUT is rejected with 409 Conflict. The
    // UI must lock the form and show the neutral confirmation — never an
    // error implying a retry is possible, and never any outcome.
    const fetchMock = mockFetch({ withHandsOn: true, putStatus: 409 });
    renderWorkspace(fetchMock);

    await openHandsOnTab();

    fillAndSubmit({ flag: 'FLAG{anything}' });

    expect(await screen.findByText(/Challenge submitted\. Your response has been recorded\./i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toBeDisabled();
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Submit Challenge/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/✓ Correct/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/score/i)).not.toBeInTheDocument();
    expect(fetchMock.putCalls).toHaveLength(1);
  });
});

const SECOND_CHALLENGE = {
  ...HANDS_ON_CHALLENGE,
  id: 'hands-2',
  title: 'Second Challenge — DevOps',
  description: 'Deploy the service and verify the rollout.',
};

async function openTwoChallengeTab() {
  fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(2\)/i }));
  await screen.findByText('SQL Injection — Employee Portal');
}

describe('MCQTest — multi-question Hands-On navigation', () => {
  it('renders both challenges and switches between them with the nav controls', async () => {
    renderWorkspace(mockFetch({ handsOn: [HANDS_ON_CHALLENGE, SECOND_CHALLENGE] }));
    await openTwoChallengeTab();

    expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
    expect(screen.queryByText('Second Challenge — DevOps')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));
    expect(await screen.findByText('Second Challenge — DevOps')).toBeInTheDocument();
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    expect(screen.queryByText('SQL Injection — Employee Portal')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Previous question' }));
    expect(await screen.findByText('SQL Injection — Employee Portal')).toBeInTheDocument();
    expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
  });

  it('supports direct selection through the numbered question selector', async () => {
    renderWorkspace(mockFetch({ handsOn: [HANDS_ON_CHALLENGE, SECOND_CHALLENGE] }));
    await openTwoChallengeTab();

    fireEvent.click(screen.getByRole('button', { name: 'Question 2' }));
    expect(await screen.findByText('Second Challenge — DevOps')).toBeInTheDocument();

    const active = screen.getByRole('button', { name: 'Question 2' });
    expect(active).toHaveAttribute('aria-current', 'true');
  });

  it("keeps each question's evidence/flag drafts independent while switching", async () => {
    renderWorkspace(mockFetch({ handsOn: [HANDS_ON_CHALLENGE, SECOND_CHALLENGE] }));
    await openTwoChallengeTab();

    fireEvent.change(screen.getByPlaceholderText(/Paste the SQL input/i), {
      target: { value: 'first payload' },
    });
    fireEvent.change(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i), {
      target: { value: 'FLAG{one}' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await screen.findByText('Second Challenge — DevOps');

    // Question 2 starts empty — question 1's draft must not leak into it.
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue('');
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toHaveValue('');

    fireEvent.change(screen.getByPlaceholderText(/Paste the SQL input/i), {
      target: { value: 'second payload' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Previous question' }));
    await screen.findByText('SQL Injection — Employee Portal');
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue('first payload');
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toHaveValue('FLAG{one}');

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await screen.findByText('Second Challenge — DevOps');
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue('second payload');
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toHaveValue('');
  });

  it('locks only the challenge that was already submitted', async () => {
    renderWorkspace(mockFetch({
      handsOn: [HANDS_ON_CHALLENGE, SECOND_CHALLENGE],
      priorResult: {
        question_id: 'hands-1',
        submitted_input: 'saved input',
        submitted_flag: 'FLAG{done}',
      },
    }));
    await openTwoChallengeTab();

    expect(screen.getByText('Submitted')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue('saved input');
    expect(screen.queryByRole('button', { name: /Submit Challenge/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next question' }));
    await screen.findByText('Second Challenge — DevOps');
    // Question 2 is untouched: no Submitted badge, submit still available.
    expect(screen.queryByText('Submitted')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Submit Challenge/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue('');
  });
});

describe('MCQTest — Hands-On header shows only question information', () => {
  for (const type of ['sql_wasm', 'pandas_wasm']) {
    it(`hides difficulty, points and runtime labels for ${type}`, async () => {
      const challenge = {
        ...HANDS_ON_CHALLENGE,
        id: `hands-${type}`,
        challenge_type: type,
        difficulty: 'easy',
        points: 100,
        title: 'Employee Analytics',
        description: 'Write a query to calculate the average salary by department.',
      };
      renderWorkspace(mockFetch({ handsOn: [challenge] }));

      fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));
      await screen.findByText('Employee Analytics');

      expect(screen.getByText(/Write a query to calculate the average salary/i)).toBeInTheDocument();
      expect(screen.queryByText('easy')).not.toBeInTheDocument();
      expect(screen.queryByText('100 pts')).not.toBeInTheDocument();
      expect(screen.queryByText('10 pts')).not.toBeInTheDocument();
      expect(screen.queryByText('SQL WASM')).not.toBeInTheDocument();
      expect(screen.queryByText('Pandas WASM')).not.toBeInTheDocument();
    });
  }
});
