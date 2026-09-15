import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
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

function mockFetch({ withHandsOn = true, priorResult = null } = {}) {
  return vi.fn(async (url, options) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      return {
        ok: true,
        json: async () => ({
          questions: [
            { id: 'mcq-1', question_text: 'What is 2 + 2?', options: ['3', '4'] },
          ],
          answers: { 'mcq-1': '4' },
          descriptive_questions: [],
          descriptive_answers: {},
          hands_on_questions: withHandsOn ? [HANDS_ON_CHALLENGE] : [],
          hands_on_results: priorResult ? [priorResult] : [],
          total_hands_on_questions: withHandsOn ? 1 : 0,
          expires_at: FUTURE,
        }),
      };
    }
    if (u.includes('/hands-on') && (options?.method === 'PUT' || options?.method === 'put')) {
      const body = JSON.parse(options.body);
      return {
        ok: true,
        json: async () => ({
          status: 'saved',
          verified: body.submitted_flag === 'FLAG{correct}',
          score: body.submitted_flag === 'FLAG{correct}' ? 100 : 0,
          points: 100,
        }),
      };
    }
    return { ok: true, json: async () => ({}) };
  });
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

    fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));

    expect(await screen.findByText('SQL Injection — Employee Portal')).toBeInTheDocument();
    expect(screen.getByText(/Gain access to the administrator account/i)).toBeInTheDocument();
    expect(screen.getByText('100 pts')).toBeInTheDocument();

    const iframe = screen.getByTitle('Hands-on challenge');
    expect(iframe).toHaveAttribute('src', 'http://127.0.0.1:8080');

    // The expected flag must never be rendered anywhere in the workspace.
    const bodyHtml = document.body.innerHTML;
    expect(bodyHtml).not.toContain('expected_flag');
  });

  it('provides exactly two submission inputs and submits both to the backend', async () => {
    const fetchMock = mockFetch({ withHandsOn: true });
    renderWorkspace(fetchMock);

    fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));

    const sqlBox = await screen.findByPlaceholderText(/Paste the SQL input/i);
    const flagBox = screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i);
    expect(sqlBox.tagName).toBe('TEXTAREA');
    expect(flagBox.tagName).toBe('INPUT');

    fireEvent.change(sqlBox, { target: { value: "' OR 1=1 --" } });
    fireEvent.change(flagBox, { target: { value: 'FLAG{correct}' } });
    fireEvent.click(screen.getByRole('button', { name: /Submit Challenge/i }));

    expect(await screen.findByText(/✓ Correct — score 100 \/ 100/i)).toBeInTheDocument();

    const putCall = fetchMock.mock.calls.find(
      ([u, o]) => String(u).includes('/hands-on') && o?.method === 'PUT'
    );
    expect(putCall).toBeTruthy();
    const sent = JSON.parse(putCall[1].body);
    expect(sent).toEqual({
      question_id: 'hands-1',
      submitted_input: "' OR 1=1 --",
      submitted_flag: 'FLAG{correct}',
    });
  });

  it('shows a zero-score failure message for an incorrect flag and keeps the evidence text', async () => {
    renderWorkspace(mockFetch({ withHandsOn: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));

    const sqlBox = await screen.findByPlaceholderText(/Paste the SQL input/i);
    const flagBox = screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i);
    fireEvent.change(sqlBox, { target: { value: "' OR 1=1 --" } });
    fireEvent.change(flagBox, { target: { value: 'FLAG{wrong}' } });
    fireEvent.click(screen.getByRole('button', { name: /Submit Challenge/i }));

    expect(await screen.findByText(/✗ Incorrect flag — score 0/i)).toBeInTheDocument();
    // Evidence preserved for correction/re-submission
    expect(sqlBox).toHaveValue("' OR 1=1 --");
  });

  it('reflects a previously verified result after reload', async () => {
    renderWorkspace(mockFetch({
      withHandsOn: true,
      priorResult: {
        question_id: 'hands-1',
        submitted_input: "' OR 1=1 --",
        submitted_flag: 'FLAG{correct}',
        verified: true,
        score: 100,
      },
    }));

    fireEvent.click(await screen.findByRole('button', { name: /Hands-On \(1\)/i }));

    expect(await screen.findByText('✓ Completed')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Paste the SQL input/i)).toHaveValue("' OR 1=1 --");
    expect(screen.getByPlaceholderText(/FLAG\{\.\.\.\}/i)).toHaveValue('FLAG{correct}');
  });
});
