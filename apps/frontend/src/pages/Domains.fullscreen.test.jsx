import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Domains from './Domains';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

const DOMAINS = [
  {
    id: 'domain-1',
    name: 'DevOps',
    description: 'Pipelines and infrastructure.',
    questionCount: 4,
    durationMinutes: 20,
  },
];

function installFullscreenApi() {
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    value: null,
    writable: true,
  });
  document.documentElement.requestFullscreen = vi.fn(() => Promise.resolve());
}

/** Renders the page and lets the domains fetch settle. */
async function renderDomains(fetchMock) {
  globalThis.fetch = fetchMock;
  const view = render(
    <MemoryRouter initialEntries={['/domains']}>
      <Routes>
        <Route path="/domains" element={<Domains />} />
        <Route path="/assessment/:attemptId" element={<div>Assessment workspace</div>} />
      </Routes>
    </MemoryRouter>
  );
  await screen.findByText('DevOps');
  return view;
}

function selectDomain() {
  fireEvent.click(screen.getByText('DevOps'));
}

function startButton() {
  return screen.getByRole('button', { name: /start assessment/i });
}

let startResolvers;

function mockFetch() {
  startResolvers = [];
  return vi.fn((url) => {
    const u = String(url);
    if (u.includes('/questions/domains')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => DOMAINS });
    }
    if (u.includes('/assessment/start')) {
      // Held open so we can prove the fullscreen request happens from the
      // click itself, not after the start request settles.
      return new Promise((resolve) => {
        startResolvers.push(() =>
          resolve({ ok: true, status: 200, json: async () => ({ attempt_id: 'attempt-9' }) })
        );
      });
    }
    return Promise.resolve({ ok: true, status: 200, json: async () => ({}) });
  });
}

beforeEach(() => {
  cleanup();
  installFullscreenApi();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Domains — starting an assessment enters fullscreen from the click', () => {
  it('requests fullscreen inside the click handler, before the start request resolves', async () => {
    const fetchMock = mockFetch();
    await renderDomains(fetchMock);
    selectDomain();

    fireEvent.click(startButton());

    // The request went out synchronously from the gesture — the start request
    // has not even been answered yet.
    expect(document.documentElement.requestFullscreen).toHaveBeenCalledTimes(1);
    expect(startResolvers).toHaveLength(1);

    await act(async () => { startResolvers.forEach((r) => r()); });
    expect(await screen.findByText('Assessment workspace')).toBeInTheDocument();
  });

  it('does not re-request fullscreen when already in fullscreen', async () => {
    document.fullscreenElement = document.documentElement;
    const fetchMock = mockFetch();
    await renderDomains(fetchMock);
    selectDomain();

    fireEvent.click(startButton());

    expect(document.documentElement.requestFullscreen).not.toHaveBeenCalled();
    await act(async () => { startResolvers.forEach((r) => r()); });
  });

  it('a rejected fullscreen request never blocks or fails the assessment start', async () => {
    document.documentElement.requestFullscreen = vi.fn(() =>
      Promise.reject(new Error('API can only be initiated by a user gesture'))
    );
    const fetchMock = mockFetch();
    await renderDomains(fetchMock);
    selectDomain();

    fireEvent.click(startButton());

    expect(startResolvers).toHaveLength(1);
    await act(async () => { startResolvers.forEach((r) => r()); });

    expect(await screen.findByText('Assessment workspace')).toBeInTheDocument();
    expect(screen.queryByText(/fullscreen/i)).not.toBeInTheDocument();
  });

  it('a browser without the Fullscreen API still starts the assessment', async () => {
    document.documentElement.requestFullscreen = undefined;
    const fetchMock = mockFetch();
    await renderDomains(fetchMock);
    selectDomain();

    fireEvent.click(startButton());

    await act(async () => { startResolvers.forEach((r) => r()); });
    expect(await screen.findByText('Assessment workspace')).toBeInTheDocument();
  });
});
