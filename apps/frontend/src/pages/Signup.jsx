import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import teamimg from '../assets/images/team.jpg';
import learn from '../assets/images/learn.jpg';
import share from '../assets/images/share.jpg';
import { useAuth } from '../hooks/useAuth';
import PasswordInput from '../components/PasswordInput';

/**
 * Signup Page
 *
 * Creates an account via the FastAPI backend (which proxies to Supabase Auth).
 * Handles email confirmation flow and duplicate emails.
 */
const Signup = () => {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [usn, setUsn] = useState('');
  const [semester, setSemester] = useState('1');
  const [branch, setBranch] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [confirmationPending, setConfirmationPending] = useState(false);
  const navigate = useNavigate();
  const { signUp, isAuthenticated } = useAuth();

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
      navigate('/instructions');
    }
  }, [isAuthenticated, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!fullName || !email || !usn || !password) {
      setError('Please fill in all required fields');
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await signUp({
        email,
        password,
        fullName,
        usn,
        semester,
        branch,
      });

      if (result.needsConfirmation) {
        setConfirmationPending(true);
      } else {
        navigate('/instructions');
      }
    } catch (err) {
      const message = err.message || 'Signup failed';
      if (message.includes('already registered') || message.includes('already exists')) {
        setError('An account with this email already exists. Please try logging in.');
      } else if (message.includes('valid email')) {
        setError('Please enter a valid email address.');
      } else if (message.includes('at least 6')) {
        setError('Password must be at least 6 characters long.');
      } else {
        setError(message);
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Show confirmation pending state
  if (confirmationPending) {
    return (
      <main className="min-h-screen bg-theme-primary flex items-center justify-center px-4 py-12">
        <div className="max-w-lg w-full bg-theme-secondary rounded-lg shadow-xl p-8 text-center">
          <div className="text-6xl mb-4">📧</div>
          <h1 className="text-3xl font-bold text-theme-primary mb-4">Check Your Email</h1>
          <p className="text-theme-secondary mb-6">
            We&apos;ve sent a confirmation link to <strong>{email}</strong>.
            Please verify your email address to complete your account setup.
          </p>
          <p className="text-theme-muted text-sm mb-6">
            After confirming, you can log in with your email and password.
          </p>
          <button
            onClick={() => navigate('/login')}
            className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg transition duration-200"
          >
            Go to Login
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-theme-primary flex items-center justify-center px-4 py-12">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute z-0 top-0 right-0 md:w-2/5 w-1/2 h-1/2 bg-blue-600 opacity-10 pointer-events-none" />
        <div className="absolute z-0 bottom-0 left-0 md:w-2/5 w-1/2 h-1/2 bg-yellow-500 opacity-10 pointer-events-none" />
      </div>

      <div className="max-w-5xl w-full z-1 bg-theme-secondary rounded-lg shadow-xl p-6 md:p-6 grid md:grid-cols-2 gap-6">
        {/* Left: Carousel / Marketing */}
        <aside className="hidden md:flex items-start justify-center rounded-lg p-4 gap-4 bg-gradient-to-b from-[rgb(var(--bg-tertiary))] to-[rgb(var(--bg-secondary))]">
          <div className="flex flex-col items-center justify-center gap-4 p-1">
            <img src={slides[slide].image} alt="" className='w-[1000px] h-[350px] rounded-lg' />
            <h2 className="text-2xl font-bold text-theme-primary">{slides[slide].title}</h2>
            <p className="text-theme-muted text-lg text-center">{slides[slide].description}</p>
          </div>
        </aside>

        {/* Right: Signup form */}
        <section className="w-full">
          <div className="text-center mb-6">
            <h1 className="text-3xl font-bold text-theme-primary mb-1">Create Account</h1>
            <p className="text-theme-secondary">Sign up to access the DSC Recruitment Platform</p>
          </div>

          {error && (
            <div className="mb-4 p-3 bg-red-900/30 border border-red-500 text-red-300 rounded-lg text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label htmlFor="fullName" className="block text-sm font-medium text-theme-muted mb-2">
                Full Name
              </label>
              <input
                id="fullName"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Your full name"
              />
            </div>

            <div>
              <label htmlFor="email" className="block text-sm font-medium text-theme-muted mb-2">
                Email Address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="you@example.com"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label htmlFor="usn" className="block text-sm font-medium text-theme-muted mb-2">USN</label>
                <input
                  id="usn"
                  type="text"
                  value={usn}
                  onChange={(e) => setUsn(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="USN"
                />
              </div>

              <div>
                <label htmlFor="semester" className="block text-sm font-medium text-theme-muted mb-2">Semester</label>
                <select
                  id="semester"
                  value={semester}
                  onChange={(e) => setSemester(e.target.value)}
                  className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="1">1st Semester</option>
                  <option value="3">3rd Semester</option>
                  <option value="5">5th Semester</option>
                  <option value="7">7th Semester</option>
                </select>
              </div>
            </div>

            <div>
              <label htmlFor="branch" className="block text-sm font-medium text-theme-muted mb-2">Branch</label>
              <select
                id="branch"
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                required
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="" disabled>Select Branch</option>
                <option value="Computer Science and Engineering">Computer Science and Engineering</option>
                <option value="Information Science and Engineering">Information Science and Engineering</option>
                <option value="Computer Science and Business Systems">Computer Science and Business Systems</option>
                <option value="Electronics and Communication">Electronics and Communication</option>
                <option value="Electronics and Instrumentation">Electronics and Instrumentation</option>
                <option value="Electrical and Electronics">Electrical and Electronics</option>
                <option value="Biotechnology">Biotechnology</option>
                <option value="Mechanical Engineering">Mechanical Engineering</option>
                <option value="Industrial and Production Engineering">Industrial and Production Engineering</option>
                <option value="Polymer Science and Technology">Polymer Science and Technology</option>
                <option value="Environmental Engineering">Environmental Engineering</option>
                <option value="Civil Engineering">Civil Engineering</option>
                <option value="Construction Technology and Management">Construction Technology and Management</option>
              </select>
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-theme-muted mb-2">Password</label>
              <PasswordInput
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary placeholder-theme focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="••••••••"
              />
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 text-white font-bold rounded-lg transition duration-200"
            >
              {isSubmitting ? 'Creating Account...' : 'Sign Up'}
            </button>

            <p className="mt-2 text-center text-theme-secondary text-sm">
              Already have an account? <a href="/login" className="text-blue-500 hover:text-blue-400">Sign in</a>
            </p>
          </form>
        </section>
      </div>
    </main>
  );
};

export default Signup;
