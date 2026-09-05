import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import teamimg from '../assets/images/team.jpg';
import learn from '../assets/images/learn.jpg';
import share from '../assets/images/share.jpg';
import { useAuth } from '../hooks/useAuth';
import PasswordInput from '../components/PasswordInput';

/**
 * Login Page
 *
 * Uses the FastAPI backend for email/password sign-in.
 * Handles invalid credentials, unverified email, and network errors.
 */
const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();
  const { signIn, isAuthenticated } = useAuth();

  const slides = [
    { title: 'Learn', description: 'Build a strong foundation in technology through hands-on sessions, workshops, and peer learning. Explore concepts from basics to advanced with guidance from mentors and real-world examples.', image: learn },
    { title: 'Code', description: 'Turn ideas into reality by writing code, building projects, and solving real problems. Practice modern tools and technologies while improving your logic, creativity, and problem-solving skills.', image: teamimg },
    { title: 'Share', description: 'Grow together by collaborating, teaching others, and sharing knowledge with the community. Present your work, contribute to open source, and learn from diverse perspectives.', image: share },
  ];

  const [slide, setSlide] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSlide((s) => (s + 1) % slides.length), 4000);
    return () => clearInterval(id);
  }, [slides.length]);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      navigate('/domains');
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!email || !password) {
      setError('Please enter both email and password');
      return;
    }

    setIsSubmitting(true);
    try {
      await signIn({ email, password });
      navigate('/domains');
    } catch (err) {
      const message = err.message || 'Login failed';
      if (message.includes('Invalid login credentials')) {
        setError('Invalid email or password. Please try again.');
      } else if (message.includes('Email not confirmed')) {
        setError('Please verify your email before logging in. Check your inbox for the confirmation link.');
      } else {
        setError(message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-theme-primary flex items-center justify-center px-4 py-12">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-0 right-0 md:w-2/5 z-0 w-1/2 h-1/2 bg-blue-600 opacity-10 pointer-events-none" />
        <div className="absolute bottom-0 left-0 md:w-2/5 z-0 w-1/2 h-1/2 bg-yellow-500 opacity-10 pointer-events-none" />
      </div>
      <div className="max-w-5xl w-full z-1 bg-theme-secondary rounded-lg shadow-xl p-6 md:p-8 grid md:grid-cols-2 gap-6">
        {/* Left: Carousel / Marketing */}
        <aside className="hidden md:flex items-start justify-center rounded-lg p-4 gap-4 bg-gradient-to-b from-[rgb(var(--bg-tertiary))] to-[rgb(var(--bg-secondary))]">
          <div className="flex flex-col items-center justify-center gap-4 p-1">
            <img src={slides[slide].image} alt="" className='w-[1000px] h-[350px] rounded-lg' />
            <h2 className="text-2xl font-bold text-theme-primary">{slides[slide].title}</h2>
            <p className="text-theme-muted text-lg text-center">{slides[slide].description}</p>
          </div>
        </aside>

        {/* Right: Login form */}
        <div className="w-full flex flex-col justify-center p-4">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold text-theme-primary mb-2">Welcome Back</h1>
            <p className="text-theme-secondary">Sign in to access DSC Recruitment Platform</p>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-500 text-red-300 rounded-lg text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-theme-muted mb-2">
                Email Address
              </label>
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="you@example.com"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-theme-muted mb-2">
                Password
              </label>
              <PasswordInput
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="••••••••"
                required
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white font-bold rounded-lg transition duration-200"
            >
              {isSubmitting ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <p className="mt-6 text-center text-theme-secondary text-sm">
            Don&apos;t have an account?{' '}
            <a href="/signup" className="text-blue-500 hover:text-blue-400">
              Sign up
            </a>
          </p>
        </div>
      </div>
    </main>
  );
};

export default Login;
