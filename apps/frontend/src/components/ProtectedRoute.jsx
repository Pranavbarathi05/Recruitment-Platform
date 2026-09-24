import { Navigate, useParams } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * ProtectedRoute Component
 *
 * Wraps routes that require authentication.
 * Shows a loading spinner while checking session.
 * Redirects to /login if not authenticated — EXCEPT for an in-flight
 * assessment workspace (/assessment/:attemptId) whose attempt id matches
 * the server-verified assessment-scoped authorization: a candidate must
 * never lose an active attempt to login-session expiry.
 */
export default function ProtectedRoute({ children }) {
  const { isAuthenticated, loading, assessmentAccess } = useAuth();
  const { attemptId } = useParams();

  if (loading) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500"></div>
      </div>
    );
  }

  if (!isAuthenticated) {
    // Assessment-scoped access: only the EXACT attempt the server authorized
    // is admitted — any other route (or a different attempt id) still goes
    // to /login. The server independently re-validates every request.
    if (attemptId && assessmentAccess?.attemptId === attemptId) {
      return children;
    }
    return <Navigate to="/login" replace />;
  }

  return children;
}
