import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { Navbar } from './components';
import ProtectedRoute from './components/ProtectedRoute';
import { Landing, Login, Domains, Dashboard, Signup, MCQTest, Results, SubmissionConfirmed, AdminPanel, AdminResults, AdminCoding, AdminDescriptive, AdminHandsOn, AdminModules, Instructions } from './pages';

/**
 * The live assessment workspace (/assessment/:attemptId) is a viewport-locked
 * IDE: it owns its scrolling and sizes Monaco with `h-full`.
 *
 * Percentage heights only resolve against a *definite* containing block. With
 * the usual `min-h-screen` shell (height: auto, min-height: 100vh) every
 * `height: 100%` inside it computes to `auto`, so the editor containers
 * collapsed — the WASM/Pandas editor rendered ~5px tall (looked blank) and the
 * coding editor grew to its content height and blew the page up. Locking the
 * shell to the viewport for this route only restores the definite chain;
 * every other route keeps the document-scrolling `min-h-screen` shell.
 */
const ASSESSMENT_WORKSPACE_PATH = /^\/assessment\/[^/]+\/?$/;

function AppShell({ children }) {
  const { pathname } = useLocation();
  const viewportLocked = ASSESSMENT_WORKSPACE_PATH.test(pathname);

  return (
    <div
      className={`flex flex-col bg-theme-primary text-theme-primary ${
        viewportLocked ? 'h-screen overflow-hidden' : 'min-h-screen'
      }`}
    >
      <Navbar />
      <main className="flex-1 min-h-0 flex flex-col">{children}</main>
    </div>
  );
}

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
        <AppShell>
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
              <Route
                path="/admin/modules"
                element={
                  <ProtectedRoute>
                    <AdminModules />
                  </ProtectedRoute>
                }
              />
              <Route path="/instructions" element={<Instructions />} />
          </Routes>
        </AppShell>
      </Router>
    </AuthProvider>
  );
}

export default App;
