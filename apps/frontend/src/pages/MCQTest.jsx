import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

/**
 * MCQ Test Page
 *
 * Displays questions for an active assessment attempt.
 * Answers are saved as the candidate progresses.
 * Refreshing returns the same persisted questions.
 */
const MCQTest = () => {
  const { attemptId } = useParams();
  const navigate = useNavigate();
  const { session } = useAuth();

  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState(0);
  const [attemptData, setAttemptData] = useState(null);

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  const authHeaders = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${session?.access_token}`,
  };

  // Fetch attempt questions
  useEffect(() => {
    if (!attemptId || !session?.access_token) return;

    const fetchQuestions = async () => {
      try {
        setLoading(true);
        const response = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/questions`, {
          headers: authHeaders,
        });

        if (!response.ok) {
          const errData = await response.json();
          throw new Error(errData.detail || 'Failed to load questions');
        }

        const data = await response.json();
        setQuestions(data.questions);
        setAnswers(data.answers || {});
        setAttemptData(data);

        // Calculate time remaining
        const attemptResp = await fetch(`${apiUrl}/assessment/attempt/${attemptId}`, {
          headers: authHeaders,
        });
        if (attemptResp.ok) {
          const attempt = await attemptResp.json();
          const startTime = new Date(attempt.started_at).getTime();
          const durationMs = attempt.duration_minutes * 60 * 1000;
          const now = Date.now();
          const remaining = Math.max(0, Math.floor((startTime + durationMs - now) / 1000));
          setTimeRemaining(remaining);
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchQuestions();
  }, [attemptId, session, apiUrl]);

  // Timer countdown
  useEffect(() => {
    if (timeRemaining <= 0 && attemptData && !loading) {
      handleSubmit(true);
      return;
    }

    const interval = setInterval(() => {
      setTimeRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [timeRemaining, loading, attemptData]);

  // Save answer
  const saveAnswer = useCallback(async (questionId, option) => {
    setAnswers((prev) => ({ ...prev, [questionId]: option }));

    try {
      await fetch(`${apiUrl}/assessment/attempt/${attemptId}/answers`, {
        method: 'PUT',
        headers: authHeaders,
        body: JSON.stringify({
          question_id: questionId,
          selected_option: option,
        }),
      });
    } catch (err) {
      console.error('Failed to save answer:', err);
    }
  }, [attemptId, session, apiUrl]);

  // Submit attempt
  const handleSubmit = async (timeExpired = false) => {
    if (submitting) return;
    setSubmitting(true);

    try {
      const response = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/submit`, {
        method: 'POST',
        headers: authHeaders,
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to submit');
      }

      navigate(`/assessment/${attemptId}/results`);
    } catch (err) {
      if (timeExpired) {
        alert('Time expired. Your answers have been auto-submitted.');
        navigate(`/assessment/${attemptId}/results`);
      } else {
        setError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Format time
  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

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

  if (questions.length === 0) {
    return (
      <div className="min-h-screen bg-theme-primary flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-theme-primary mb-4">No questions available</h2>
          <a href="/domains" className="text-blue-400 hover:underline">Go back to domains</a>
        </div>
      </div>
    );
  }

  const currentQuestion = questions[currentIndex];
  const isWarning = timeRemaining <= 300 && timeRemaining > 0;
  const isExpired = timeRemaining <= 0;
  const answeredCount = Object.keys(answers).length;

  return (
    <div className="min-h-screen bg-theme-primary p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
          <div>
            <h1 className="text-2xl font-bold text-theme-primary">MCQ Assessment</h1>
            <p className="text-theme-secondary">
              Question {currentIndex + 1} of {questions.length}
              {currentQuestion.domainName && (
                <span className="ml-2 text-theme-muted">· {currentQuestion.domainName}</span>
              )}
            </p>
          </div>

          <div className="flex items-center gap-4">
            {/* Timer */}
            <div
              className={`px-4 py-2 rounded-lg font-mono text-lg font-bold ${
                isWarning
                  ? 'bg-red-900/50 text-red-300 border-2 border-red-500 animate-pulse'
                  : isExpired
                  ? 'bg-red-900/50 text-red-300'
                  : 'bg-blue-900/50 text-blue-300 border-2 border-blue-500'
              }`}
            >
              ⏱️ {formatTime(timeRemaining)}
            </div>
            <span className="text-theme-muted text-sm">
              {answeredCount}/{questions.length} answered
            </span>
          </div>
        </div>

        {/* Progress bar */}
        <div className="w-full bg-theme-secondary rounded-full h-2 mb-6">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }}
          />
        </div>

        {/* Question */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-theme-primary mb-6">
            {currentQuestion.question_text}
          </h2>

          {/* Options */}
          <div className="space-y-3">
            {['A', 'B', 'C', 'D'].map((option) => {
              const optionText = currentQuestion[`option_${option.toLowerCase()}`];
              const isSelected = answers[currentQuestion.id] === option;

              return (
                <button
                  key={option}
                  onClick={() => saveAnswer(currentQuestion.id, option)}
                  className={`w-full text-left p-4 rounded-lg border-2 transition-all duration-200 ${
                    isSelected
                      ? 'border-blue-500 bg-blue-900/30 text-theme-primary'
                      : 'border-theme-primary bg-theme-primary hover:border-blue-400 text-theme-primary'
                  }`}
                >
                  <span className="font-bold mr-3">{option}.</span>
                  {optionText}
                </button>
              );
            })}
          </div>
        </div>

        {/* Navigation */}
        <div className="flex justify-between items-center">
          <button
            onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
            disabled={currentIndex === 0}
            className="px-6 py-2 rounded-lg bg-theme-secondary text-theme-primary hover:bg-theme-tertiary disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>

          {/* Question number pills */}
          <div className="hidden md:flex flex-wrap justify-center gap-1 max-w-md">
            {questions.map((q, i) => (
              <button
                key={q.id}
                onClick={() => setCurrentIndex(i)}
                className={`w-8 h-8 rounded text-sm font-medium transition-colors ${
                  i === currentIndex
                    ? 'bg-blue-600 text-white'
                    : answers[q.id]
                    ? 'bg-green-600 text-white'
                    : 'bg-theme-secondary text-theme-muted hover:bg-theme-tertiary'
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>

          {currentIndex < questions.length - 1 ? (
            <button
              onClick={() => setCurrentIndex((prev) => prev + 1)}
              className="px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold transition-colors"
            >
              Next
            </button>
          ) : (
            <button
              onClick={() => handleSubmit(false)}
              disabled={submitting}
              className="px-6 py-2 rounded-lg bg-green-600 hover:bg-green-700 disabled:bg-gray-600 text-white font-semibold transition-colors"
            >
              {submitting ? 'Submitting...' : 'Submit Assessment'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default MCQTest;
