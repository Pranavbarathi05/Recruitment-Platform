import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Admin Results Page
 *
 * Displays complete assessment results for a single candidate submission.
 * Admin-only — requires is_admin = true in profiles.
 *
 * Shows:
 * - Candidate information (name, email, USN, branch, semester)
 * - Assessment metadata (domains, total questions, duration, timestamps)
 * - Performance summary (score, percentage, correct/incorrect/unanswered)
 * - Question-by-question review with correct answers and explanations
 */
const AdminResults = () => {
  const { attemptId } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();

  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const authHeaders = useMemo(
    () => session?.access_token
      ? { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` }
      : null,
    [session?.access_token],
  );

  useEffect(() => {
    if (!attemptId || !authHeaders) return;

    const fetchResults = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch(`${apiUrl}/admin/assessments/${attemptId}/results`, {
          headers: authHeaders,
        });

        if (resp.status === 401 || resp.status === 403) {
          setError('Admin access required.');
          return;
        }
        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.detail || 'Failed to load results');
        }

        setResults(await resp.json());
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [attemptId, apiUrl, authHeaders]);

  if (loading) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="text-center bg-theme-secondary rounded-lg p-8 max-w-md">
          <h2 className="text-2xl font-bold text-theme-primary mb-4">Error</h2>
          <p className="text-theme-muted mb-6">{error}</p>
          <button
            onClick={() => navigate('/admin')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold"
          >
            Back to Admin Panel
          </button>
        </div>
      </div>
    );
  }

  if (!results) return null;

  const {
    candidate,
    domain_names,
    total_questions,
    duration_minutes,
    started_at,
    submitted_at,
    score,
    max_score,
    percentage,
    correct_count,
    incorrect_count,
    unanswered_count,
    questions,
  } = results;

  const formatTime = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  return (
    <div className="min-h-screen bg-theme-primary py-8 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <button
            onClick={() => navigate('/admin')}
            className="text-theme-muted hover:text-theme-primary transition-colors"
          >
            ← Back to Admin Panel
          </button>
        </div>

        <h1 className="text-3xl font-bold text-theme-primary mb-6">Assessment Results</h1>

        {/* Candidate Info Card */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <h2 className="text-xl font-bold text-theme-primary mb-4">Candidate</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-theme-muted block">Name</span>
              <span className="text-theme-primary font-medium">{candidate.full_name}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Email</span>
              <span className="text-theme-primary font-medium">{candidate.email}</span>
            </div>
            <div>
              <span className="text-theme-muted block">USN</span>
              <span className="text-theme-primary font-medium">{candidate.usn}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Branch</span>
              <span className="text-theme-primary font-medium">{candidate.branch}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Semester</span>
              <span className="text-theme-primary font-medium">{candidate.semester_label}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Domain(s)</span>
              <span className="text-theme-primary font-medium">{domain_names.join(', ')}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Duration</span>
              <span className="text-theme-primary font-medium">{duration_minutes} min</span>
            </div>
            <div>
              <span className="text-theme-muted block">Total Questions</span>
              <span className="text-theme-primary font-medium">{total_questions}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-4 text-sm">
            <div>
              <span className="text-theme-muted block">Started</span>
              <span className="text-theme-primary font-medium">{formatTime(started_at)}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Submitted</span>
              <span className="text-theme-primary font-medium">{formatTime(submitted_at)}</span>
            </div>
          </div>
        </div>

        {/* Performance Summary */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <h2 className="text-xl font-bold text-theme-primary mb-4">Performance</h2>
          <div className="flex flex-wrap items-center gap-8">
            <div className="text-center">
              <div className="text-4xl font-bold text-blue-400">{score} / {max_score}</div>
              <div className="text-sm text-theme-muted mt-1">{percentage}% Correct</div>
            </div>
            <div className="flex gap-6 text-sm">
              <div className="text-center">
                <div className="text-2xl font-bold text-green-400">{correct_count}</div>
                <div className="text-theme-muted">Correct</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-red-400">{incorrect_count}</div>
                <div className="text-theme-muted">Incorrect</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-yellow-400">{unanswered_count}</div>
                <div className="text-theme-muted">Unanswered</div>
              </div>
            </div>
          </div>
        </div>

        {/* Question-by-question review */}
        <div className="bg-theme-secondary rounded-lg p-6">
          <h2 className="text-xl font-bold text-theme-primary mb-6">Question Review</h2>
          <div className="space-y-6">
            {questions.map((q, idx) => {
              const isCorrect = q.is_correct;
              const isUnanswered = !q.selected_option;

              return (
                <div
                  key={idx}
                  className={`border-l-4 pl-4 ${
                    isUnanswered
                      ? 'border-yellow-500'
                      : isCorrect
                      ? 'border-green-500'
                      : 'border-red-500'
                  }`}
                >
                  <div className="flex items-start justify-between mb-2">
                    <h3 className="font-semibold text-theme-primary">
                      Q{idx + 1}. {q.question_text}
                    </h3>
                    <span className={`text-xs px-2 py-1 rounded ml-2 flex-shrink-0 ${
                      isUnanswered
                        ? 'bg-yellow-900/50 text-yellow-300'
                        : isCorrect
                        ? 'bg-green-900/50 text-green-300'
                        : 'bg-red-900/50 text-red-300'
                    }`}>
                      {isUnanswered ? '— Unanswered' : isCorrect ? '✓ Correct' : '✗ Incorrect'}
                    </span>
                  </div>

                  {q.domainName && (
                    <span className="text-xs text-theme-muted">{q.domainName}</span>
                  )}

                  {/* Options */}
                  <div className="mt-2 space-y-1 text-sm">
                    {['A', 'B', 'C', 'D'].map((opt) => {
                      const isCandidateAnswer = q.selected_option === opt;
                      const isCorrectAnswer = q.correct_option === opt;
                      let optClass = 'text-theme-muted';
                      if (isCandidateAnswer && isCorrectAnswer) optClass = 'text-green-400 font-medium';
                      else if (isCandidateAnswer && !isCorrectAnswer) optClass = 'text-red-400 font-medium';
                      else if (!isCandidateAnswer && isCorrectAnswer) optClass = 'text-green-400';

                      return (
                        <div key={opt} className={optClass}>
                          {opt}. {q[`option_${opt.toLowerCase()}`]}
                          {isCandidateAnswer && <span className="ml-2 text-xs">(candidate)</span>}
                          {isCorrectAnswer && <span className="ml-2 text-xs">(correct)</span>}
                        </div>
                      );
                    })}
                  </div>

                  {/* Unanswered notice */}
                  {isUnanswered && (
                    <p className="text-xs text-yellow-400 mt-2">Candidate did not answer this question.</p>
                  )}

                  {/* Explanation */}
                  {q.explanation && (
                    <p className="text-xs text-blue-400 mt-2 italic">Explanation: {q.explanation}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminResults;
