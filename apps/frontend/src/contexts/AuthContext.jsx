import { createContext, useState, useEffect, useCallback } from 'react';

const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
  const [loading, setLoading] = useState(true);

  /**
   * On mount: restore session from cookie + fetch CSRF token.
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
        } else {
          setUser(null);
        }


      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    init();
  }, []);

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

    setUser(data.user);

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

    setUser(data.user);

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
    setUser(null);
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
    isAuthenticated: !!user,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}
