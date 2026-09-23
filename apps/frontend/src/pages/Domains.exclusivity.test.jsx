import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Domains from './Domains';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

/**
 * Domain payloads as the API can actually return them.
 *
 * The rule is: Organizational Roles must NEVER coexist with any other domain,
 * in either click order. The excluded states are exactly the ones the real
 * browser produced, so the payload shapes below are reproduced faithfully —
 * including the one the running DEV API currently serves, which carries no
 * scope field at all and previously made the exclusivity rule silently
 * ineffective.
 */
const TECH = [
  {
    id: 'domain-cyber',
    name: 'Cyber Security',
    description: 'Network security and ethical hacking.',
    questionCount: 2,
    durationMinutes: 10,
  },
  {
    id: 'domain-devops',
    name: 'DevOps',
    description: 'CI/CD and infrastructure.',
    questionCount: 2,
    durationMinutes: 10,
  },
];

/** The real DEV response shape: no assessmentScope / assessment_scope. */
const ORG_LEGACY = {
  id: 'domain-org',
  slug: 'organizationalRoles',
  name: 'Organizational Roles',
  description: 'Org structures and responsibilities.',
  questionCount: 5,
  durationMinutes: 10,
};

const ORG_SHAPES = [
  { label: 'assessmentScope (canonical)', org: { ...ORG_LEGACY, assessmentScope: 'organizational' } },
  { label: 'assessment_scope (snake_case)', org: { ...ORG_LEGACY, assessment_scope: 'organizational' } },
  { label: 'no scope field at all (live DEV API)', org: ORG_LEGACY },
];

const MESSAGE = /cannot be combined with other domains/i;

let startBodies;
let startResolve;

function mockFetch(domains) {
  startBodies = [];
  return vi.fn((url, options = {}) => {
    const u = String(url);
    if (u.includes('/questions/domains')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => domains });
    }
    if (u.includes('/assessment/start')) {
      startBodies.push(JSON.parse(options.body));
      return new Promise((resolve) => {
        startResolve = () =>
          resolve({ ok: true, status: 200, json: async () => ({ attempt_id: 'attempt-1' }) });
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
  });
}

async function renderDomains(domains) {
  globalThis.fetch = mockFetch(domains);
  const view = render(
    <MemoryRouter initialEntries={['/domains']}>
      <Routes>
        <Route path="/domains" element={<Domains />} />
        <Route path="/assessment/:attemptId" element={<div>Assessment workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
  await screen.findByText(domains[0].name);
  return view;
}

/** The card element itself — the only ancestor carrying the card background. */
const card = (name) => screen.getByText(name).closest('div[class*="bg-theme-secondary"]');
/** The visible checkmark exists only while a card is selected. */
const isChecked = (name) => Boolean(card(name).querySelector('svg'));
const click = (name) => fireEvent.click(screen.getByText(name));
const countedText = () => screen.getByText(/\d+ domains? selected/).textContent;
const notice = () => screen.queryByRole('status');
const startButton = () => screen.getByRole('button', { name: /start assessment/i });

async function submit() {
  fireEvent.click(startButton());
  await act(async () => { if (startResolve) startResolve(); });
}

beforeEach(() => {
  cleanup();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe.each(ORG_SHAPES)('Domains — Organizational exclusivity ($label)', ({ org }) => {
  const domains = [...TECH, org];

  it('screenshot scenario: Cyber Security then Organizational Roles never yields two', async () => {
    await renderDomains(domains);

    click('Cyber Security');
    expect(isChecked('Cyber Security')).toBe(true);

    click('Organizational Roles');

    // Only Organizational Roles remains — the exact state from the bug report.
    expect(isChecked('Organizational Roles')).toBe(true);
    expect(isChecked('Cyber Security')).toBe(false);
    expect(countedText()).toBe('1 domain selected');
    expect(notice()).not.toBeNull();
    expect(notice().textContent).toMatch(MESSAGE);

    await submit();
    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });

  it('reverse order: Organizational Roles then Cyber Security is never mixed', async () => {
    await renderDomains(domains);

    click('Organizational Roles');
    click('Cyber Security');

    expect(isChecked('Cyber Security')).toBe(false);
    expect(isChecked('Organizational Roles')).toBe(true);
    expect(countedText()).toBe('1 domain selected');

    await submit();
    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });

  it('Organizational Roles then DevOps is never mixed', async () => {
    await renderDomains(domains);

    click('Organizational Roles');
    click('DevOps');

    expect(isChecked('DevOps')).toBe(false);
    expect(countedText()).toBe('1 domain selected');
    await submit();
    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });

  it('DevOps then Organizational Roles is never mixed', async () => {
    await renderDomains(domains);

    click('DevOps');
    click('Organizational Roles');

    expect(isChecked('DevOps')).toBe(false);
    expect(isChecked('Organizational Roles')).toBe(true);
    expect(countedText()).toBe('1 domain selected');
    await submit();
    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });

  it('Cyber Security then DevOps then Organizational Roles ends with one domain', async () => {
    await renderDomains(domains);

    click('Cyber Security');
    click('DevOps');
    expect(countedText()).toBe('2 domains selected');

    click('Organizational Roles');

    expect(isChecked('Cyber Security')).toBe(false);
    expect(isChecked('DevOps')).toBe(false);
    expect(isChecked('Organizational Roles')).toBe(true);
    expect(countedText()).toBe('1 domain selected');
    await submit();
    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });

  it('locks the other cards while Organizational Roles is selected', async () => {
    await renderDomains(domains);

    click('Organizational Roles');

    expect(card('Cyber Security').getAttribute('aria-disabled')).toBe('true');
    expect(card('DevOps').getAttribute('aria-disabled')).toBe('true');
  });

  it('starts a standalone Organizational assessment', async () => {
    await renderDomains(domains);

    click('Organizational Roles');
    await submit();

    expect(startBodies).toEqual([{ domain_ids: [org.id] }]);
  });
});

describe('Domains — ordinary multi-domain selection is unchanged', () => {
  const domains = [...TECH, ORG_SHAPES[0].org];

  it('two technical domains remain selectable and submittable', async () => {
    await renderDomains(domains);

    click('Cyber Security');
    click('DevOps');

    expect(isChecked('Cyber Security')).toBe(true);
    expect(isChecked('DevOps')).toBe(true);
    expect(countedText()).toBe('2 domains selected');
    expect(notice()).toBeNull();

    await submit();
    expect(startBodies).toEqual([
      { domain_ids: ['domain-cyber', 'domain-devops'] },
    ]);
  });

  it('still caps the selection at two domains', async () => {
    const second = {
      id: 'domain-ml',
      name: 'Machine Learning',
      assessmentScope: 'technical',
      questionCount: 1,
      durationMinutes: 10,
    };
    await renderDomains([...domains, second]);

    click('Cyber Security');
    click('DevOps');
    click('Machine Learning');

    expect(isChecked('Machine Learning')).toBe(false);
    expect(countedText()).toBe('2 domains selected');
  });

  it('releases the lock once Organizational Roles is deselected', async () => {
    await renderDomains(domains);

    click('Organizational Roles');
    click('Organizational Roles'); // deselect

    expect(card('Cyber Security').getAttribute('aria-disabled')).toBeNull();
    click('Cyber Security');
    click('DevOps');

    expect(countedText()).toBe('2 domains selected');
    await submit();
    expect(startBodies).toEqual([
      { domain_ids: ['domain-cyber', 'domain-devops'] },
    ]);
  });

  it('treats a domain explicitly scoped technical as technical', async () => {
    const explicit = { ...ORG_SHAPES[0].org, assessmentScope: 'technical' };
    await renderDomains([TECH[0], TECH[1], explicit]);

    click('Cyber Security');
    click('Organizational Roles');

    // Explicitly technical: ordinary multi-domain behaviour, backend still owns
    // the authoritative rejection.
    expect(countedText()).toBe('2 domains selected');
  });
});
