import { useState, useEffect } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/**
 * Navbar Component
 *
 * A responsive navigation bar with DSC logo and navigation links.
 * Shows different links based on authentication state.
 * Supports light/dark theme toggle with localStorage persistence.
 */
const Navbar = ({
  logo = '/logo-nav.png',
  logoAlt = 'DSC Logo',
  showThemeToggle = true,
}) => {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const { isAuthenticated, user, signOut, session } = useAuth();
  const navigate = useNavigate();
  const [darkMode, setDarkMode] = useState(() => {
    const savedTheme = localStorage.getItem('theme');
    return savedTheme ? savedTheme === 'dark' : true;
  });
  const [isAdmin, setIsAdmin] = useState(false);

  // Sync theme class on documentElement whenever darkMode changes
  useEffect(() => {
    const theme = darkMode ? 'dark' : 'light';
    document.documentElement.classList.remove('light', 'dark');
    document.documentElement.classList.add(theme);
    localStorage.setItem('theme', theme);
  }, [darkMode]);

  const toggleMobileMenu = () => {
    setIsMobileMenuOpen(!isMobileMenuOpen);
  };

  const toggleDarkMode = () => {
    setDarkMode((prev) => !prev);
  };

  const handleLogout = async () => {
    try {
      await signOut();
      navigate('/');
    } catch (err) {
      console.error('Logout failed:', err);
    }
  };

  // Check admin status — only show Admin link if the user is an admin.
  // When not authenticated, this effect is a no-op (isAdmin stays false
  // from the initial state or from the previous logout).
  useEffect(() => {
    if (!isAuthenticated || !session?.access_token) return;
    let cancelled = false;
    fetch(`${apiUrl}/admin/domains`, {
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
      .then((r) => { if (!cancelled) setIsAdmin(r.ok); })
      .catch(() => { if (!cancelled) setIsAdmin(false); });
    return () => { cancelled = true; };
  }, [isAuthenticated, session, apiUrl]);

  // Navigation links based on auth state
  const navLinks = isAuthenticated
    ? [
        { name: 'Home', href: '/' },
        { name: 'Domains', href: '/domains' },
        { name: 'Dashboard', href: '/dashboard' },
        ...(isAdmin ? [{ name: 'Admin', href: '/admin' }] : []),
      ]
    : [
        { name: 'Home', href: '/' },
        { name: 'Login', href: '/login' },
      ];

  return (
    <header className="sticky top-0 z-50 bg-theme-secondary shadow-md backdrop-blur-md">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <NavLink to="/" className="flex items-center">
            <img src={logo} alt={logoAlt} className="h-8 w-auto" />
          </NavLink>

          {/* Desktop Navigation */}
          <nav className="hidden md:flex space-x-8">
            {navLinks.map((link) => (
              <NavLink
                key={link.name}
                to={link.href}
                className={({ isActive }) =>
                  `text-theme-primary hover:text-blue-500 transition-colors duration-300 font-medium ${
                    isActive ? 'text-blue-500 font-bold border-b-2 border-blue-500' : ''
                  }`
                }
              >
                {link.name}
              </NavLink>
            ))}
          </nav>

          {/* Right side controls */}
          <div className="flex items-center space-x-4">
            {/* User info + Logout (desktop) */}
            {isAuthenticated && (
              <div className="hidden md:flex items-center space-x-3">
                <span className="text-theme-muted text-sm">
                  {user?.email}
                </span>
                <button
                  onClick={handleLogout}
                  className="text-sm text-red-400 hover:text-red-300 transition-colors duration-200"
                >
                  Logout
                </button>
              </div>
            )}

            {/* Theme Toggle */}
            {showThemeToggle && (
              <button
                onClick={toggleDarkMode}
                className="p-2 rounded-full text-theme-primary hover:bg-theme-tertiary transition-all duration-300"
                aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {darkMode ? (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-6 w-6"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z"
                      clipRule="evenodd"
                    />
                  </svg>
                ) : (
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-6 w-6"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                  </svg>
                )}
              </button>
            )}

            {/* Mobile Menu Button */}
            <button
              onClick={toggleMobileMenu}
              className="md:hidden p-2 rounded-full text-theme-primary hover:bg-theme-tertiary transition-all duration-300"
              aria-label="Toggle menu"
              aria-expanded={isMobileMenuOpen}
            >
              {isMobileMenuOpen ? (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              ) : (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Navigation Menu */}
      {isMobileMenuOpen && (
        <div className="md:hidden bg-theme-secondary border-t border-theme-primary">
          <div className="py-2">
            {navLinks.map((link) => (
              <NavLink
                key={link.name}
                to={link.href}
                onClick={() => setIsMobileMenuOpen(false)}
                className={({ isActive }) =>
                  `block px-6 py-3 text-theme-primary hover:bg-theme-tertiary transition-colors duration-300 ${
                    isActive ? 'text-blue-500 font-bold border-l-4 border-blue-500 bg-theme-tertiary' : ''
                  }`
                }
              >
                {link.name}
              </NavLink>
            ))}
            {isAuthenticated && (
              <button
                onClick={() => {
                  setIsMobileMenuOpen(false);
                  handleLogout();
                }}
                className="block w-full text-left px-6 py-3 text-red-400 hover:bg-theme-tertiary transition-colors duration-300"
              >
                Logout
              </button>
            )}
          </div>
        </div>
      )}
    </header>
  );
};

export default Navbar;
