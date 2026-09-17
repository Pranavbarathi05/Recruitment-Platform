import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import AdminModules from './AdminModules';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const TECH_DOMAIN = {
  id: 'd-tech',
  name: 'Machine Learning',
  slug: 'machineLearning',
  assessment_scope: 'technical',
  is_active: true,
};

const ORG_DOMAIN = {
  id: 'd-org',
  name: 'Organizational Roles',
  slug: 'organizationalRoles',
  assessment_scope: 'organizational',
  is_active: true,
};

const INACTIVE_DOMAIN = {
  id: 'd-off',
  name: 'Cyber Security',
  slug: 'cyberSecurity',
  assessment_scope: 'technical',
  is_active: false,
};

function modulesResponse({ techConfigs = [], orgConfigs = [], includeInactive = false } = {}) {
  const entries = [
    { domain: TECH_DOMAIN, configs: techConfigs },
    { domain: ORG_DOMAIN, configs: orgConfigs },
  ];
  if (includeInactive) entries.push({ domain: INACTIVE_DOMAIN, configs: [] });
  return entries;
}

function juniorConfig(overrides = {}) {
  return {
    id: 'cfg-junior',
    domain_id: 'd-tech',
    applies_to: 'junior',
    mcq_count: 5,
    descriptive_count: 2,
    hands_on_enabled: true,
    hands_on_count: 1,
    hands_on_additional_minutes: 20,
    notes: null,
    ...overrides,
  };
}

/**
 * Fetch mock:
 * - /admin/domains            → admin probe
 * - PUT /admin/assessment/modules/{id} → save
 * - GET /admin/assessment/modules      → module list
 */
function mockFetch({ modules, domainsStatus = 200, putResponse } = {}) {
  return vi.fn(async (url, options = {}) => {
    const u = String(url);
    const method = (options.method || 'GET').toUpperCase();

    if (u.includes('/admin/domains')) {
      if (domainsStatus !== 200) {
        return { ok: false, status: domainsStatus, json: async () => ({ detail: 'denied' }) };
      }
      return { ok: true, status: 200, json: async () => [] };
    }

    if (u.includes('/admin/assessment/modules') && method === 'PUT') {
      if (putResponse) return putResponse(JSON.parse(options.body || '{}'));
      return { ok: true, status: 200, json: async () => ({}) };
    }

    if (u.includes('/admin/assessment/modules')) {
      return { ok: true, status: 200, json: async () => modules ?? modulesResponse() };
    }

    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function renderPage(fetchMock) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={['/admin/modules']}>
      <Routes>
        <Route path="/admin/modules" element={<AdminModules />} />
        <Route path="/domains" element={<div>Domains landing</div>} />
        <Route path="/login" element={<div>Login landing</div>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  cleanup();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AdminModules — tier availability', () => {
  it('shows Junior and Senior tiers for a technical domain', async () => {
    renderPage(mockFetch({}));

    fireEvent.click(await screen.findByText('Machine Learning'));

    expect(await screen.findByRole('button', { name: 'Junior' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Senior' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Organizational' })).not.toBeInTheDocument();
  });

  it('shows only the Organizational tier for an organizational domain', async () => {
    renderPage(mockFetch({}));

    fireEvent.click(await screen.findByText('Organizational Roles'));

    expect(await screen.findByRole('button', { name: 'Organizational' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Junior' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Senior' })).not.toBeInTheDocument();
  });

  it('does not expose a coding count field', async () => {
    renderPage(mockFetch({}));

    fireEvent.click(await screen.findByText('Machine Learning'));
    await screen.findByRole('button', { name: 'Junior' });

    expect(screen.queryByLabelText(/coding/i)).not.toBeInTheDocument();
  });

  it('excludes inactive domains from the configurable list', async () => {
    renderPage(mockFetch({ modules: modulesResponse({ includeInactive: true }) }));

    await screen.findByText('Machine Learning');
    expect(screen.queryByText('Cyber Security')).not.toBeInTheDocument();
    expect(screen.getByText('Domains (2)')).toBeInTheDocument();
  });
});

describe('AdminModules — unconfigured state', () => {
  it('renders an unconfigured state with zeroed fields when no config exists', async () => {
    renderPage(mockFetch({}));

    fireEvent.click(await screen.findByText('Machine Learning'));

    expect(
      await screen.findByText(/No Junior configuration exists for this domain yet/i)
    ).toBeInTheDocument();
    expect(screen.getAllByText('Not configured').length).toBeGreaterThan(0);

    // Nothing is auto-created and nothing is assumed — fields start at zero.
    expect(screen.getByLabelText('MCQ count').value).toBe('0');
    expect(screen.getByLabelText('Descriptive count').value).toBe('0');
    expect(screen.getByLabelText('Hands-on count').value).toBe('0');
    expect(screen.getByLabelText('Additional minutes').value).toBe('0');
    expect(screen.getByLabelText('Hands-on enabled')).not.toBeChecked();
  });

  it('loads an existing configuration into the form', async () => {
    renderPage(mockFetch({ modules: modulesResponse({ techConfigs: [juniorConfig()] }) }));

    fireEvent.click(await screen.findByText('Machine Learning'));

    expect(await screen.findByLabelText('MCQ count')).toHaveValue(5);
    expect(screen.getByLabelText('Descriptive count')).toHaveValue(2);
    expect(screen.getByLabelText('Hands-on enabled')).toBeChecked();
    expect(screen.getByLabelText('Hands-on count')).toHaveValue(1);
    expect(screen.getByLabelText('Additional minutes')).toHaveValue(20);
    expect(screen.getAllByText('Configured').length).toBeGreaterThan(0);
  });
});

describe('AdminModules — hands-on coupling', () => {
  it('disables and resets the dependent fields when hands-on is turned off', async () => {
    renderPage(mockFetch({ modules: modulesResponse({ techConfigs: [juniorConfig()] }) }));

    fireEvent.click(await screen.findByText('Machine Learning'));

    const countInput = await screen.findByLabelText('Hands-on count');
    const minutesInput = screen.getByLabelText('Additional minutes');
    expect(countInput).not.toBeDisabled();
    expect(minutesInput).not.toBeDisabled();
    expect(countInput).toHaveValue(1);
    expect(minutesInput).toHaveValue(20);

    fireEvent.click(screen.getByLabelText('Hands-on enabled'));

    expect(screen.getByLabelText('Hands-on count')).toBeDisabled();
    expect(screen.getByLabelText('Additional minutes')).toBeDisabled();
    expect(screen.getByLabelText('Hands-on count')).toHaveValue(0);
    expect(screen.getByLabelText('Additional minutes')).toHaveValue(0);
  });

  it('sends zeroed hands-on values when hands-on is disabled', async () => {
    const fetchMock = mockFetch({
      modules: modulesResponse({ techConfigs: [juniorConfig()] }),
      putResponse: () => ({ ok: true, status: 200, json: async () => ({}) }),
    });
    renderPage(fetchMock);

    fireEvent.click(await screen.findByText('Machine Learning'));
    fireEvent.click(await screen.findByLabelText('Hands-on enabled'));
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, opts]) =>
          String(url).includes('/admin/assessment/modules/') &&
          (opts?.method || '').toUpperCase() === 'PUT'
      );
      expect(putCalls).toHaveLength(1);
      expect(JSON.parse(putCalls[0][1].body)).toMatchObject({
        applies_to: 'junior',
        hands_on_enabled: false,
        hands_on_count: 0,
        hands_on_additional_minutes: 0,
      });
    });
  });
});

describe('AdminModules — save', () => {
  it('saves the selected tier and shows the preflight on success', async () => {
    const fetchMock = mockFetch({
      modules: modulesResponse(),
      putResponse: () => ({
        ok: true,
        status: 200,
        json: async () => ({
          domain: TECH_DOMAIN,
          config: juniorConfig({ hands_on_enabled: false, hands_on_count: 0, hands_on_additional_minutes: 0 }),
          preflight: {
            mcq_available: 12,
            mcq_required_semester: 3,
            descriptive_available: 4,
            hands_on_available: 0,
            hard_errors: [],
            warnings: [],
          },
        }),
      }),
    });
    renderPage(fetchMock);

    fireEvent.click(await screen.findByText('Machine Learning'));
    fireEvent.change(await screen.findByLabelText('MCQ count'), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText('Descriptive count'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));

    expect(await screen.findByText('Configuration saved successfully.')).toBeInTheDocument();

    await waitFor(() => {
      const putCalls = fetchMock.mock.calls.filter(
        ([url, opts]) =>
          String(url).includes('/admin/assessment/modules/') &&
          (opts?.method || '').toUpperCase() === 'PUT'
      );
      expect(putCalls).toHaveLength(1);
      expect(String(putCalls[0][0])).toContain('/admin/assessment/modules/d-tech');
      expect(JSON.parse(putCalls[0][1].body)).toEqual({
        applies_to: 'junior',
        mcq_count: 5,
        descriptive_count: 2,
        hands_on_enabled: false,
        hands_on_count: 0,
        hands_on_additional_minutes: 0,
        notes: null,
      });
    });

    expect(screen.getByText('Preflight')).toBeInTheDocument();
    expect(screen.getByText('Available MCQs:')).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
  });

  it('treats a hard preflight error as blocking and never reports success', async () => {
    const fetchMock = mockFetch({
      modules: modulesResponse(),
      putResponse: () => ({
        ok: false,
        status: 400,
        json: async () => ({
          detail:
            'Requested mcq_count (20) exceeds the available MCQ pool (3) for semester 3',
        }),
      }),
    });
    renderPage(fetchMock);

    fireEvent.click(await screen.findByText('Machine Learning'));
    fireEvent.change(await screen.findByLabelText('MCQ count'), { target: { value: '20' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save configuration' }));

    expect(
      await screen.findByText(/exceeds the available MCQ pool/)
    ).toBeInTheDocument();
    expect(screen.queryByText('Configuration saved successfully.')).not.toBeInTheDocument();
  });

  it('shows an advisory warning without blocking the save', async () => {
    const fetchMock = mockFetch({
      modules: modulesResponse(),
      putResponse: () => ({
        ok: true,
        status: 200,
        json: async () => ({
          domain: TECH_DOMAIN,
          config: juniorConfig(),
          preflight: {
            mcq_available: 12,
            mcq_required_semester: 3,
            descriptive_available: 4,
            hands_on_available: 2,
            hard_errors: [],
            warnings: [
              'Some descriptive questions are shared with other domains; the planner validates cross-domain feasibility when an assessment is created',
            ],
          },
        }),
      }),
    });
    renderPage(fetchMock);

    fireEvent.click(await screen.findByText('Machine Learning'));
    fireEvent.click(await screen.findByRole('button', { name: 'Save configuration' }));

    expect(await screen.findByText('Advisory warnings')).toBeInTheDocument();
    expect(screen.getByText(/shared with other domains/)).toBeInTheDocument();
    expect(screen.getByText('Configuration saved successfully.')).toBeInTheDocument();
  });

  it('surfaces a 422 validation error cleanly', async () => {
    const fetchMock = mockFetch({
      modules: modulesResponse(),
      putResponse: () => ({
        ok: false,
        status: 422,
        json: async () => ({ detail: [{ msg: 'hands_on_count must be 0' }] }),
      }),
    });
    renderPage(fetchMock);

    fireEvent.click(await screen.findByText('Machine Learning'));
    fireEvent.click(await screen.findByRole('button', { name: 'Save configuration' }));

    expect(await screen.findByText(/hands_on_count must be 0/)).toBeInTheDocument();
  });
});

describe('AdminModules — auth handling', () => {
  it('redirects to /login when unauthenticated', async () => {
    renderPage(mockFetch({ domainsStatus: 401 }));

    expect(await screen.findByText('Login landing')).toBeInTheDocument();
  });

  it('redirects to /domains when the user is not an admin', async () => {
    renderPage(mockFetch({ domainsStatus: 403 }));

    expect(await screen.findByText('Domains landing')).toBeInTheDocument();
  });
});
