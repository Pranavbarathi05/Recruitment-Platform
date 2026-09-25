import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Domains from './Domains';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

/**
 * The Domains page must offer exactly the domains the candidate's programme
 * allows — no more, and critically NO LESS.
 *
 * CORRECTED RULE: `assessment_program.scope` is a programme's DEFAULT mode,
 * not an exclusive restriction.
 *
 *   1st semester  (organizational) -> Organizational Roles only
 *   3rd / 5th     (technical)      -> technical domains AND Organizational
 *                                     Roles as a STANDALONE choice
 *
 * So a technical candidate must SEE Organizational Roles; what is forbidden
 * is COMBINING it with a technical domain (the planner refuses that
 * independently, and the selection UI makes it unreachable). Only a 1st
 * semester candidate is offered a narrowed list.
 *
 * These tests pin the per-semester contract of the eligibility endpoint and
 * prove the page renders everything the endpoint returns.
 */

const TECHNICAL_DOMAINS = [
  {
    id: 'domain-web',
    slug: 'webDevelopment',
    name: 'Web Development',
    assessment_scope: 'technical',
    description: 'Build and ship web applications.',
    questionCount: 40,
    durationMinutes: 60,
  },
  {
    id: 'domain-ml',
    slug: 'machineLearning',
    name: 'Machine Learning',
    assessment_scope: 'technical',
    description: 'Models, data and evaluation.',
    questionCount: 40,
    durationMinutes: 60,
  },
];

const ORGANIZATIONAL_DOMAINS = [
  {
    id: 'domain-org',
    slug: 'organizationalRoles',
    name: 'Organizational Roles',
    assessment_scope: 'organizational',
    description: 'Org structures, team roles and responsibilities.',
    questionCount: 12,
    durationMinutes: 60,
  },
];

let requests;
let startBodies;

/** Serves one eligibility response and records every request the page makes. */
function mockFetch(payload, { ok = true, status = 200 } = {}) {
  requests = [];
  startBodies = [];
  return vi.fn((url, options = {}) => {
    requests.push({ url: String(url), options });
    if (String(url).includes('/assessment/available-domains')) {
      return Promise.resolve({
        ok,
        status,
        json: async () => payload,
      });
    }
    if (String(url).includes('/assessment/start')) {
      startBodies.push(JSON.parse(options.body));
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ attempt_id: 'attempt-1' }),
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
  });
}

async function renderDomains(payload, options) {
  globalThis.fetch = mockFetch(payload, options);
  const view = render(
    <MemoryRouter initialEntries={['/domains']}>
      <Routes>
        <Route path="/domains" element={<Domains />} />
        <Route path="/assessment/:attemptId" element={<div>Assessment workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
  // Let the eligibility request settle inside act() so the rendered state is
  // the post-fetch one.
  await act(async () => {});
  return view;
}

const startButton = () => screen.getByRole('button', { name: /start assessment/i });

async function submit() {
  fireEvent.click(startButton());
  await act(async () => {});
}

beforeEach(() => {
  cleanup();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Domains — the offered list follows the candidate programme', () => {
  it('offers technical domains AND the standalone Organizational domain to a technical candidate', async () => {
    // CORRECTED RULE: a technical programme offers BOTH modes, and
    // Organizational Roles is a standalone choice rather than hidden.
    await renderDomains({
      semester: 3,
      scope: 'technical',
      tier: 'junior',
      max_domains: 2,
      domains: [...TECHNICAL_DOMAINS, ...ORGANIZATIONAL_DOMAINS],
    });

    expect(await screen.findByText('Web Development')).toBeInTheDocument();
    expect(screen.getByText('Machine Learning')).toBeInTheDocument();
    expect(screen.getByText('Organizational Roles')).toBeInTheDocument();

    // Organizational replaces any technical selection (standalone only)…
    fireEvent.click(screen.getByText('Web Development'));
    fireEvent.click(screen.getByText('Organizational Roles'));
    expect(screen.getByText('1 domain selected')).toBeInTheDocument();

    // …and a technical domain can never be added beside it (the notice is
    // the live region; the header copy mentions the rule too).
    fireEvent.click(screen.getByText('Web Development'));
    expect(screen.getByRole('status')).toHaveTextContent(/cannot be combined/i);
    expect(screen.getByText('1 domain selected')).toBeInTheDocument();

    await submit();
    expect(startBodies).toEqual([{ domain_ids: ['domain-org'] }]);
  });

  it('offers only the Organizational domain to the 1st-semester candidate', async () => {
    await renderDomains({ semester: 1, scope: 'organizational', tier: null, max_domains: 1, domains: ORGANIZATIONAL_DOMAINS });

    expect(await screen.findByText('Organizational Roles')).toBeInTheDocument();
    expect(screen.queryByText('Web Development')).toBeNull();
    expect(screen.queryByText('Machine Learning')).toBeNull();

    // The one domain it does offer is the id that gets submitted.
    fireEvent.click(screen.getByText('Organizational Roles'));
    await submit();
    expect(startBodies).toEqual([{ domain_ids: ['domain-org'] }]);
  });

  it('submits exactly the eligible technical domain that was selected', async () => {
    await renderDomains({ semester: 3, scope: 'technical', tier: 'junior', max_domains: 2, domains: TECHNICAL_DOMAINS });

    fireEvent.click(await screen.findByText('Web Development'));
    await submit();

    expect(startBodies).toEqual([{ domain_ids: ['domain-web'] }]);
    expect(await screen.findByText('Assessment workspace')).toBeInTheDocument();
  });

  it('renders every domain the endpoint returns and never discards one for a low question count', async () => {
    // A zero (or small) question count is display metadata only. It must not
    // make an otherwise eligible, configured technical assessment disappear
    // — eligibility comes from assessment_program.scope + is_active, and
    // whether there is enough content to start is the planner's decision.
    const sparse = [
      { ...TECHNICAL_DOMAINS[0], questionCount: 0 },
      { ...TECHNICAL_DOMAINS[1], questionCount: 3 },
    ];
    await renderDomains({ semester: 3, scope: 'technical', tier: 'junior', max_domains: 2, domains: sparse });

    expect(await screen.findByText('Web Development')).toBeInTheDocument();
    expect(screen.getByText('Machine Learning')).toBeInTheDocument();
    // The counts are display metadata only: they are not a filter, and the
    // cards deliberately render no question-count/duration badge.
    expect(screen.queryByText(/Questions/)).toBeNull();
    expect(screen.queryByText(/min$/)).toBeNull();

    // Both remain selectable and the low-count one still submits.
    fireEvent.click(screen.getByText('Web Development'));
    await submit();
    expect(startBodies).toEqual([{ domain_ids: ['domain-web'] }]);
  });

  it('renders every domain returned for a 5th-semester technical candidate', async () => {
    await renderDomains({
      semester: 5,
      scope: 'technical',
      tier: 'senior',
      max_domains: 2,
      domains: [
        ...TECHNICAL_DOMAINS,
        { ...TECHNICAL_DOMAINS[0], id: 'domain-cyber', slug: 'cyberSecurity', name: 'Cyber Security' },
        ...ORGANIZATIONAL_DOMAINS,
      ],
    });

    expect(await screen.findByText('Web Development')).toBeInTheDocument();
    expect(screen.getByText('Machine Learning')).toBeInTheDocument();
    expect(screen.getByText('Cyber Security')).toBeInTheDocument();
    // Organizational Roles IS offered to a technical candidate — the page
    // must not silently discard it just because the programme is technical.
    expect(screen.getByText('Organizational Roles')).toBeInTheDocument();
  });

  it('loads the candidate-scoped endpoint with the session cookie, never the global catalogue', async () => {
    await renderDomains({ semester: 5, scope: 'technical', max_domains: 2, domains: TECHNICAL_DOMAINS });
    await screen.findByText('Web Development');

    const urls = requests.map((r) => r.url);
    expect(urls.some((u) => u.includes('/assessment/available-domains'))).toBe(true);
    expect(urls.some((u) => u.includes('/questions/domains'))).toBe(false);

    const eligibility = requests.find((r) => r.url.includes('/assessment/available-domains'));
    expect(eligibility.options.credentials).toBe('include');
  });

  it('caps the selection at the programme max_domains', async () => {
    // Synthetic payload: the programme's cap is 1, so a second selection must
    // be refused even for domains the UI would otherwise allow two of.
    await renderDomains({ semester: 1, scope: 'organizational', max_domains: 1, domains: TECHNICAL_DOMAINS });

    fireEvent.click(await screen.findByText('Web Development'));
    fireEvent.click(screen.getByText('Machine Learning'));

    expect(screen.getByText('1 domain selected')).toBeInTheDocument();
    await submit();
    expect(startBodies).toEqual([{ domain_ids: ['domain-web'] }]);
  });

  it('shows no domains (and no start button) when the semester has no assessment', async () => {
    await renderDomains({ semester: 7, scope: 'none', tier: null, max_domains: 1, domains: [] });

    expect(await screen.findByText(/no domains available/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /start assessment/i })).toBeNull();
  });

  it('reports a failure instead of falling back to a domain list', async () => {
    await renderDomains({ detail: 'Not authenticated' }, { ok: false, status: 401 });

    expect(await screen.findByText(/failed to load domains/i)).toBeInTheDocument();
    expect(screen.queryByText('Web Development')).toBeNull();
    expect(screen.queryByRole('button', { name: /start assessment/i })).toBeNull();
  });

  it('ignores a malformed payload rather than rendering an unusable list', async () => {
    await renderDomains({ semester: 5 });

    expect(await screen.findByText(/no domains available/i)).toBeInTheDocument();
  });
});
