import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

// Monaco is browser-only (it touches DOM APIs at import time) and cannot run in
// jsdom, so the editor is stubbed — same convention as MCQTest.test.jsx. These
// tests cover the descriptive section, never the editor itself.
vi.mock('../components/CodeEditor', () => ({
  default: ({ value }) => <textarea data-testid="code-editor" readOnly value={value} />,
}));

const FUTURE = new Date(Date.now() + 3600_000).toISOString();

const DESCRIPTIVE_QUESTIONS = [
  {
    id: 'desc-1',
    question_text: 'Explain the differences between processes and threads.',
    image_url: 'https://example.com/os.png',
    word_limit: 300,
  },
  {
    id: 'desc-2',
    question_text: 'Describe ACID properties of transactions.',
    image_url: null,
    word_limit: null,
  },
];

function mockFetch({ withDescriptive = true } = {}) {
  return vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      return {
        ok: true,
        json: async () => ({
          questions: [
            {
              id: 'mcq-1',
              question_text: 'What is 2 + 2?',
              options: ['3', '4'],
              correct_answer: '4',
            },
          ],
          answers: { 'mcq-1': '4' },
          descriptive_questions: withDescriptive ? DESCRIPTIVE_QUESTIONS : [],
          descriptive_answers: {},
          expires_at: FUTURE,
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

describe('MCQTest — Descriptive section', () => {
  it('shows the Descriptive tab when the questions endpoint returns descriptive_questions', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    const tab = await screen.findByRole('button', { name: /Descriptive \(2\)/i });
    expect(tab).toBeInTheDocument();

    fireEvent.click(tab);
    expect(
      await screen.findByText(/Explain the differences between processes and threads/i)
    ).toBeInTheDocument();
    expect(screen.getByText('Question 1 of 2')).toBeInTheDocument();
    expect(screen.getByText(/Word limit: 300/)).toBeInTheDocument();
  });

  it('renders the question image and live word count', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));

    const img = await screen.findByAltText('Question image');
    expect(img).toHaveAttribute('src', 'https://example.com/os.png');

    const textarea = screen.getByPlaceholderText(/Type your answer here/i);
    fireEvent.change(textarea, { target: { value: 'A process has its own memory space.' } });
    expect(screen.getByText('Word count: 7 / 300')).toBeInTheDocument();
  });

  it('hard-constrains typed input to the word limit', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));
    const textarea = await screen.findByPlaceholderText(/Type your answer here/i);

    // Type far beyond the 300-word limit of desc-1.
    const overLimit = Array.from({ length: 400 }, (_, i) => `word${i}`).join(' ');
    fireEvent.change(textarea, { target: { value: overLimit } });

    expect(screen.getByText('Word count: 300 / 300')).toBeInTheDocument();
  });

  it('constrains over-limit pasted text to the first N words', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));
    const textarea = await screen.findByPlaceholderText(/Type your answer here/i);

    const pasted = Array.from({ length: 500 }, (_, i) => `w${i}`).join(' ');
    fireEvent.change(textarea, { target: { value: pasted } });

    expect(screen.getByText('Word count: 300 / 300')).toBeInTheDocument();
  });

  it('allows unlimited text when no word_limit is configured', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));
    await screen.findByText(/Explain the differences/i);
    fireEvent.click(screen.getByRole('button', { name: /Next/i }));

    const textarea = await screen.findByPlaceholderText(/Type your answer here/i);
    const longText = Array.from({ length: 500 }, (_, i) => `free${i}`).join(' ');
    fireEvent.change(textarea, { target: { value: longText } });

    expect(screen.getByText('Word count: 500')).toBeInTheDocument();
  });

  it('counts words on the whitespace-run rule (no empty tokens)', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));
    const textarea = await screen.findByPlaceholderText(/Type your answer here/i);
    fireEvent.change(textarea, { target: { value: '  hello   world\n\t\nthis  ' } });

    expect(screen.getByText('Word count: 3 / 300')).toBeInTheDocument();
  });

  it('navigates between descriptive questions and has no word-limit row when absent', async () => {
    renderWorkspace(mockFetch({ withDescriptive: true }));

    fireEvent.click(await screen.findByRole('button', { name: /Descriptive \(2\)/i }));
    await screen.findByText(/Explain the differences/i);
    expect(screen.getByText(/Word limit: 300/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Next/i }));
    expect(await screen.findByText(/Describe ACID properties/i)).toBeInTheDocument();
    expect(screen.getByText('Question 2 of 2')).toBeInTheDocument();
    expect(screen.queryByText(/Word limit:/i)).not.toBeInTheDocument();
  });

  it('hides the Descriptive tab when no descriptive questions are returned (count = 0 behaviour)', async () => {
    renderWorkspace(mockFetch({ withDescriptive: false }));

    await screen.findByRole('button', { name: /MCQ \(1\)/i });
    expect(screen.queryByRole('button', { name: /Descriptive/i })).not.toBeInTheDocument();
  });
});
