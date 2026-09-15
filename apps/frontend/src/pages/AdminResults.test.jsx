import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import AdminResults from './AdminResults';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: true, loading: false, getAuthHeaders: () => ({}) }),
}));

const ATTEMPT_ID = 'attempt-1';

function mockFetch(payload) {
  return vi.fn(async (url) => {
    if (String(url).includes(`/admin/assessments/${ATTEMPT_ID}/results`)) {
      return { ok: true, json: async () => payload };
    }
    return { ok: true, json: async () => ({}) };
  });
}

function renderPage(fetchMock) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={[`/admin/assessments/${ATTEMPT_ID}/results`]}>
      <Routes>
        <Route path="/admin/assessments/:attemptId/results" element={<AdminResults />} />
      </Routes>
    </MemoryRouter>
  );
}

function buildResults({ descriptives } = {}) {
  return {
    attempt_id: ATTEMPT_ID,
    candidate: { full_name: 'Cand A', email: 'a@t.com', usn: 'USN1', branch: 'CSE', semester_label: '5th' },
    domain_names: ['Web Dev'],
    total_mcq_questions: 1,
    total_coding_problems: 0,
    total_descriptive_questions: descriptives?.length ?? 0,
    duration_minutes: 20,
    started_at: '2026-09-14T10:00:00Z',
    submitted_at: '2026-09-14T10:15:00Z',
    score: 1, max_score: 1, percentage: 100,
    mcq_score: 1, mcq_max_score: 1, coding_score: 0, coding_max_score: 0,
    correct_count: 1, incorrect_count: 0, unanswered_count: 0,
    mcq_questions: [{
      question_text: 'What is 2+2?', option_a: '3', option_b: '4', option_c: '5', option_d: '6',
      correct_option: 'B', explanation: null, selected_option: 'B', is_correct: true, domainName: 'Web Dev',
    }],
    coding_results: [],
    descriptive_results: descriptives,
  };
}

describe('AdminResults — Descriptive Responses section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders answered descriptive question with answer, image and word limit', async () => {
    renderPage(mockFetch(buildResults({
      descriptives: [{
        question_id: 'd1',
        question_text: 'Explain processes vs threads.',
        image_url: 'https://example.com/os.png',
        word_limit: 100,
        answer_text: 'A process has its own memory space.',
        answered_at: '2026-09-14T10:05:00Z',
      }],
    })));

    expect(await screen.findByText('Descriptive Responses')).toBeInTheDocument();
    expect(screen.getByText(/Explain processes vs threads\./)).toBeInTheDocument();
    expect(screen.getByText('A process has its own memory space.')).toBeInTheDocument();
    expect(screen.getByText('Answered')).toBeInTheDocument();
    expect(screen.getByText('Word count: 7 / 100')).toBeInTheDocument();
    expect(screen.getByText('Word limit: 100')).toBeInTheDocument();
    const img = screen.getByAltText('Question image');
    expect(img).toHaveAttribute('src', 'https://example.com/os.png');
  });

  it('renders unanswered descriptive question as "Not answered" (not hidden)', async () => {
    renderPage(mockFetch(buildResults({
      descriptives: [{
        question_id: 'd1',
        question_text: 'Unanswered one.',
        image_url: null,
        word_limit: null,
        answer_text: null,
        answered_at: null,
      }],
    })));

    expect(await screen.findByText('Descriptive Responses')).toBeInTheDocument();
    expect(screen.getByText(/Unanswered one\./)).toBeInTheDocument();
    // Badge + candidate-answer body both read "Not answered"
    expect(screen.getAllByText('Not answered').length).toBe(2);
    expect(screen.getByText('Word count: 0')).toBeInTheDocument();
  });

  it('renders multiple descriptive questions including mixed states', async () => {
    renderPage(mockFetch(buildResults({
      descriptives: [
        { question_id: 'd1', question_text: 'Q1 text', image_url: null, word_limit: 50, answer_text: 'answer one', answered_at: '2026-09-14T10:05:00Z' },
        { question_id: 'd2', question_text: 'Q2 text', image_url: null, word_limit: null, answer_text: '', answered_at: '2026-09-14T10:06:00Z' },
      ],
    })));

    expect(await screen.findByText('Descriptive Responses')).toBeInTheDocument();
    expect(screen.getByText(/Q1 text/)).toBeInTheDocument();
    expect(screen.getByText(/Q2 text/)).toBeInTheDocument();
    expect(screen.getByText('answer one')).toBeInTheDocument();
    // Q2 saved an empty string → treated as unanswered (badge + body)
    const notAnswered = screen.getAllByText('Not answered');
    expect(notAnswered.length).toBe(2);
    expect(screen.getByText('Word count: 2 / 50')).toBeInTheDocument();
    expect(screen.getByText('Word count: 0')).toBeInTheDocument();
  });

  it('does not render the section when there are no descriptive questions', async () => {
    renderPage(mockFetch(buildResults({ descriptives: [] })));

    await screen.findByText(/What is 2\+2\?/);
    expect(screen.queryByText('Descriptive Responses')).not.toBeInTheDocument();
  });

  it('never displays admin_remark', async () => {
    renderPage(mockFetch(buildResults({ descriptives: [] })));
    await screen.findByText(/What is 2\+2\?/);
    expect(screen.queryByText(/admin_remark/i)).not.toBeInTheDocument();
  });
});
