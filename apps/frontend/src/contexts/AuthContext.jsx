import { createContext, useState, useEffect, useCallback, useRef } from 'react';

const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// How often the live session is re-validated against the server while a
// user is signed in. This is NOT a client-side logout timer: the server
// (/auth/me → JWT exp + the backend's 2-hour absolute iat ceiling) is always
// the authority — we merely re-ask it so an expired session is detected and
// the user is returned to /login cleanly instead of hitting silent 401s.
const SESSION_REVALIDATE_INTERVAL_MS = 60 * 1000;

export const SESSION_EXPIRED_NOTICE =
  'Your session has expired. Please sign in again — your assessment attempt is saved and will be resumed.';

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);

/**
 * Authentication Provider — Cookie-only auth.
 *
 * The browser NEVER has access to the JWT.
 * Authentication is purely through HttpOnly cookies set by FastAPI.
 * CSRF protection uses double-submit token pattern.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // Assessment-scoped authorization: the server-verified id of a LIVE
  // (owned, in_progress, unexpired) attempt. Survives login-session expiry
  // so an in-flight assessment is never lost; set ONLY by the server's
  // GET /auth/assessment-access, never by client-side state.
  const [assessmentAccess, setAssessmentAccess] = useState(null);
  const [loading, setLoading] = useState(true);
  // One-shot banner shown on /login after a live session expired.
  const [sessionNotice, setSessionNotice] = useState(null);
  // Whether a session was live at last check — guards the expiry notice so
  // anonymous visitors hitting /auth/me's normal 401 are never told their
  // "session expired".
  const hadSessionRef = useRef(false);

  /**
   * Ask the server whether an assessment-scoped authorization is currently
   * active (capability cookie validated against the attempt row). True only
   * while the attempt is owned, in_progress and unexpired.
   */
  const probeAssessmentAccess = useCallback(async () => {
    try {
      const resp = await fetch(`${apiUrl}/auth/assessment-access`, {
        credentials: 'include',
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.attempt_id) {
          setAssessmentAccess({ attemptId: data.attempt_id });
          return true;
        }
      }
    } catch {
      /* network blip — leave state unchanged */
    }
    return false;
  }, []);

  /**
   * On mount: restore session from cookie.
   */
  useEffect(() => {
    const init = async () => {
      try {
        // Restore session from cookie
        const meResp = await fetch(`${apiUrl}/auth/me`, {
          credentials: 'include',
        });
        if (meResp.ok) {
          const data = await meResp.json();
          setUser(data);
          hadSessionRef.current = true;
        } else {
          setUser(null);
          // Login session missing/expired — an in-flight assessment may
          // still be authorized by the assessment capability cookie.
          await probeAssessmentAccess();
        }


      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    init();
  }, [probeAssessmentAccess]);

  /**
   * The login session is gone — but assessment-scoped access (if any) is
   * deliberately KEPT: an in-flight attempt must survive session expiry.
   * Announces the expiry only when a session actually existed.
   */
  const expireUserSession = useCallback(() => {
    if (hadSessionRef.current) {
      hadSessionRef.current = false;
      setSessionNotice(SESSION_EXPIRED_NOTICE);
    }
    setUser(null);
  }, []);

  /**
   * Nothing is authorized any more: no login session AND no live assessment
   * (or an explicit sign-out). ProtectedRoute then returns to /login.
   */
  const expireSession = useCallback(() => {
    expireUserSession();
    setAssessmentAccess(null);
  }, [expireUserSession]);

  /**
   * Server-authoritative session re-validation. The backend rejects expired
   * JWTs (exp) and any token older than the 2-hour absolute ceiling (iat),
   * so a 401 here means the session is genuinely over — clear local state so
   * ProtectedRoute returns the user to /login. Transient network errors keep
   * the current state (never log a user out on a blip).
   */
  const validateSession = useCallback(async () => {
    try {
      if (user) {
        const resp = await fetch(`${apiUrl}/auth/me`, { credentials: 'include' });
        if (resp.ok) {
          const data = await resp.json();
          hadSessionRef.current = true;
          setUser(data);
          return;
        }
        if (resp.status === 401) {
          // Login session over — an in-flight assessment may still be
          // authorized server-side: probe before settling on /login.
          expireUserSession();
          await probeAssessmentAccess();
          return;
        }
        // Other statuses (5xx etc.): keep state, retry on the next tick.
        return;
      }

      if (assessmentAccess) {
        const resp = await fetch(`${apiUrl}/auth/assessment-access`, {
          credentials: 'include',
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.attempt_id) {
            setAssessmentAccess({ attemptId: data.attempt_id });
          } else {
            expireSession();
          }
        } else if (resp.status === 401) {
          // Attempt over (expired or submitted) or access revoked: no
          // authorization remains → clean return to /login.
          expireSession();
        }
        // 5xx / blips: keep state, retry on the next tick.
      }
    } catch {
      /* network blip — keep current state */
    }
  }, [user, assessmentAccess, expireUserSession, expireSession, probeAssessmentAccess]);

  // Re-validate while EITHER a login session OR an assessment-scoped
  // authorization exists, so a capability outliving the session keeps being
  // re-checked server-side and drops the moment the attempt ends.
  const isAuthenticated = !!user;
  const hasAnyAccess = !!user || !!assessmentAccess;
  useEffect(() => {
    if (!hasAnyAccess) return undefined;
    const id = setInterval(() => { validateSession(); }, SESSION_REVALIDATE_INTERVAL_MS);
    const onFocus = () => { validateSession(); };
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(id);
      window.removeEventListener('focus', onFocus);
    };
  }, [hasAnyAccess, validateSession]);

  /**
   * Sign up a new candidate.
   */
  const signUp = useCallback(async ({ email, password, fullName, usn, semester, branch }) => {
    const resp = await fetch(`${apiUrl}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        email,
        password,
        full_name: fullName,
        usn,
        semester: parseInt(semester, 10),
        branch,
      }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || 'Signup failed');
    }

    setSessionNotice(null);
    setUser(data.user);
    hadSessionRef.current = true;

    if (data.user?.needs_confirmation) {
      return { needsConfirmation: true, user: data.user };
    }

    return { needsConfirmation: false, user: data.user };
  }, []);

  /**
   * Sign in with email and password.
   */
  const signIn = useCallback(async ({ email, password }) => {
    const resp = await fetch(`${apiUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ email, password }),
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || 'Login failed');
    }

    setSessionNotice(null);
    setUser(data.user);
    hadSessionRef.current = true;

    return data;
  }, []);

  /**
   * Sign out — clear session cookie.
   */
  const signOut = useCallback(async () => {
    try {
      const headers = { 'Content-Type': 'application/json' };
      const match = document.cookie.match(/dsc_csrf=([^;]+)/);
      if (match) headers['X-CSRF-Token'] = match[1];

      await fetch(`${apiUrl}/auth/logout`, {
        method: 'POST',
        headers,
        credentials: 'include',
      });
    } catch {
      // Non-critical — clear local state regardless
    }
    hadSessionRef.current = false;
    setSessionNotice(null);
    setUser(null);
    setAssessmentAccess(null);
  }, []);

  /**
   * Get headers for authenticated API requests.
   * Cookie-based auth — browser sends session cookie automatically.
   * Includes CSRF token from cookie for state-changing requests.
   */
  const getAuthHeaders = useCallback(() => {
    const headers = { 'Content-Type': 'application/json' };
    const match = document.cookie.match(/dsc_csrf=([^;]+)/);
    if (match) {
      headers['X-CSRF-Token'] = match[1];
    }
    return headers;
  }, []);

  const value = {
    user,
    loading,
    signUp,
    signIn,
    signOut,
    getAuthHeaders,
    // Called by pages when an API call returns 401 mid-session: clears the
    // session immediately so ProtectedRoute redirects to /login cleanly.
    sessionExpired: expireSession,
    sessionNotice,
    isAuthenticated,
    // { attemptId } while an assessment-scoped authorization is live — lets
    // ProtectedRoute admit the in-flight workspace after session expiry.
    assessmentAccess,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}
