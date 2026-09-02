import { createContext, useState, useEffect, useCallback } from 'react';
import { authSignup, authLogin, authLogout, authGetMe, getStoredAccessToken } from '../lib/api';

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  /**
   * On mount: check for an existing stored access token and validate it
   * by calling the backend /auth/me endpoint.
   *
   * This replaces the previous supabase.auth.getSession() call.
   */
  useEffect(() => {
    const restoreSession = async () => {
      const token = getStoredAccessToken();
      if (!token) {
        setLoading(false);
        return;
      }

      try {
        const me = await authGetMe();
        setUser({ id: me.id, email: me.email });
        setSession({ access_token: token });
      } catch {
        // Token invalid/expired — cleared by apiRequest on 401
        setUser(null);
        setSession(null);
      } finally {
        setLoading(false);
      }
    };

    restoreSession();
  }, []);

  /**
   * Sign up a new candidate.
   *
   * All candidate data is passed to the backend, which forwards it to
   * Supabase Auth as user metadata. The database trigger (handle_new_user)
   * creates both profile and candidate rows atomically.
   */
  const signUp = useCallback(async ({ email, password, fullName, usn, semester, branch }) => {
    const data = await authSignup({ email, password, fullName, usn, semester, branch });

    if (data.needsConfirmation) {
      return { needsConfirmation: true, user: data.user };
    }

    // Session was returned — user is signed in
    if (data.session?.access_token) {
      setUser(data.user);
      setSession({ access_token: data.session.access_token });
    }

    return { needsConfirmation: false, user: data.user };
  }, []);

  /**
   * Sign in with email and password.
   */
  const signIn = useCallback(async ({ email, password }) => {
    const data = await authLogin({ email, password });

    if (data.session?.access_token) {
      setUser(data.user);
      setSession({ access_token: data.session.access_token });
    }

    return data;
  }, []);

  /**
   * Sign out. Clears local tokens and notifies the backend.
   */
  const signOut = useCallback(async () => {
    await authLogout();
    setUser(null);
    setSession(null);
  }, []);

  const value = {
    user,
    session,
    loading,
    signUp,
    signIn,
    signOut,
    isAuthenticated: !!session,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}
