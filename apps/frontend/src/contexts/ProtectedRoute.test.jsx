import { render, screen, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AuthProvider } from './AuthContext';
import ProtectedRoute from '../components/ProtectedRoute';

/**
 * ProtectedRoute admits the assessment workspace when (and ONLY when) the
 * server-verified assessment-scoped access matches the route's attempt id —
 * so a candidate can refresh/resume an in-flight attempt after the 2-hour
 * login session expired, without opening any other route.
 */

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

describe('ProtectedRoute assessment-scoped access', () => {
  let meResponses;
  let accessResponses;

  beforeEach(() => {
    meResponses = [];
    accessResponses = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        if (String(url).includes('/auth/assessment-access')) {
          const next = accessResponses.shift();
          return next ? next() : unauthorizedAccess();
        }
        if (String(url).includes('/auth/me')) {
          const next = meResponses.shift();
          return next ? next() : unauthorizedMe();
        }
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({}),
        });
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const renderAt = async (path) => {
    let utils;
    await act(async () => {
      utils = render(
        <MemoryRouter initialEntries={[path]}>
          <AuthProvider>
            <Routes>
              <Route
                path="/assessment/:attemptId"
                element={
                  <ProtectedRoute>
                    <div data-testid="workspace">workspace</div>
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin"
                element={
                  <ProtectedRoute>
                    <div data-testid="admin">admin</div>
                  </ProtectedRoute>
                }
              />
              <Route path="/login" element={<div data-testid="login">login</div>} />
            </Routes>
          </AuthProvider>
        </MemoryRouter>
      );
    });
    // Drain the mount effect's full chain (auth/me → assessment-access probe).
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    return utils;
  };

  it('renders the workspace when the session is live', async () => {
    meResponses = [okMe];
    await renderAt('/assessment/attempt-123');
    expect(screen.getByTestId('workspace')).toBeTruthy();
  });

  it('redirects to /login with no session and no assessment access', async () => {
    meResponses = [unauthorizedMe];
    await renderAt('/assessment/attempt-123');
    expect(screen.getByTestId('login')).toBeTruthy();
    expect(screen.queryByTestId('workspace')).toBeNull();
  });

  it('resumes the in-flight attempt after session expiry (matching id)', async () => {
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderAt('/assessment/attempt-123');
    expect(screen.getByTestId('workspace')).toBeTruthy();
    expect(screen.queryByTestId('login')).toBeNull();
  });

  it('rejects a different attempt id than the server authorized', async () => {
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderAt('/assessment/some-other-attempt');
    expect(screen.getByTestId('login')).toBeTruthy();
    expect(screen.queryByTestId('workspace')).toBeNull();
  });

  it('never opens non-assessment routes on assessment access alone', async () => {
    meResponses = [unauthorizedMe];
    accessResponses = [() => okAccess('attempt-123')];
    await renderAt('/admin');
    expect(screen.getByTestId('login')).toBeTruthy();
    expect(screen.queryByTestId('admin')).toBeNull();
  });
});
