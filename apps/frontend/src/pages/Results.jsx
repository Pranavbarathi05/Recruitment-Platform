import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * Results Page
 *
 * Displays the score and detailed results for a completed assessment.
 * Shows correct/incorrect breakdown with explanations.
 */
const Results = () => {
  const { attemptId } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();

  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  useEffect(() => {
    if (!attemptId || !session?.access_token) return;

    const fetchResults = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/results`, {
          headers: {
            Authorization: `Bearer ${session?.access_token}`,
          },
        });

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || 'Failed to load results');
        }

        const data = await response.json();
        setResults(data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [attemptId, session, apiUrl]);

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
            onClick={() => navigate('/domains')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold"
          >
            Back to Domains
          </button>
        </div>
      </div>
    );
  }

  if (!results) return null;

  const percentage = results.max_score > 0
    ? Math.round((results.score / results.max_score) * 100)
    : 0;

  const correctCount = results.questions.filter((q) => q.is_correct).length;
  const incorrectCount = results.questions.filter((q) => !q.is_correct && q.selected_option).length;
  const unansweredCount = results.questions.filter((q) => !q.selected_option).length;

  return (
    <div className="min-h-screen bg-theme-primary py-12 px-4">
      <div className="max-w-4xl mx-auto">
        {/* Score Card */}
        <div className="bg-theme-secondary rounded-lg p-8 mb-8 text-center">
          <h1 className="text-3xl font-bold text-theme-primary mb-2">Assessment Complete</h1>
          <p className="text-theme-muted mb-6">
            Submitted on {new Date(results.submitted_at).toLocaleString()}
          </p>

          <div className="mb-6">
            <div className="text-6xl font-bold text-blue-500 mb-2">
              {results.score}/{results.max_score}
            </div>
            <div className="text-2xl text-theme-secondary">
              {percentage}% correct
            </div>
          </div>

          <div className="flex justify-center gap-8 mb-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-green-400">{correctCount}</div>
              <div className="text-theme-muted text-sm">Correct</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-400">{incorrectCount}</div>
              <div className="text-theme-muted text-sm">Incorrect</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-yellow-400">{unansweredCount}</div>
              <div className="text-theme-muted text-sm">Unanswered</div>
            </div>
          </div>

          <button
            onClick={() => navigate('/domains')}
            className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-3 rounded-lg font-semibold transition-colors"
          >
            Back to Domains
          </button>
        </div>

        {/* Detailed Review */}
        <h2 className="text-2xl font-bold text-theme-primary mb-6">Question Review</h2>

        <div className="space-y-4">
          {results.questions.map((q, index) => (
            <div
              key={index}
              className={`bg-theme-secondary rounded-lg p-6 border-l-4 ${
                q.is_correct
                  ? 'border-green-500'
                  : q.selected_option
                  ? 'border-red-500'
                  : 'border-yellow-500'
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-lg font-semibold text-theme-primary">
                  Q{index + 1}. {q.question_text}
                </h3>
                <span
                  className={`px-3 py-1 rounded-full text-sm font-medium ${
                    q.is_correct
                      ? 'bg-green-900/50 text-green-300'
                      : q.selected_option
                      ? 'bg-red-900/50 text-red-300'
                      : 'bg-yellow-900/50 text-yellow-300'
                  }`}
                >
                  {q.is_correct ? '✓ Correct' : q.selected_option ? '✗ Incorrect' : '— Unanswered'}
                </span>
              </div>

              {q.domainName && (
                <p className="text-theme-muted text-xs mb-3">{q.domainName}</p>
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mb-3">
                {['A', 'B', 'C', 'D'].map((opt) => {
                  const optText = q[`option_${opt.toLowerCase()}`];
                  const isCorrect = q.correct_option === opt;
                  const isSelected = q.selected_option === opt;

                  return (
                    <div
                      key={opt}
                      className={`p-3 rounded-lg text-sm ${
                        isCorrect
                          ? 'bg-green-900/30 border border-green-500 text-green-200'
                          : isSelected && !isCorrect
                          ? 'bg-red-900/30 border border-red-500 text-red-200'
                          : 'bg-theme-primary text-theme-muted'
                      }`}
                    >
                      <span className="font-bold mr-2">{opt}.</span>
                      {optText}
                      {isCorrect && ' ✓'}
                      {isSelected && !isCorrect && ' ✗'}
                    </div>
                  );
                })}
              </div>

              {q.explanation && (
                <div className="bg-theme-primary rounded-lg p-3 text-sm text-theme-secondary">
                  <strong>Explanation:</strong> {q.explanation}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Results;
