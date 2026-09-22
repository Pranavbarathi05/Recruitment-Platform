import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Enter fullscreen from the "Start Assessment" click.
 *
 * The Fullscreen API only honours a request made from a transient user
 * activation, so the assessment cannot enter fullscreen from a `useEffect`
 * once /assessment/:attemptId has mounted — Chrome rejects that with
 * "API can only be initiated by a user gesture". This click is the last
 * gesture we get before the workspace takes over, so the request is fired
 * synchronously here (never awaited: a rejection must not block the start
 * flow) and the assessment workspace arms its exit penalty only once
 * fullscreen has actually been entered.
 */
function requestAssessmentFullscreen() {
  if (typeof document === 'undefined') return;
  const el = document.documentElement;
  if (!el || typeof el.requestFullscreen !== 'function' || document.fullscreenElement) return;
  try {
    const pending = el.requestFullscreen();
    if (pending && typeof pending.catch === 'function') {
      pending.catch(() => { /* browser policy/permission — handled gracefully downstream */ });
    }
  } catch {
    /* unsupported — handled gracefully downstream */
  }
}

/**
 * Domains Page
 *
 * Fetches active domains from the backend.
 * Candidate selects 1 or 2 domains, then starts assessment.
 */
const Domains = () => {
  const [domains, setDomains] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedDomains, setSelectedDomains] = useState([]);
  const [starting, setStarting] = useState(false);
  const { getAuthHeaders } = useAuth();
  const navigate = useNavigate();

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    const fetchDomains = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${apiUrl}/questions/domains`);

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        setDomains(data);
        setError(null);
      } catch (err) {
        console.error('Error fetching domains:', err);
        setError('Failed to load domains. Please try again later.');
      } finally {
        setLoading(false);
      }
    };

    fetchDomains();
  }, [apiUrl]);

  const toggleDomain = (domainId) => {
    setSelectedDomains((prev) => {
      if (prev.includes(domainId)) {
        return prev.filter((id) => id !== domainId);
      }
      if (prev.length >= 2) {
        return prev; // Max 2
      }
      return [...prev, domainId];
    });
  };

  const handleStartAssessment = async () => {
    if (selectedDomains.length === 0) {
      setError('Please select at least one domain.');
      return;
    }

    setStarting(true);
    setError(null);

    // Must happen from this click (user activation), before the first await.
    requestAssessmentFullscreen();

    try {
      const response = await fetch(`${apiUrl}/assessment/start`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ domain_ids: selectedDomains }),
      });

      // Read the body ONCE, then branch on status.
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || 'Failed to start assessment');
      }

      // If resuming an existing attempt, navigate to it
      navigate(`/assessment/${data.attempt_id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setStarting(false);
    }
  };

  // DSC theme colors for domains
  const domainColors = [
    'from-blue-600 to-blue-800',
    'from-teal-600 to-teal-800',
    'from-purple-600 to-purple-800',
    'from-red-600 to-red-800',
    'from-green-600 to-green-800',
    'from-indigo-600 to-purple-700',
    'from-orange-600 to-red-700',
    'from-cyan-600 to-blue-700',
  ];

  return (
    <main className="min-h-screen bg-theme-primary py-16 px-4">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-12">
          <h1 className="text-4xl font-bold text-theme-primary mb-4">Choose Your Domain</h1>
          <p className="text-theme-secondary text-lg max-w-2xl mx-auto">
            Select up to 2 domains for your assessment.
          </p>

        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex justify-center items-center py-20">
            <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-900/30 border border-red-500 text-red-200 px-6 py-4 rounded-lg max-w-2xl mx-auto mb-6">
            <p className="font-semibold">Error</p>
            <p>{error}</p>
          </div>
        )}

        {/* Selection info */}
        {!loading && !error && domains.length > 0 && (
          <div className="text-center mb-8">
            <p className="text-theme-muted">
              {selectedDomains.length === 0
                ? 'Select 1 or 2 domains to begin'
                : `${selectedDomains.length} domain${selectedDomains.length > 1 ? 's' : ''} selected`}
            </p>
          </div>
        )}

        {/* Domains Grid */}
        {!loading && !error && domains.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 mb-8">
            {domains.map((domain, index) => {
              const isSelected = selectedDomains.includes(domain.id);
              const gradientColor = domainColors[index % domainColors.length];

              return (
                <div
                  key={domain.id}
                  onClick={() => toggleDomain(domain.id)}
                  className={`bg-theme-secondary rounded-lg overflow-hidden cursor-pointer transition-all duration-300 shadow-lg hover:shadow-2xl ${
                    isSelected
                      ? 'ring-2 ring-blue-500 scale-[1.02]'
                      : 'hover:transform hover:scale-105'
                  }`}
                >
                  <div className={`h-2 bg-gradient-to-r ${gradientColor}`} />
                  <div className="p-6">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-xl font-bold text-theme-primary">
                        {domain.name}
                      </h3>
                      <div
                        className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${
                          isSelected
                            ? 'bg-blue-500 border-blue-500'
                            : 'border-gray-500'
                        }`}
                      >
                        {isSelected && (
                          <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                          </svg>
                        )}
                      </div>
                    </div>

                    {domain.description && (
                      <p className="text-theme-muted text-sm mb-4">{domain.description}</p>
                    )}

                    <div className="flex items-center gap-2">
                      <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-theme-tertiary text-theme-muted">
                        {domain.questionCount} {domain.questionCount === 1 ? 'Question' : 'Questions'}
                      </span>
                      <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-blue-900/50 text-blue-300">
                        ⏱️ {domain.durationMinutes} min
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Start Button */}
        {!loading && !error && domains.length > 0 && (
          <div className="text-center">
            <button
              onClick={handleStartAssessment}
              disabled={selectedDomains.length === 0 || starting}
              className={`px-8 py-3 rounded-lg font-bold text-white text-lg transition-all duration-200 ${
                selectedDomains.length === 0 || starting
                  ? 'bg-gray-600 cursor-not-allowed opacity-50'
                  : 'bg-blue-600 hover:bg-blue-700'
              }`}
            >
              {starting ? 'Starting...' : 'Start Assessment'}
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && domains.length === 0 && (
          <div className="text-center py-20">
            <p className="text-theme-secondary text-lg">No domains available at the moment.</p>
          </div>
        )}
      </div>
    </main>
  );
};

export default Domains;
