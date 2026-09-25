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

describe('AdminResults — Hands-On Challenge Responses section', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function buildHandsOnResults({ handsOn, handsOnScore = 100, handsOnMax = 100 }) {
    const results = buildResults({});
    results.hands_on_results = handsOn;
    results.hands_on_score = handsOnScore;
    results.hands_on_max_score = handsOnMax;
    results.total_hands_on_questions = handsOn?.length ?? 0;
    return results;
  }

  it('renders a verified hands-on response with evidence, flag and score', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h1',
        title: 'SQL Injection — Employee Portal',
        challenge_type: 'sql_injection_employee_portal',
        difficulty: 'medium',
        points: 100,
        submitted_input: "' OR 1=1 --",
        submitted_flag: 'FLAG{sql1}',
        verified: true,
        score: 100,
        started_at: '2026-09-14T10:00:00Z',
        completed_at: '2026-09-14T10:05:00Z',
        attempted: true,
      }],
    })));

    expect(await screen.findByText('Hands-On Challenge Responses')).toBeInTheDocument();
    expect(screen.getByText(/SQL Injection — Employee Portal/)).toBeInTheDocument();
    expect(screen.getByText('✓ Completed')).toBeInTheDocument();
    expect(screen.getByText("' OR 1=1 --")).toBeInTheDocument();
    expect(screen.getByText('FLAG{sql1}')).toBeInTheDocument();
    expect(screen.getByText('Score: 100 / 100')).toBeInTheDocument();
    expect(screen.getByText(/Verification: ✓ Correct/)).toBeInTheDocument();
  });

  it('renders an incorrect submission without revealing the expected flag', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h1',
        title: 'SQL Injection — Employee Portal',
        challenge_type: 'sql_injection_employee_portal',
        difficulty: 'medium',
        points: 100,
        submitted_input: "admin'--",
        submitted_flag: 'FLAG{nope}',
        verified: false,
        score: 0,
        started_at: '2026-09-14T10:00:00Z',
        completed_at: null,
        attempted: true,
      }],
      handsOnScore: 0,
    })));

    expect(await screen.findByText('✗ Not Completed')).toBeInTheDocument();
    expect(screen.getByText(/Verification: ✗ Incorrect/)).toBeInTheDocument();
    expect(screen.getByText('Score: 0 / 100')).toBeInTheDocument();
    expect(screen.queryByText(/expected_flag/i)).not.toBeInTheDocument();
  });

  it('renders an unattempted challenge as Not attempted', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h1',
        title: 'SQL Injection — Employee Portal',
        challenge_type: 'sql_injection_employee_portal',
        difficulty: 'easy',
        points: 100,
        submitted_input: null,
        submitted_flag: null,
        verified: false,
        score: null,
        started_at: null,
        completed_at: null,
        attempted: false,
      }],
      handsOnScore: 0,
      handsOnMax: 100,
    })));

    expect(await screen.findByText('✗ Not Completed')).toBeInTheDocument();
    expect(screen.getAllByText('Not attempted').length).toBeGreaterThan(0);
  });

  it('does not render the hands-on section when there are no hands-on results', async () => {
    renderPage(mockFetch(buildResults({ descriptives: [] })));
    expect(await screen.findByText('Question Review')).toBeInTheDocument();
    expect(screen.queryByText('Hands-On Challenge Responses')).not.toBeInTheDocument();
  });

  it('presents a solved SQL WASM challenge as a validation pass, not a flag check', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h-sql',
        title: 'Employee Analytics — SQL',
        challenge_type: 'sql_wasm',
        difficulty: 'easy',
        points: 100,
        submitted_input: 'SELECT department, AVG(salary) FROM employees GROUP BY department;',
        submitted_flag: '',
        verified: true,
        score: 100,
        started_at: '2026-09-14T10:00:00Z',
        completed_at: '2026-09-14T10:05:00Z',
        attempted: true,
      }],
    })));

    expect(await screen.findByText('Hands-On Challenge Responses')).toBeInTheDocument();
    expect(screen.getByText('Type: SQL WASM')).toBeInTheDocument();
    expect(screen.getByText('Score: 100 / 100')).toBeInTheDocument();
    expect(screen.getByText(/Validation: ✓ Passed/)).toBeInTheDocument();
    // A WASM challenge is not flag-scored, so no flag field is implied.
    expect(screen.queryByText(/Flag Submitted/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Verification:/)).not.toBeInTheDocument();
    expect(screen.getByText('Submitted Code:')).toBeInTheDocument();
    expect(screen.getByText(/AVG\(salary\)/)).toBeInTheDocument();
  });

  it('presents a solved Pandas WASM challenge with its code and no flag evidence', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h-pd',
        title: 'Employee Analytics — Pandas',
        challenge_type: 'pandas_wasm',
        difficulty: 'easy',
        points: 100,
        submitted_input: 'result = df.groupby("department").size()',
        submitted_flag: null,
        verified: true,
        score: 100,
        started_at: '2026-09-14T10:00:00Z',
        completed_at: '2026-09-14T10:05:00Z',
        attempted: true,
      }],
    })));

    expect(await screen.findByText('Type: Pandas WASM')).toBeInTheDocument();
    expect(screen.getByText(/Validation: ✓ Passed/)).toBeInTheDocument();
    expect(screen.queryByText(/Flag Submitted/)).not.toBeInTheDocument();
    expect(screen.queryByText('—')).not.toBeInTheDocument();
  });

  it('shows a failed WASM validation with zero points', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [{
        question_id: 'h-sql',
        title: 'Employee Analytics — SQL',
        challenge_type: 'sql_wasm',
        difficulty: 'easy',
        points: 100,
        submitted_input: 'SELECT 1;',
        submitted_flag: '',
        verified: false,
        score: 0,
        started_at: '2026-09-14T10:00:00Z',
        completed_at: null,
        attempted: true,
      }],
      handsOnScore: 0,
    })));

    expect(await screen.findByText(/Validation: ✗ Failed/)).toBeInTheDocument();
    expect(screen.getByText('Score: 0 / 100')).toBeInTheDocument();
    expect(screen.getByText('✗ Not Completed')).toBeInTheDocument();
  });

  it('renders WASM and flag challenges side by side without confusing them', async () => {
    renderPage(mockFetch(buildHandsOnResults({
      handsOn: [
        {
          question_id: 'h-sql',
          title: 'Employee Analytics — SQL',
          challenge_type: 'sql_wasm',
          difficulty: 'easy',
          points: 100,
          submitted_input: 'SELECT 1;',
          submitted_flag: '',
          verified: true,
          score: 100,
          started_at: '2026-09-14T10:00:00Z',
          completed_at: '2026-09-14T10:05:00Z',
          attempted: true,
        },
        {
          question_id: 'h-flag',
          title: 'SQL Injection — Employee Portal',
          challenge_type: 'sql_injection_employee_portal',
          difficulty: 'medium',
          points: 10,
          submitted_input: "' OR 1=1 --",
          submitted_flag: 'FLAG{sql1}',
          verified: true,
          score: 10,
          started_at: '2026-09-14T10:06:00Z',
          completed_at: '2026-09-14T10:07:00Z',
          attempted: true,
        },
      ],
      handsOnScore: 110,
      handsOnMax: 110,
    })));

    expect(await screen.findByText('Type: SQL WASM')).toBeInTheDocument();
    expect(screen.getByText('Type: Flag challenge')).toBeInTheDocument();
    // Only the flag challenge exposes flag material and flag-verification wording.
    expect(screen.getByText('FLAG{sql1}')).toBeInTheDocument();
    expect(screen.getByText(/Verification: ✓ Correct/)).toBeInTheDocument();
    expect(screen.getByText(/Validation: ✓ Passed/)).toBeInTheDocument();
  });
});

describe('AdminResults — termination reason', () => {
  it('labels a network-integrity termination explicitly', async () => {
    renderPage(
      mockFetch({
        ...buildResults(),
        termination_reason: 'network_integrity_violation',
      })
    );

    expect(await screen.findByTestId('termination-reason')).toHaveTextContent(
      'Termination reason: Network integrity violation'
    );
  });

  it('shows nothing for an ordinary submission', async () => {
    renderPage(mockFetch({ ...buildResults(), termination_reason: null }));

    // Wait for the page itself to render, then assert the absence.
    expect(await screen.findByText('Performance')).toBeInTheDocument();
    expect(screen.queryByTestId('termination-reason')).not.toBeInTheDocument();
  });

  it('shows nothing when the field is absent entirely', async () => {
    renderPage(mockFetch(buildResults()));

    expect(await screen.findByText('Performance')).toBeInTheDocument();
    expect(screen.queryByTestId('termination-reason')).not.toBeInTheDocument();
  });
});
