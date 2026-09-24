import { render, screen, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AuthProvider, SESSION_EXPIRED_NOTICE } from './AuthContext';
import { useAuth } from '../hooks/useAuth';

/**
 * Session-expiry tests for the 2-hour login session.
 *
 * The SERVER owns expiry (JWT exp + the backend's 2-hour iat ceiling);
 * AuthProvider only re-asks /auth/me periodically / on focus and clears
 * local state on 401 so ProtectedRoute returns the user to /login.
 * These tests pin that contract:
 *   - a live session survives revalidation while the server says ok,
 *   - a 401 from the server ends the session and sets the login notice,
 *   - anonymous visitors (mount-time 401) are never shown the notice,
 *   - sessionExpired() (used by pages on any mid-session 401) clears state,
 *   - a successful sign-in clears a previous expiry notice.
 */

function Probe() {
  const {
    isAuthenticated,
    sessionExpired,
    sessionNotice,
    loading,
    assessmentAccess,
  } = useAuth();
  return (
    <div>
      <span data-testid="auth">{String(isAuthenticated)}</span>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="notice">{sessionNotice || ''}</span>
      <span data-testid="assessment">{assessmentAccess?.attemptId || ''}</span>
      <button type="button" onClick={() => sessionExpired()}>
        expire
      </button>
    </div>
  );
}

const okMe = () =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ id: 'user-1', email: 'a@b.com' }),
  });

const unauthorizedMe = () =>
  Promise.resolve({
    ok: false,
    status: 401,
    json: () => Promise.resolve({ detail: 'Not authenticated' }),
  });

const okAccess = (attemptId) =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ attempt_id: attemptId }),
  });

const unauthorizedAccess = () =>
  Promise.resolve({
    ok: false,
    status: 401,
    json: () => Promise.resolve({ detail: 'No active assessment access' }),
  });

describe('AuthContext session revalidation', () => {
  let meResponses;
  let accessResponses;
  let fetchMock;

  beforeEach(() => {
    meResponses = [];
    accessResponses = [];
    fetchMock = vi.fn((url) => {
      if (String(url).includes('/auth/assessment-access')) {
        const next = accessResponses.shift();
        return next ? next() : unauthorizedAccess();
      }
      if (String(url).includes('/auth/me')) {
        const next = meResponses.shift();
        return next ? next() : okMe();
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const renderProvider = async () => {
    let utils;
    await act(async () => {
      utils = render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      );
    });
    return utils;
  };

  it('restores a live session from the server on mount', async () => {
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');
    expect(screen.getByTestId('notice').textContent).toBe('');
  });

  it('stays authenticated across a successful periodic revalidation', async () => {
    meResponses = [okMe]; // consume mount check
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');

    // Next periodic check (60s) also succeeds → still authenticated.
    meResponses = [okMe];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000);
    });
    expect(screen.getByTestId('auth').textContent).toBe('true');
    expect(screen.getByTestId('notice').textContent).toBe('');
  });

  it('clears the session and sets the notice when the server reports 401', async () => {
    meResponses = [okMe];
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');

    // The periodic revalidation hits an expired/ceiling-exceeded token.
    meResponses = [unauthorizedMe];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000);
    });

    // waitFor is deliberately NOT used: it polls with real timers, which
    // never fire while fake timers are installed (the act() above has
    // already flushed the state update).
    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('notice').textContent).toBe(
      SESSION_EXPIRED_NOTICE
    );
  });

  it('revalidates when the tab regains focus', async () => {
    meResponses = [okMe];
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');

    meResponses = [unauthorizedMe];
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });

    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('notice').textContent).toBe(
      SESSION_EXPIRED_NOTICE
    );
  });

  it('does not show the expiry notice to anonymous visitors', async () => {
    // Mount-time 401 = simply not signed in.
    meResponses = [unauthorizedMe];
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('notice').textContent).toBe('');
  });

  it('does not run revalidation while signed out', async () => {
    meResponses = [unauthorizedMe];
    await renderProvider();
    const fetchCalls = fetchMock.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    });
    expect(fetchMock.mock.calls.length).toBe(fetchCalls);
  });

  it('sessionExpired() clears the session and sets the notice immediately', async () => {
    meResponses = [okMe];
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');

    await act(async () => {
      screen.getByText('expire').click();
    });
    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('notice').textContent).toBe(
      SESSION_EXPIRED_NOTICE
    );
  });
});

/**
 * Assessment-scoped authorization: an in-flight attempt must survive
 * login-session expiry (server-verified via /auth/assessment-access),
 * and must stop existing the moment the attempt expires or is submitted.
 */
describe('AuthContext assessment-scoped access', () => {
  let meResponses;
  let accessResponses;
  let fetchMock;

  beforeEach(() => {
    meResponses = [];
    accessResponses = [];
    fetchMock = vi.fn((url) => {
      if (String(url).includes('/auth/assessment-access')) {
        const next = accessResponses.shift();
        return next ? next() : unauthorizedAccess();
      }
      if (String(url).includes('/auth/me')) {
        const next = meResponses.shift();
        return next ? next() : okMe();
      }
      return Promise.resolve({
        ok: false,
        status: 404,
        json: () => Promise.resolve({}),
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const renderProvider = async () => {
    let utils;
    await act(async () => {
      utils = render(
        <AuthProvider>
          <Probe />
        </AuthProvider>
      );
    });
    // Drain init()'s second fetch chain (auth/me → assessment-access probe):
    // the mount effect's microtasks can outlive the act() above.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    return utils;
  };

  it('recovers into assessment access when the session is already dead (refresh)', async () => {
    // Mount: /auth/me 401 (session expired) but the capability cookie
    // still authorizes a live attempt → resume without a session.
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderProvider();

    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('assessment').textContent).toBe('attempt-123');
    // Anonymous-at-mount style 401 must NOT claim a session expired…
    expect(screen.getByTestId('notice').textContent).toBe('');
    // …but the provider is now actively revalidating the attempt.
    expect(
      fetchMock.mock.calls.some(([u]) =>
        String(u).includes('/auth/assessment-access')
      )
    ).toBe(true);
  });

  it('keeps the in-flight attempt when the session dies mid-use', async () => {
    meResponses = [okMe]; // mount: signed in
    await renderProvider();
    expect(screen.getByTestId('auth').textContent).toBe('true');

    // Periodic check: session 401 → user cleared, but the assessment
    // access probe succeeds → the attempt is NOT lost.
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000);
    });

    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(screen.getByTestId('assessment').textContent).toBe('attempt-123');
    expect(screen.getByTestId('notice').textContent).toBe(
      SESSION_EXPIRED_NOTICE
    );
  });

  it('drops assessment access when the attempt ends (expired or submitted)', async () => {
    // Session dead, attempt live on mount.
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderProvider();
    expect(screen.getByTestId('assessment').textContent).toBe('attempt-123');

    // Next revalidation: server says no live attempt (401) → clear everything.
    accessResponses = [unauthorizedAccess];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByTestId('assessment').textContent).toBe('');
    expect(screen.getByTestId('auth').textContent).toBe('false');
  });

  it('revalidates periodically while only assessment access remains', async () => {
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderProvider();
    const callsAfterMount = fetchMock.mock.calls.length;

    // The interval must keep running (hasAnyAccess includes assessment access).
    accessResponses = [() => okAccess('attempt-123')];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 1000);
    });
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterMount);
    expect(screen.getByTestId('assessment').textContent).toBe('attempt-123');
  });

  it('sessionExpired() clears the assessment access too', async () => {
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderProvider();
    expect(screen.getByTestId('assessment').textContent).toBe('attempt-123');

    await act(async () => {
      screen.getByText('expire').click();
    });
    expect(screen.getByTestId('assessment').textContent).toBe('');
    expect(screen.getByTestId('auth').textContent).toBe('false');
  });
});
