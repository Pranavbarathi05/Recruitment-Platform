import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPanel from './AdminPanel';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const DOMAIN = {
  id: 'd1',
  name: 'Web Development',
  slug: 'webDevelopment',
  description: '',
  duration_minutes: 20,
  is_active: true,
  semesterCounts: { 1: 1, 3: 0, 5: 0, 7: 0 },
};

const MCQ = {
  id: 'mcq-1',
  domain_id: 'd1',
  semester: 1,
  question_text: 'What is HTML?',
  option_a: 'Markup',
  option_b: 'Language',
  option_c: 'Database',
  option_d: 'Framework',
  correct_option: 'A',
  explanation: '',
  is_active: true,
};

// A mutable question bank shared by the list refetches and the delete handler,
// so a successful delete is reflected on the automatic refetch.
let bank = [];

function mockFetch(onDelete) {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();

    if (u.includes('/admin/domains/d1/mcqs')) {
      return { ok: true, status: 200, json: async () => bank };
    }
    if (u.includes('/admin/mcqs/') && method === 'DELETE') {
      const response = onDelete();
      if (response.ok) bank.length = 0;
      return response;
    }
    if (u.includes('/admin/domains')) {
      return { ok: true, status: 200, json: async () => [DOMAIN] };
    }
    if (u.includes('/admin/config')) {
      return { ok: true, status: 200, json: async () => [] };
    }
    if (u.includes('/admin/assessments/submissions')) {
      return { ok: true, status: 200, json: async () => [] };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function deleteCalls(fetchMock) {
  return fetchMock.mock.calls.filter(
    ([url, opts]) => String(url).includes('/admin/mcqs/mcq-1')
      && (opts?.method || '').toUpperCase() === 'DELETE'
  );
}

async function openDomainWithMcq(fetchMock) {
  globalThis.fetch = fetchMock;
  render(
    <MemoryRouter initialEntries={['/admin']}>
      <AdminPanel />
    </MemoryRouter>
  );
  fireEvent.click(await screen.findByText('Web Development'));
  await screen.findByText('What is HTML?');
}

beforeEach(() => {
  cleanup();
  bank = [{ ...MCQ }];
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AdminPanel — MCQ deletion', () => {
  it('deleting an unused MCQ succeeds and removes it from the domain list', async () => {
    const fetchMock = mockFetch(() => ({
      ok: true,
      status: 200,
      json: async () => ({ status: 'deleted' }),
    }));
    await openDomainWithMcq(fetchMock);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(deleteCalls(fetchMock)).toHaveLength(1));
    expect(await screen.findByText('MCQ deleted')).toBeInTheDocument();
    // Gone from the list after the refetch.
    await waitFor(() => expect(screen.queryByText('What is HTML?')).not.toBeInTheDocument());
  });

  it('shows the backend 409 explanation when the MCQ is already used in an assessment', async () => {
    const fetchMock = mockFetch(() => ({
      ok: false,
      status: 409,
      json: async () => ({
        detail: 'This question is already used in an assessment and cannot be deleted. Deactivate it instead.',
      }),
    }));
    await openDomainWithMcq(fetchMock);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(
      await screen.findByText(/This question is already used in an assessment and cannot be deleted/)
    ).toBeInTheDocument();
    // The question is NOT removed on a rejected delete.
    expect(screen.getByText('What is HTML?')).toBeInTheDocument();
  });

  it('never fails silently when the error body is not JSON', async () => {
    const fetchMock = mockFetch(() => ({
      ok: false,
      status: 500,
      json: async () => { throw new Error('not json'); },
      text: async () => 'Internal Server Error',
    }));
    await openDomainWithMcq(fetchMock);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(await screen.findByText(/Internal Server Error/)).toBeInTheDocument();
  });
});
