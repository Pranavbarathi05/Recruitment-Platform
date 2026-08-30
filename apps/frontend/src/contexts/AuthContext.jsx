import { createContext, useState, useEffect } from 'react';
import { supabase } from '../lib/supabase';

// eslint-disable-next-line react-refresh/only-export-components
export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session on mount
    supabase.auth.getSession().then(({ data: { session: currentSession } }) => {
      setSession(currentSession);
      setUser(currentSession?.user ?? null);
      setLoading(false);
    });

    // Listen for auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, currentSession) => {
        setSession(currentSession);
        setUser(currentSession?.user ?? null);
      }
    );

    return () => subscription.unsubscribe();
  }, []);

  /**
   * Sign up a new candidate.
   *
   * All candidate data is passed as Supabase Auth user metadata.
   * The database trigger (handle_new_user) creates both profile and
   * candidate rows atomically — no frontend database insert needed.
   */
  const signUp = async ({ email, password, fullName, usn, semester, branch }) => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          full_name: fullName,
          usn,
          semester: parseInt(semester, 10),
          branch,
        },
      },
    });

    if (error) throw error;

    // If email confirmation is required, data.session will be null.
    // The profile + candidate are created by the trigger when the user
    // confirms their email and the auth.users row is finalized.
    const needsConfirmation = data.user && !data.session;

    return { needsConfirmation, user: data.user };
  };

  /**
   * Sign in with email and password.
   * No frontend database operations — just Supabase auth.
   */
  const signIn = async ({ email, password }) => {
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) throw error;
    return data;
  };

  /**
   * Sign out. Clears the Supabase session.
   */
  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
  };

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
