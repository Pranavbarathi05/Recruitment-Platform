import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, cleanup, fireEvent } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';
import { runCodeLocally } from '../execution/runner';
import { NETWORK_VIOLATION_MESSAGE, NETWORK_VIOLATION_REASON } from '../assessment/networkIntegrityMonitor';

vi.mock('../execution/runner', () => ({
  runCodeLocally: vi.fn(),
  isClientRunnable: (language) => language === 'python3',
}));

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }),
}));

vi.mock('../components/CodeEditor', () => ({
  default: ({ value }) => <textarea data-testid="code-editor" readOnly value={value} />,
}));

const FUTURE = new Date(Date.now() + 3600_000).toISOString();
const HELPER_URL = 'http://127.0.0.1:8765/network-check';
const INTERVAL_MS = 60_000;

const CONFIRMED = { target: '8.8.8.8', reachable: true, packetLoss: 0, rttMs: 9.1 };
const NO_REPLY = { target: '8.8.8.8', reachable: false, packetLoss: 100, rttMs: null };

// ---- Fullscreen API simulation (jsdom does not implement it) ----------------
function installFullscreenApi() {
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    get: () => document.documentElement,
  });
  Object.defineProperty(document, 'fullscreenEnabled', { configurable: true, value: true });
  document.documentElement.requestFullscreen = vi.fn(() => Promise.resolve());
  document.exitFullscreen = vi.fn(() => Promise.resolve());
}

function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

/**
 * fetch mock: API calls plus the loopback helper endpoint.
 *
 * @param monitored   value of `network_integrity_monitoring` on the attempt
 * @param helperReplies  queued helper replies; the last one repeats
 * @param helperFails    when true the helper endpoint is unreachable
 * @param submit        { status, deferred } control over POST /submit
 */
function mockFetch({
  monitored = true,
  helperReplies = [NO_REPLY],
  helperFails = false,
  active = true,
  submitStatus = 200,
  deferredSubmit = false,
} = {}) {
  let helperIndex = 0;
  let resolveSubmit = null;
  const fetchMock = vi.fn(async (url) => {
    const u = String(url);
    if (u.startsWith(HELPER_URL)) {
      if (helperFails) throw new TypeError('Failed to fetch');
      const reply = helperReplies[Math.min(helperIndex, helperReplies.length - 1)];
      helperIndex += 1;
      return jsonResponse(reply);
    }
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      if (!active) {
        return { ok: false, status: 400, json: async () => ({ detail: 'Attempt is not in progress' }) };
      }
      return jsonResponse({
        questions: [],
        answers: {},
        expires_at: FUTURE,
        network_integrity_monitoring: monitored,
      });
    }
    if (u.includes('/coding/attempt/attempt-1/problems')) {
      return jsonResponse({ problems: [], expires_at: FUTURE });
    }
    if (u.includes('/assessment/attempt/attempt-1/submit')) {
      if (deferredSubmit) {
        return new Promise((resolve) => {
          resolveSubmit = () => resolve({ ok: submitStatus === 200, status: submitStatus, json: async () => ({}) });
        });
      }
      return {
        ok: submitStatus === 200,
        status: submitStatus,
        json: async () => ({ detail: 'Submission failed' }),
      };
    }
    return jsonResponse({});
  });
  fetchMock.releaseSubmit = () => resolveSubmit && resolveSubmit();
  return fetchMock;
}

function renderWorkspace(fetchMock) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={['/assessment/attempt-1']}>
      <Routes>
        <Route path="/assessment/:attemptId" element={<McqTestRoute />} />
        <Route path="/assessment/:attemptId/submitted" element={<div>Submitted page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function McqTestRoute() {
  return <MCQTest />;
}

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
}

async function tick(ms) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Render an active, monitored attempt and let the initial load settle. */
async function renderActive(options = {}) {
  installFullscreenApi();
  const fetchMock = mockFetch(options);
  const view = renderWorkspace(fetchMock);
  await flush();
  expect(screen.getByRole('button', { name: /finish assessment/i })).toBeInTheDocument();
  return { fetchMock, view };
}

const helperCalls = (fetchMock) =>
  fetchMock.mock.calls.filter(([url]) => String(url).startsWith(HELPER_URL));

const submitCalls = (fetchMock) =>
  fetchMock.mock.calls.filter(([url]) => String(url).includes('/attempt-1/submit'));

const violationOverlay = () => screen.queryByTestId('network-violation-message');

beforeEach(() => {
  cleanup();
  runCodeLocally.mockReset();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('network-integrity monitoring in the assessment workspace', () => {
  it('1. does nothing at all when the frozen policy is off', async () => {
    const { fetchMock } = await renderActive({ monitored: false, helperReplies: [CONFIRMED] });

    await tick(INTERVAL_MS * 5);

    expect(helperCalls(fetchMock)).toHaveLength(0);
    expect(submitCalls(fetchMock)).toHaveLength(0);
    expect(violationOverlay()).not.toBeInTheDocument();
  });

  it('2. starts only after the attempt is active, not before', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [NO_REPLY] });

    // Loaded (active attempt) but not yet one interval in: no probe at all.
    expect(helperCalls(fetchMock)).toHaveLength(0);

    await tick(INTERVAL_MS - 1);
    expect(helperCalls(fetchMock)).toHaveLength(0);

    await tick(1);
    expect(helperCalls(fetchMock)).toHaveLength(1);
  });

  it('3. probes exactly once per interval (one timer, no duplicates)', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [NO_REPLY] });

    await tick(INTERVAL_MS * 4);

    expect(helperCalls(fetchMock)).toHaveLength(4);
  });

  it('4. a ping timeout leaves the assessment running', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [NO_REPLY] });

    await tick(INTERVAL_MS * 2);

    expect(violationOverlay()).not.toBeInTheDocument();
    expect(submitCalls(fetchMock)).toHaveLength(0);
    expect(screen.getByRole('button', { name: /finish assessment/i })).toBeInTheDocument();
  });

  it('5. an unreachable helper leaves the assessment running', async () => {
    const { fetchMock } = await renderActive({ helperFails: true });

    await tick(INTERVAL_MS * 3);

    expect(violationOverlay()).not.toBeInTheDocument();
    expect(submitCalls(fetchMock)).toHaveLength(0);
  });

  it('6. confirmed connectivity submits exactly once, with the termination reason', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [CONFIRMED] });

    await tick(INTERVAL_MS);

    const submits = submitCalls(fetchMock);
    expect(submits).toHaveLength(1);
    expect(JSON.parse(submits[0][1].body)).toEqual({ reason: NETWORK_VIOLATION_REASON });
    await flush();
    expect(screen.getByText('Submitted page')).toBeInTheDocument();
  });

  it('7. a violation locks the workspace and shows the candidate message', async () => {
    const { fetchMock, view } = await renderActive({
      helperReplies: [CONFIRMED],
      submitStatus: 500,
    });

    await tick(INTERVAL_MS);
    await flush();

    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByTestId('network-violation-message')).toHaveTextContent(NETWORK_VIOLATION_MESSAGE);
    expect(submitCalls(fetchMock)).toHaveLength(1);

    // The candidate message must not leak the mechanism.
    expect(screen.getByTestId('network-violation-message').textContent).not.toMatch(/ping|8\.8\.8\.8/i);

    // The underlying assessment is inert while the termination is in flight.
    const hidden = view.container.querySelector('[aria-hidden="true"]');
    expect(hidden).not.toBeNull();
    expect(hidden.hasAttribute('inert')).toBe(true);
  });

  it('8. monitoring stops after the violation: no second submission, ever', async () => {
    const { fetchMock } = await renderActive({
      helperReplies: [CONFIRMED],
      submitStatus: 500,
    });

    await tick(INTERVAL_MS);
    expect(submitCalls(fetchMock)).toHaveLength(1);

    await tick(INTERVAL_MS * 5);

    expect(submitCalls(fetchMock)).toHaveLength(1);
    expect(helperCalls(fetchMock)).toHaveLength(1);
  });

  it('9. a failed submission never claims success and offers an explicit retry', async () => {
    const { fetchMock } = await renderActive({
      helperReplies: [CONFIRMED],
      submitStatus: 500,
    });

    await tick(INTERVAL_MS);

    expect(screen.queryByText('Submitted page')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/could not be submitted/i);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /retry submission/i }));
    });
    expect(submitCalls(fetchMock)).toHaveLength(2);
  });

  it('10. a manual finish stops monitoring and beats the monitor to the submit', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [NO_REPLY] });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /finish assessment/i }));
    });
    expect(submitCalls(fetchMock)).toHaveLength(1);
    expect(JSON.parse(submitCalls(fetchMock)[0][1].body ?? 'null')).toBeNull();

    // Manual submit navigates away, which unmounts the workspace: the monitor
    // must not survive the attempt.
    await tick(INTERVAL_MS * 3);
    expect(helperCalls(fetchMock).length).toBeLessThanOrEqual(1);
    expect(submitCalls(fetchMock)).toHaveLength(1);
  });

  it('11. a violation racing an in-flight submission cannot submit twice', async () => {
    const { fetchMock } = await renderActive({
      helperReplies: [CONFIRMED],
      deferredSubmit: true,
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /finish assessment/i }));
    });
    expect(submitCalls(fetchMock)).toHaveLength(1);

    // The probe confirms connectivity while that submission is still in flight.
    await tick(INTERVAL_MS);

    expect(submitCalls(fetchMock)).toHaveLength(1);

    await act(async () => {
      fetchMock.releaseSubmit();
      await vi.advanceTimersByTimeAsync(1);
    });
    await flush();
    expect(screen.getByText('Submitted page')).toBeInTheDocument();
  });

  it('12. a finalized attempt is never monitored', async () => {
    const { fetchMock } = await renderActive({ active: false, helperReplies: [CONFIRMED] });

    await tick(INTERVAL_MS * 3);

    expect(helperCalls(fetchMock)).toHaveLength(0);
    expect(submitCalls(fetchMock)).toHaveLength(0);
  });

  it('13. unmounting the workspace releases the monitor timer', async () => {
    const { fetchMock, view } = await renderActive({ helperReplies: [NO_REPLY] });

    await tick(INTERVAL_MS);
    const before = helperCalls(fetchMock).length;

    view.unmount();
    await tick(INTERVAL_MS * 3);

    expect(helperCalls(fetchMock).length).toBe(before);
  });

  it('14. the assessment duration timer still works independently', async () => {
    const { fetchMock } = await renderActive({ helperReplies: [NO_REPLY] });

    // 60 seconds of assessment time elapses; the duration timer keeps its own
    // cadence and the monitoring interval is unaffected by it.
    await tick(INTERVAL_MS);
    expect(screen.getByText(/⏱/)).toBeInTheDocument();
    expect(helperCalls(fetchMock)).toHaveLength(1);
    expect(submitCalls(fetchMock)).toHaveLength(0);
  });
});
