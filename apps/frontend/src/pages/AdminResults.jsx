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
    total_mcq_questions,
    total_coding_problems,
    duration_minutes,
    started_at,
    submitted_at,
    score,
    max_score,
    percentage,
    mcq_score,
    mcq_max_score,
    coding_score,
    coding_max_score,
    correct_count,
    incorrect_count,
    unanswered_count,
    mcq_questions,
    coding_results,
  } = results;
  const questions = mcq_questions || [];

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
              <span className="text-theme-muted block">MCQ Questions</span>
              <span className="text-theme-primary font-medium">{total_mcq_questions}</span>
            </div>
            <div>
              <span className="text-theme-muted block">Coding Problems</span>
              <span className="text-theme-primary font-medium">{total_coding_problems}</span>
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Overall */}
            <div className="text-center">
              <div className="text-4xl font-bold text-blue-400">{score} / {max_score}</div>
              <div className="text-sm text-theme-muted mt-1">{percentage}% Overall</div>
            </div>
            {/* MCQ */}
            <div className="text-center">
              <div className="text-2xl font-bold text-green-400">{mcq_score} / {mcq_max_score}</div>
              <div className="text-sm text-theme-muted mt-1">MCQ Score</div>
              <div className="flex justify-center gap-3 text-xs mt-2">
                <span className="text-green-400">✓ {correct_count} correct</span>
                <span className="text-red-400">✗ {incorrect_count} wrong</span>
                <span className="text-yellow-400">— {unanswered_count} skipped</span>
              </div>
            </div>
            {/* Coding */}
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-400">{coding_score} / {coding_max_score}</div>
              <div className="text-sm text-theme-muted mt-1">Coding Score</div>
            </div>
          </div>
        </div>

        {/* Coding Submissions */}
        {coding_results && coding_results.length > 0 && (
          <div className="bg-theme-secondary rounded-lg p-6 mb-6">
            <h2 className="text-xl font-bold text-theme-primary mb-6">Coding Submissions</h2>
            <div className="space-y-4">
              {coding_results.map((cr, idx) => (
                <div key={idx} className="bg-theme-primary rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold text-theme-primary">{cr.problem_title}</h3>
                    <span className={`text-xs px-2 py-1 rounded font-bold ${
                      cr.status === 'passed' ? 'bg-green-900/50 text-green-300'
                      : cr.status === 'failed' ? 'bg-red-900/50 text-red-300'
                      : 'bg-yellow-900/50 text-yellow-300'
                    }`}>{cr.status}</span>
                  </div>
                  <div className="grid grid-cols-4 gap-4 text-xs text-theme-muted mb-3">
                    <span>Language: {cr.language}</span>
                    <span>Score: {cr.score}/{cr.max_score}</span>
                    <span>Tests: {cr.tests_passed}/{cr.tests_total}</span>
                    {cr.execution_time_ms && <span>Time: {cr.execution_time_ms}ms</span>}
                  </div>
                  <details>
                    <summary className="text-xs text-blue-400 cursor-pointer">View Source Code</summary>
                    <pre className="mt-2 bg-theme-secondary rounded p-3 text-xs text-theme-secondary overflow-x-auto max-h-64 overflow-y-auto font-mono whitespace-pre-wrap">{cr.source_code}</pre>
                  </details>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* MCQ Question-by-question review */}
        {questions.length > 0 && (
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
        )}
      </div>
    </div>
  );
};

export default AdminResults;
