import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import MCQTest from './MCQTest';
import { runCodeLocally } from '../execution/runner';

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

const PROBLEM_ONE = {
  id: 'prob-1',
  title: 'Square It',
  difficulty: 'easy',
  points: 10,
  description: 'Return n squared.',
  function_name: 'solve',
  class_name: null,
  supported_languages: ['python3'],
  time_limit_ms: 2000,
  test_cases: [{ id: 'tc-1', arguments: [2], expected_output: 4 }],
};

// ---- Fullscreen API simulation (jsdom does not implement it) ----------------
let fullscreenElement = null;

function installFullscreenApi() {
  fullscreenElement = null;
  Object.defineProperty(document, 'fullscreenElement', {
    configurable: true,
    get: () => fullscreenElement,
  });
  document.documentElement.requestFullscreen = vi.fn(() => {
    fullscreenElement = document.documentElement;
    return Promise.resolve();
  });
  document.exitFullscreen = vi.fn(() => {
    fullscreenElement = null;
    return Promise.resolve();
  });
}

// A real fullscreen-exit: the element is gone, then the browser fires the event.
async function loseFullscreen() {
  fullscreenElement = null;
  await act(async () => {
    document.dispatchEvent(new Event('fullscreenchange'));
  });
}

async function restoreFullscreenEvent() {
  fullscreenElement = document.documentElement;
  await act(async () => {
    document.dispatchEvent(new Event('fullscreenchange'));
  });
}

// ---- fetch mock -------------------------------------------------------------
function mockFetch({ active = true, submitStatus = 200, submitOkStatus = true } = {}) {
  return vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/assessment/attempt/attempt-1/questions')) {
      if (!active) {
        return { ok: false, status: 400, json: async () => ({ detail: 'Attempt is not in progress' }) };
      }
      return { ok: true, status: 200, json: async () => ({ questions: [], answers: {}, expires_at: FUTURE }) };
    }
    if (u.includes('/coding/attempt/attempt-1/problems')) {
      return { ok: true, status: 200, json: async () => ({ problems: [PROBLEM_ONE], expires_at: FUTURE }) };
    }
    if (u.includes('/assessment/attempt/attempt-1/submit')) {
      return {
        ok: submitOkStatus,
        status: submitStatus,
        json: async () => ({ detail: 'Submission failed' }),
      };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  });
}

function renderWorkspace(fetchMock = mockFetch()) {
  globalThis.fetch = fetchMock;
  return render(
    <MemoryRouter initialEntries={['/assessment/attempt-1']}>
      <Routes>
        <Route path="/assessment/:attemptId" element={<MCQTest />} />
        <Route path="/assessment/:attemptId/submitted" element={<div>Submitted page</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function submitCalls(fetchMock) {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes('/attempt-1/submit'));
}

beforeEach(() => {
  cleanup();
  runCodeLocally.mockReset();
  installFullscreenApi();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function renderActive() {
  const fetchMock = mockFetch();
  const view = renderWorkspace(fetchMock);
  await screen.findByRole('button', { name: /run code/i });
  // Flush the mount-time requestFullscreen promise so fullscreen state settles.
  await act(async () => { await Promise.resolve(); });
  return { fetchMock, view };
}

describe('Assessment fullscreen enforcement', () => {
  it('1. attempts fullscreen on initialisation when the API is available', async () => {
    await renderActive();
    expect(document.documentElement.requestFullscreen).toHaveBeenCalledTimes(1);
  });

  it('2. losing fullscreen shows the blocking overlay', async () => {
    await renderActive();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();

    await loseFullscreen();

    expect(await screen.findByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText('Fullscreen Required')).toBeInTheDocument();
  });

  it('3. the overlay makes the underlying assessment inert', async () => {
    const { view } = await renderActive();
    await loseFullscreen();

    const hidden = view.container.querySelector('[aria-hidden="true"]');
    expect(hidden).not.toBeNull();
    expect(hidden.className).toMatch(/pointer-events-none/);
    expect(hidden.hasAttribute('inert')).toBe(true);
    // The underlying "Run Code" control lives inside the inert subtree (it is
    // removed from the accessibility tree while inert, so query the DOM).
    const buttons = Array.from(hidden.querySelectorAll('button'));
    expect(buttons.some((b) => /run code/i.test(b.textContent || ''))).toBe(true);
  });

  it('4. the countdown starts at exactly 15 seconds', async () => {
    await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();

    expect(screen.getByTestId('fullscreen-countdown')).toHaveTextContent('15');
  });

  it('5. the countdown decrements once per second', async () => {
    await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();

    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByTestId('fullscreen-countdown')).toHaveTextContent('14');
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByTestId('fullscreen-countdown')).toHaveTextContent('13');
  });

  it('6. clicking "Return to Fullscreen" requests fullscreen again', async () => {
    await renderActive();
    await loseFullscreen();

    document.documentElement.requestFullscreen.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Return to Fullscreen' }));

    expect(document.documentElement.requestFullscreen).toHaveBeenCalledTimes(1);
  });

  it('7. a successful return hides the overlay and clears the timer', async () => {
    await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Return to Fullscreen' }));
    });

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    // Countdown stopped: advancing time must not bring the overlay back.
    const before = vi.getTimerCount();
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(vi.getTimerCount()).toBeLessThanOrEqual(before);
  });

  it('8. a failed return keeps the overlay, the error, and the running timer', async () => {
    await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();

    await act(async () => { vi.advanceTimersByTime(3000); });
    expect(screen.getByTestId('fullscreen-countdown')).toHaveTextContent('12');

    document.documentElement.requestFullscreen = vi.fn(() =>
      Promise.reject(new Error('denied'))
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Return to Fullscreen' }));
    });

    expect(screen.getByRole('alertdialog')).toBeInTheDocument();
    expect(screen.getByText(/Fullscreen could not be restored/)).toBeInTheDocument();
    // The timer was NOT reset — it keeps counting down from 12.
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.getByTestId('fullscreen-countdown')).toHaveTextContent('11');
  });

  it('9. reaching zero submits exactly once through the existing endpoint', async () => {
    const { fetchMock } = await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();

    await act(async () => { vi.advanceTimersByTime(15000); });
    await act(async () => { await Promise.resolve(); });
    expect(submitCalls(fetchMock)).toHaveLength(1);

    // Let the navigation settle on real timers before asserting the route.
    vi.useRealTimers();
    expect(await screen.findByText('Submitted page')).toBeInTheDocument();
  });

  it('10. a manual submission prevents the automatic fullscreen-timeout submission', async () => {
    const { fetchMock } = await renderActive();

    fireEvent.click(screen.getByRole('button', { name: /finish assessment/i }));
    expect(await screen.findByText('Submitted page')).toBeInTheDocument();
    expect(submitCalls(fetchMock)).toHaveLength(1);

    // Once finalized, a (simulated) fullscreen exit cannot submit again.
    await loseFullscreen();
    expect(submitCalls(fetchMock)).toHaveLength(1);
  });

  it('11. unmount removes the fullscreenchange listener, clears timers, exits fullscreen', async () => {
    const removeSpy = vi.spyOn(document, 'removeEventListener');
    const { view } = await renderActive();
    vi.useFakeTimers();
    await loseFullscreen();
    // Candidate is back in fullscreen when the component unmounts.
    await restoreFullscreenEvent();

    view.unmount();

    expect(removeSpy).toHaveBeenCalledWith('fullscreenchange', expect.any(Function));
    expect(document.exitFullscreen).toHaveBeenCalled();
    // The exit interval is gone.
    expect(vi.getTimerCount()).toBe(0);
  });

  it('12. a submitted/scored attempt never activates fullscreen enforcement', async () => {
    const fetchMock = mockFetch({ active: false });
    renderWorkspace(fetchMock);

    await screen.findByRole('button', { name: /run code/i });

    expect(document.documentElement.requestFullscreen).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('13. the existing assessment duration timer keeps working independently', async () => {
    await renderActive();

    // No fullscreen exit → no overlay, and the shared clock is rendered.
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    const clock = screen.getByText(/⏱/);
    expect(clock).toBeInTheDocument();

    vi.useFakeTimers();
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('14. rerenders do not create duplicate listeners or timers', async () => {
    const addSpy = vi.spyOn(document, 'addEventListener');
    await renderActive();

    // Force a re-render through normal interaction.
    runCodeLocally.mockResolvedValue({ all_passed: true, results: [] });
    fireEvent.click(screen.getByRole('button', { name: /run code/i }));

    const fsListeners = addSpy.mock.calls.filter(([type]) => type === 'fullscreenchange');
    expect(fsListeners).toHaveLength(1);

    await loseFullscreen();
    const overlays = screen.getAllByRole('alertdialog');
    expect(overlays).toHaveLength(1);
  });
});
