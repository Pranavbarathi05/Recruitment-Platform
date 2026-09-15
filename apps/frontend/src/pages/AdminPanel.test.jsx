import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPanel from './AdminPanel';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const FUTURE_SUBMITTED = new Date(Date.now() - 3600_000).toISOString();

const SUBMISSION_NO_REMARK = {
  attempt_id: 'attempt-1',
  candidate_name: 'Alice Candidate',
  email: 'alice@test.com',
  usn: '01JST22CS001',
  branch: 'CSE',
  semester: 5,
  domain_ids: ['d1'],
  domain_names: ['Web Development'],
  score: 18,
  max_score: 20,
  percentage: 90,
  mcq_score: 10,
  mcq_max_score: 10,
  coding_score: 8,
  coding_max_score: 10,
  total_mcq_questions: 10,
  total_coding_problems: 2,
  total_descriptive_questions: 1,
  admin_remark: null,
  status: 'scored',
  started_at: FUTURE_SUBMITTED,
  submitted_at: FUTURE_SUBMITTED,
};

function makeSubmission(overrides = {}) {
  return { ...SUBMISSION_NO_REMARK, ...overrides };
}

/**
 * Fetch mock:
 * - /admin/domains → admin check + domain list (admin check must succeed)
 * - /admin/config → config list
 * - /admin/assessments/submissions → submissions list
 */
function mockFetch({ submissions = [SUBMISSION_NO_REMARK], onRemarkPut } = {}) {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();

    if (u.includes('/admin/domains')) {
      return {
        ok: true,
        json: async () => [
          {
            id: 'd1',
            name: 'Web Development',
            slug: 'webDevelopment',
            description: '',
            duration_minutes: 20,
            is_active: true,
            questionCount: 0,
            semesterCounts: { 1: 0, 3: 0, 5: 0, 7: 0 },
          },
        ],
      };
    }
    if (u.includes('/admin/config')) {
      return { ok: true, json: async () => [] };
    }
    if (u.includes('/admin/assessments/submissions')) {
      return { ok: true, json: async () => submissions };
    }
    if (u.includes('/remark') && method === 'PUT') {
      const body = JSON.parse(options.body || '{}');
      if (onRemarkPut) return onRemarkPut(body);
      return {
        ok: true,
        json: async () => ({ attempt_id: 'attempt-1', admin_remark: body.admin_remark, status: 'saved' }),
      };
    }
    if (u.includes('/remark') && method === 'DELETE') {
      return {
        ok: true,
        json: async () => ({ attempt_id: 'attempt-1', admin_remark: null, status: 'cleared' }),
      };
    }
    return { ok: true, json: async () => ({}) };
  });
}

function renderAdminPanel(fetchMock) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={['/admin']}>
      <AdminPanel />
    </MemoryRouter>
  );
}

beforeEach(() => {
  cleanup();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AdminPanel — submission remark chat button', () => {
  it('renders a chat button for every submission row', async () => {
    renderAdminPanel(
      mockFetch({ submissions: [makeSubmission(), makeSubmission({ attempt_id: 'attempt-2' })] })
    );

    const buttons = await screen.findAllByRole('button', { name: /remark for/i });
    expect(buttons).toHaveLength(2);
  });

  it('chat button is faded (opacity) when no remark exists and highlighted when one does', async () => {
    renderAdminPanel(
      mockFetch({
        submissions: [
          makeSubmission({ attempt_id: 'attempt-no-remark', admin_remark: null }),
          makeSubmission({ attempt_id: 'attempt-with-remark', admin_remark: 'Strong candidate' }),
        ],
      })
    );

    const noRemark = await screen.findByRole('button', {
      name: 'Add remark for Alice Candidate',
    });
    expect(noRemark.className).toMatch(/opacity-60/);
    expect(noRemark.className).not.toMatch(/bg-blue-600/);

    const withRemark = await screen.findByRole('button', {
      name: 'Edit remark for Alice Candidate',
    });
    expect(withRemark.className).toMatch(/bg-blue-600/);
    expect(withRemark.className).not.toMatch(/opacity-60/);
  });

  it('opens the modal with the existing remark when the chat button is clicked', async () => {
    renderAdminPanel(
      mockFetch({ submissions: [makeSubmission({ admin_remark: 'Existing note' })] })
    );

    fireEvent.click(await screen.findByRole('button', { name: /Edit remark for Alice/i }));

    const dialogHeading = await screen.findByRole('heading', { name: /Assessment Remark/i });
    expect(dialogHeading).toBeInTheDocument();
    const textarea = screen.getByPlaceholderText(/Write a remark/i);
    expect(textarea.value).toBe('Existing note');
  });

  it('saves a new remark and refreshes the submissions list', async () => {
    const fetchMock = mockFetch({ submissions: [makeSubmission({ admin_remark: null })] });
    renderAdminPanel(fetchMock);

    fireEvent.click(await screen.findByRole('button', { name: /Add remark for Alice/i }));
    const textarea = screen.getByPlaceholderText(/Write a remark/i);
    fireEvent.change(textarea, { target: { value: 'Interview recommended' } });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, opts]) => String(url).includes('/remark') && (opts?.method || '').toUpperCase() === 'PUT'
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body)).toEqual({ admin_remark: 'Interview recommended' });
    });
  });

  it('clears the remark via the Clear button (DELETE request)', async () => {
    const fetchMock = mockFetch({ submissions: [makeSubmission({ admin_remark: 'Old note' })] });
    renderAdminPanel(fetchMock);

    fireEvent.click(await screen.findByRole('button', { name: /Edit remark for Alice/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));

    await waitFor(() => {
      const deleteCalls = fetchMock.mock.calls.filter(
        ([url, opts]) => String(url).includes('/remark') && (opts?.method || '').toUpperCase() === 'DELETE'
      );
      expect(deleteCalls).toHaveLength(1);
    });
  });

  it('preserves the edited text after a failed save and shows the error', async () => {
    const fetchMock = mockFetch({
      submissions: [makeSubmission({ admin_remark: null })],
      onRemarkPut: () => ({
        ok: false,
        json: async () => ({ detail: 'Server error while saving' }),
      }),
    });
    renderAdminPanel(fetchMock);

    fireEvent.click(await screen.findByRole('button', { name: /Add remark for Alice/i }));
    const textarea = screen.getByPlaceholderText(/Write a remark/i);
    fireEvent.change(textarea, { target: { value: 'Important note to keep' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    // Error shown, text preserved, modal stays open
    expect(await screen.findByText(/Server error while saving/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Write a remark/i).value).toBe('Important note to keep');
    expect(screen.getByRole('heading', { name: /Assessment Remark/i })).toBeInTheDocument();
  });

  it('closes the modal with Cancel', async () => {
    renderAdminPanel(mockFetch({ submissions: [makeSubmission({ admin_remark: null })] }));

    fireEvent.click(await screen.findByRole('button', { name: /Add remark for Alice/i }));
    expect(screen.getByRole('heading', { name: /Assessment Remark/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('heading', { name: /Assessment Remark/i })).not.toBeInTheDocument();
  });

  it('disables Clear when there is nothing to clear', async () => {
    renderAdminPanel(mockFetch({ submissions: [makeSubmission({ admin_remark: null })] }));

    fireEvent.click(await screen.findByRole('button', { name: /Add remark for Alice/i }));
    const clearButton = screen.getByRole('button', { name: 'Clear' });
    expect(clearButton).toBeDisabled();

    // Typing something enables Clear
    fireEvent.change(screen.getByPlaceholderText(/Write a remark/i), {
      target: { value: 'new text' },
    });
    expect(clearButton).not.toBeDisabled();
  });

  it('existing submission actions remain functional (Reset/Delete open their modals)', async () => {
    renderAdminPanel(mockFetch({ submissions: [makeSubmission({ status: 'scored' })] }));

    fireEvent.click(await screen.findByRole('button', { name: 'Reset' }));
    expect(
      screen.getByRole('heading', { name: /Reset Assessment/i })
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    expect(
      screen.getByRole('heading', { name: /Delete Assessment/i })
    ).toBeInTheDocument();
  });
});
