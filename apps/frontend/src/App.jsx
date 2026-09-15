import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { Navbar } from './components';
import ProtectedRoute from './components/ProtectedRoute';
import { Landing, Login, Domains, Dashboard, Signup, MCQTest, Results, SubmissionConfirmed, AdminPanel, AdminResults, AdminCoding, AdminDescriptive, AdminHandsOn, Instructions } from './pages';

/**
 * Main App Component
 *
 * Sets up routing for the DSC Recruitment Platform.
 * Initializes theme from localStorage on first load.
 *
 * Routes:
 * - / : Landing page (public)
 * - /login : Login page (public)
 * - /signup : Signup page (public)
 * - /domains : Domains page (protected)
 * - /dashboard : Dashboard page (protected)
 * - /test-editor : CodeEditor test page (protected)
 * - /test/:domainId : CodeEditor test page (protected)
 */
function App() {
  useEffect(() => {
    // Initialize theme from localStorage (default to dark)
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(savedTheme);
  }, []);

  return (
    <AuthProvider>
      <Router>
        <div className="flex flex-col min-h-screen bg-theme-primary text-theme-primary">
          <Navbar />
          <main className="flex-1 min-h-0 flex flex-col">
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route
                path="/domains"
                element={
                  <ProtectedRoute>
                    <Domains />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute>
                    <Dashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/assessment/:attemptId"
                element={
                  <ProtectedRoute>
                    <MCQTest />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/assessment/:attemptId/submitted"
                element={
                  <ProtectedRoute>
                    <SubmissionConfirmed />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/assessment/:attemptId/results"
                element={
                  <ProtectedRoute>
                    <Results />
                  </ProtectedRoute>
                }
              />

              <Route
                path="/admin"
                element={
                  <ProtectedRoute>
                    <AdminPanel />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/assessments/:attemptId/results"
                element={
                  <ProtectedRoute>
                    <AdminResults />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/coding"
                element={
                  <ProtectedRoute>
                    <AdminCoding />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/descriptive"
                element={
                  <ProtectedRoute>
                    <AdminDescriptive />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/admin/hands-on"
                element={
                  <ProtectedRoute>
                    <AdminHandsOn />
                  </ProtectedRoute>
                }
              />
              <Route path="/instructions" element={<Instructions />} />
            </Routes>
          </main>
        </div>
      </Router>
    </AuthProvider>
  );
}

export default App;
