import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AdminPanel from './AdminPanel';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const CONFIG = {
  id: 'cfg-1',
  name: 'MCQ Assessment',
  coding_problem_count: 2,
  duration_minutes: 20,
  is_active: true,
  network_integrity_monitoring: false,
};

function mockFetch({ configs = [CONFIG] } = {}) {
  return vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/admin/domains')) {
      return { ok: true, json: async () => [] };
    }
    if (u.includes('/admin/config')) {
      return { ok: true, json: async () => configs };
    }
    if (u.includes('/admin/assessments/submissions')) {
      return { ok: true, json: async () => [] };
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

async function openConfigEditor() {
  const heading = await screen.findByText('MCQ Assessment');
  const card = heading.closest('.bg-theme-secondary');
  fireEvent.click(within(card).getByRole('button', { name: 'Edit' }));
  return card;
}

// The domain list and the MCQ-total form also render a Save button.
function saveCard(card) {
  fireEvent.click(within(card).getByRole('button', { name: 'Save' }));
}

function putBodies(fetchMock) {
  return fetchMock.mock.calls
    .filter(([, opts]) => (opts?.method || '').toUpperCase() === 'PUT')
    .map(([, opts]) => JSON.parse(opts.body));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AdminPanel — Network Integrity Monitoring toggle', () => {
  it('shows the setting as Off by default in the read-only summary', async () => {
    renderAdminPanel(mockFetch());

    await screen.findByText('MCQ Assessment');

    expect(screen.getByTestId('network-integrity-state')).toHaveTextContent(
      'Network Integrity Monitoring: Off'
    );
  });

  it('renders a labelled toggle that explains what it does', async () => {
    renderAdminPanel(mockFetch());
    await openConfigEditor();

    expect(screen.getByText('Network Integrity Monitoring')).toBeInTheDocument();
    expect(
      screen.getByText(/Detect direct internet connectivity during active assessments/i)
    ).toBeInTheDocument();
    expect(screen.getByTestId('network-integrity-toggle')).not.toBeChecked();
  });

  it('saving the toggle on persists it in the update payload', async () => {
    const fetchMock = mockFetch();
    renderAdminPanel(fetchMock);
    const card = await openConfigEditor();

    fireEvent.click(screen.getByTestId('network-integrity-toggle'));
    expect(screen.getByTestId('network-integrity-toggle')).toBeChecked();

    saveCard(card);

    await waitFor(() => {
      expect(putBodies(fetchMock)).toHaveLength(1);
    });
    expect(putBodies(fetchMock)[0].network_integrity_monitoring).toBe(true);
    // Nothing else was disturbed.
    expect(putBodies(fetchMock)[0].duration_minutes).toBe(20);
  });

  it('an already-enabled config opens with the toggle checked and can be turned off', async () => {
    const fetchMock = mockFetch({
      configs: [{ ...CONFIG, network_integrity_monitoring: true }],
    });
    renderAdminPanel(fetchMock);
    const card = await openConfigEditor();

    expect(screen.getByTestId('network-integrity-toggle')).toBeChecked();

    fireEvent.click(screen.getByTestId('network-integrity-toggle'));
    saveCard(card);

    await waitFor(() => {
      expect(putBodies(fetchMock)).toHaveLength(1);
    });
    expect(putBodies(fetchMock)[0].network_integrity_monitoring).toBe(false);
  });

  it('a config row without the column opens as Off', async () => {
    const { network_integrity_monitoring: _omitted, ...legacyRow } = CONFIG;
    renderAdminPanel(mockFetch({ configs: [legacyRow] }));
    await openConfigEditor();

    expect(screen.getByTestId('network-integrity-toggle')).not.toBeChecked();
  });
});
