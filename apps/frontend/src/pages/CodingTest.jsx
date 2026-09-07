import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import CodeEditor from '../components/CodeEditor';
import TestResultsPanel from '../components/TestResultsPanel';
import { runCodeLocally, isClientRunnable } from '../execution/runner';
import { generatePythonStarterCode } from '../utils/codingStarterCode';

/**
 * Coding Test Page
 *
 * Displays coding problems for an active coding assessment attempt.
 * Supports:
 * - Problem description with examples
 * - Language selection
 * - Code editing with Monaco
 * - Run against public test cases
 * - Submit for server-side evaluation
 * - Autosave drafts
 * - Timer display
 */

const LANGUAGES = [
  { value: 'python3', label: 'Python 3' },
  { value: 'cpp', label: 'C++' },
  { value: 'java', label: 'Java' },
];

/**
 * Simple per-language starter code fallback.
 * Used when the backend has no stored starter_code for a language.
 * Python uses generatePythonStarterCode (type-aware).
 * C++/Java use simple templates based on function_name only (no type parsing).
 */
function getStarterForLanguage(language, functionName, className, functionSignature) {
  switch (language) {
    case 'python3':
      return generatePythonStarterCode(functionName, className, functionSignature);
    case 'cpp': {
      const params = ['arg1', 'arg2'].join(', ');
      if (className && className.trim()) {
        return (
          'class ' + className.trim() + ' {\n' +
          'public:\n' +
          '    int ' + functionName + '(' + params + ') {\n' +
          '        // Write your solution here\n' +
          '    }\n' +
          '};\n'
        );
      }
      return 'int ' + functionName + '(' + params + ') {\n    // Write your solution here\n}\n';
    }
    case 'java': {
      const params = ['arg1', 'arg2'].join(', ');
      if (className && className.trim()) {
        return (
          'class ' + className.trim() + ' {\n' +
          '    public int ' + functionName + '(' + params + ') {\n' +
          '        // Write your solution here\n' +
          '    }\n' +
          '}\n'
        );
      }
      return 'public int ' + functionName + '(' + params + ') {\n    // Write your solution here\n}\n';
    }
    default:
      return '';
  }
}

const CodingTest = () => {
  const { attemptId } = useParams();
  const navigate = useNavigate();
  // Cookie auth

  const [problems, setProblems] = useState([]);
  const [currentProblemIndex, setCurrentProblemIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeRemaining, setTimeRemaining] = useState(0);

  // Editor state
  const [language, setLanguage] = useState('python3');
  const [sourceCode, setSourceCode] = useState('');
  const [running, setRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [runResults, setRunResults] = useState(null);

  // Submission states per problem
  const [submittedProblems, setSubmittedProblems] = useState({});

  // Autosave
  const autosaveTimerRef = useRef(null);
  const lastSavedCodeRef = useRef('');

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // Cookie auth — no manual headers needed

  // Fetch problems
  useEffect(() => {
    if (!attemptId) return;

    const fetchProblems = async () => {
      try {
        setLoading(true);
        const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/problems`, {
          credentials: 'include',
        });
        if (!resp.ok) {
          const err = await resp.json();
          throw new Error(err.detail || 'Failed to load problems');
        }
        const data = await resp.json();
        setProblems(data.problems || []);

        if (data.expires_at) {
          const expires = new Date(data.expires_at);
          const now = new Date();
          setTimeRemaining(Math.max(0, Math.floor((expires - now) / 1000)));
        }
      } catch (err) {
        // ignore fetch errors on initial load
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchProblems();
  }, [attemptId, apiUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load initial code/draft when problem changes
  useEffect(() => {
    if (problems.length === 0 || currentProblemIndex >= problems.length) return;

    const problem = problems[currentProblemIndex];

    if (problem.draft) {
      setSourceCode(problem.draft.source_code);
      setLanguage(problem.draft.language || 'python3');
    } else {
      // Load starter code. For Python we can regenerate a correct starter from
      // the problem metadata when the stored starter for the active language is
      // missing/empty, so the editor never silently falls back to a generic
      // skeleton that disagrees with the configured function metadata.
      const activeLang = language || problem.supported_languages?.[0] || 'python3';
      const storedStarter = problem.starter_code?.[activeLang];

      if (activeLang === 'python3') {
        setSourceCode(
          (storedStarter && storedStarter.trim())
            ? storedStarter
            : generatePythonStarterCode(
                problem.function_name || 'solve',
                problem.class_name || null,
                problem.function_signature || null,
              ),
        );
      } else {
        // C++/Java: prefer stored starter from backend; fall back to simple
        // inline template (no type parsing).
        setSourceCode(
          storedStarter && storedStarter.trim()
            ? storedStarter
            : getStarterForLanguage(
                activeLang,
                problem.function_name || 'solve',
                problem.class_name || null,
                problem.function_signature || null,
              ),
        );
      }

      setLanguage(activeLang);
    }
    setRunResults(null);
    lastSavedCodeRef.current = '';
  }, [currentProblemIndex, problems]);

  // Per-(problem, language) typed-code drafts. Lets switching away and back
  // restore the candidate's own edits instead of re-showing the starter.
  const [languageDrafts, setLanguageDrafts] = useState({});

  // Regenerate starter code when language changes.
  // Priority: (1) candidate-typed draft for this language; (2) admin-stored
  // starter; (3) generated starter (Python from metadata, C++/Java simple
  // fallback, no type parsing).
  useEffect(() => {
    if (problems.length === 0 || currentProblemIndex >= problems.length) return;

    const problem = problems[currentProblemIndex];
    const draft = languageDrafts[problem.id]?.[language];
    if (draft && draft.trim()) {
      setSourceCode(draft);
      return;
    }

    const storedStarter = problem.starter_code?.[language];
    if (storedStarter && storedStarter.trim()) {
      setSourceCode(storedStarter);
      return;
    }

    if (language === 'python3') {
      setSourceCode(
        generatePythonStarterCode(
          problem.function_name || 'solve',
          problem.class_name || null,
          problem.function_signature || null,
        ),
      );
    } else {
      setSourceCode(
        getStarterForLanguage(
          language,
          problem.function_name || 'solve',
          problem.class_name || null,
          problem.function_signature || null,
        ),
      );
    }
  }, [language, currentProblemIndex, problems, languageDrafts]);

  // Persist typed code per (problem, language). This is what allows switching
  // away from a language and back to restore the candidate's own edits instead
  // of re-showing the starter.
  useEffect(() => {
    if (problems.length === 0 || currentProblemIndex >= problems.length) return;

    const problem = problems[currentProblemIndex];
    setLanguageDrafts((prev) => {
      const byProblem = prev[problem.id] || {};
      if (byProblem[language] !== sourceCode) {
        return {
          ...prev,
          [problem.id]: {
            ...byProblem,
            [language]: sourceCode,
          },
        };
      }
      return prev;
    });
  }, [sourceCode, language, currentProblemIndex, problems]);

  // Autosave (debounced 2 seconds)
  useEffect(() => {
    if (!attemptId || problems.length === 0) return;

    const problem = problems[currentProblemIndex];
    if (!problem) return;

    if (sourceCode === lastSavedCodeRef.current) return;

    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);

    autosaveTimerRef.current = setTimeout(async () => {
      try {
        await fetch(`${apiUrl}/coding/attempt/${attemptId}/draft`, {
          method: 'PUT',
          credentials: 'include',
          body: JSON.stringify({
            problem_id: problem.id,
            language,
            source_code: sourceCode,
          }),
        });
        lastSavedCodeRef.current = sourceCode;
      } catch {
        // Silently fail autosave — user won't lose local state
      }
    }, 2000);

    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [sourceCode, language, attemptId, currentProblemIndex, problems]); // eslint-disable-line react-hooks/exhaustive-deps

  // Timer
  useEffect(() => {
    if (timeRemaining <= 0) return;

    const interval = setInterval(() => {
      setTimeRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          handleCompleteAll();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [timeRemaining > 0]);


  const formatTime = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  // Run executes client-side (Web Worker + WASM via Pyodide) for languages
  // with a browser runtime — currently python3. It never touches the Submit
  // flow; results are candidate feedback only. Other languages keep using the
  // existing server-side run endpoint.
  const runCodeOnServer = async (problem) => {
    const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/run`, {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({
        problem_id: problem.id,
        language,
        source_code: sourceCode,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to run code');
    }

    return resp.json();
  };

  const handleRunCode = async () => {
    const problem = problems[currentProblemIndex];
    if (!problem || running) return;
    setRunning(true);
    setRunResults(null);

    try {
      const result = isClientRunnable(language)
        ? await runCodeLocally({
            language,
            sourceCode,
            testCases: problem.test_cases || [], // public tests only
            functionName: problem.function_name || 'solve',
            className: problem.class_name || null,
            timeLimitMs: problem.time_limit_ms || 2000,
          })
        : await runCodeOnServer(problem);
      setRunResults(result);
    } catch (err) {
      setRunResults({ all_passed: false, results: [], error: err.message });
    } finally {
      setRunning(false);
    }
  };

  const handleSubmitSolution = async () => {
    if (!problems[currentProblemIndex] || submitting) return;
    setSubmitting(true);

    try {
      const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/submit`, {
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          problem_id: problems[currentProblemIndex].id,
          language,
          source_code: sourceCode,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to submit');
      }

      const result = await resp.json();
      setSubmittedProblems((prev) => ({
        ...prev,
        [currentProblemIndex]: result,
      }));
      setRunResults(null);
    } catch (err) {
      alert(`Submission failed: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleCompleteAll = async () => {
    try {
      const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/complete`, {
        method: 'POST',
        credentials: 'include',
      });

      if (resp.ok) {
        navigate('/assessment/' + attemptId + '/submitted');
      }
    } catch {
      // If server-side completion fails, still navigate
      navigate('/assessment/' + attemptId + '/submitted');
    }
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

  const problem = problems[currentProblemIndex];
  if (!problem) return null;

  const isSubmitted = !!submittedProblems[currentProblemIndex];
  const isExpired = timeRemaining <= 0;

  return (
    <div className="min-h-screen bg-theme-primary">
      {/* Header Bar */}
      <div className="bg-theme-secondary border-b border-theme-border px-6 py-3 flex items-center justify-between sticky top-0 z-10">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-theme-primary">Coding Assessment</h1>
          <span className="text-sm text-theme-muted">
            Problem {currentProblemIndex + 1} of {problems.length}
          </span>
        </div>

        <div className="flex items-center gap-4">
          {/* Timer */}
          <div className={`px-4 py-2 rounded-lg font-mono text-lg font-bold ${
            timeRemaining <= 300
              ? 'bg-red-900/50 text-red-300 border-2 border-red-500'
              : 'bg-blue-900/50 text-blue-300 border-2 border-blue-500'
          }`}>
            ⏱ {formatTime(timeRemaining)}
          </div>

          <button
            onClick={handleCompleteAll}
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg font-semibold text-sm"
          >
            Finish Assessment
          </button>
        </div>
      </div>

      <div className="flex h-[calc(100vh-60px)]">
        {/* Left: Problem Description */}
        <div className="w-1/2 overflow-y-auto p-6 border-r border-theme-border">
          {/* Problem Tabs */}
          {problems.length > 1 && (
            <div className="flex gap-2 mb-4 flex-wrap">
              {problems.map((p, idx) => (
                <button
                  key={p.id}
                  onClick={() => setCurrentProblemIndex(idx)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    idx === currentProblemIndex
                      ? 'bg-blue-600 text-white'
                      : submittedProblems[idx]
                        ? 'bg-green-900/50 text-green-300 border border-green-600'
                        : 'bg-theme-tertiary text-theme-muted hover:text-theme-primary'
                  }`}
                >
                  Problem {idx + 1}
                  {submittedProblems[idx] && ' ✓'}
                </button>
              ))}
            </div>
          )}

          {/* Problem Title & Difficulty */}
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-2xl font-bold text-theme-primary">{problem.title}</h2>
            <span className={`px-2 py-1 rounded text-xs font-bold uppercase ${
              problem.difficulty === 'easy' ? 'bg-green-900/50 text-green-300'
                : problem.difficulty === 'hard' ? 'bg-red-900/50 text-red-300'
                  : 'bg-yellow-900/50 text-yellow-300'
            }`}>
              {problem.difficulty}
            </span>
            <span className="text-sm text-theme-muted">{problem.points} pts</span>
          </div>

          {problem.domainName && (
            <span className="text-xs text-theme-muted mb-4 block">{problem.domainName}</span>
          )}

          {/* Description */}
          <div className="bg-theme-secondary rounded-lg p-4 mb-4">
            <h3 className="font-semibold text-theme-primary mb-2">Description</h3>
            <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.description}</div>
          </div>

          {/* Constraints */}
          {problem.constraints && (
            <div className="bg-theme-secondary rounded-lg p-4 mb-4">
              <h3 className="font-semibold text-theme-primary mb-2">Constraints</h3>
              <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.constraints}</div>
            </div>
          )}

          {/* Input Format */}
          {problem.input_format && (
            <div className="bg-theme-secondary rounded-lg p-4 mb-4">
              <h3 className="font-semibold text-theme-primary mb-2">Input Format</h3>
              <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.input_format}</div>
            </div>
          )}

          {/* Output Format */}
          {problem.output_format && (
            <div className="bg-theme-secondary rounded-lg p-4 mb-4">
              <h3 className="font-semibold text-theme-primary mb-2">Output Format</h3>
              <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.output_format}</div>
            </div>
          )}

          {/* Examples (from public test cases) */}
          {problem.test_cases && problem.test_cases.length > 0 && (
            <div className="bg-theme-secondary rounded-lg p-4 mb-4">
              <h3 className="font-semibold text-theme-primary mb-2">Examples</h3>
              {problem.test_cases.map((tc, idx) => (
                <div key={tc.id || idx} className="mb-3 last:mb-0">
                  <div className="text-xs text-theme-muted mb-1">Sample {idx + 1}</div>
                  <div className="bg-theme-primary rounded p-3 font-mono text-sm">
                    <div className="mb-2">
                      <span className="text-theme-muted">Input:</span>
                      <pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{tc.input}</pre>
                    </div>
                    <div>
                      <span className="text-theme-muted">Output:</span>
                      <pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{tc.expected_output}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Code Editor */}
        <div className="w-1/2 flex flex-col">
          {/* Language Selector */}
          <div className="flex items-center gap-4 px-4 py-2 bg-theme-secondary border-b border-theme-border">
            <label className="text-sm text-theme-muted">Language:</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={isSubmitted || isExpired}
              className="bg-theme-primary text-theme-primary border border-theme-border rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {LANGUAGES.filter((l) => problem.supported_languages?.includes(l.value)).map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>

            {isSubmitted && (
              <span className="text-green-400 text-sm font-semibold">
                ✓ Submitted — Score: {submittedProblems[currentProblemIndex]?.score}/{submittedProblems[currentProblemIndex]?.max_score}
              </span>
            )}
          </div>

          {/* Code Editor */}
          <div className="flex-1">
            <CodeEditor
              language={language === 'python3' ? 'python' : language === 'cpp' ? 'cpp' : 'java'}
              value={sourceCode}
              onChange={(val) => setSourceCode(val || '')}
              height="100%"
            />
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-4 px-4 py-3 bg-theme-secondary border-t border-theme-border">
            <button
              onClick={handleRunCode}
              disabled={running || isSubmitted || isExpired}
              className={`px-6 py-2 rounded-lg font-semibold text-sm transition-colors ${
                running || isSubmitted || isExpired
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-blue-600 hover:bg-blue-700 text-white'
              }`}
            >
              {running ? '⏳ Running...' : '▶ Run Code'}
            </button>

            <button
              onClick={handleSubmitSolution}
              disabled={submitting || isSubmitted || isExpired}
              className={`px-6 py-2 rounded-lg font-semibold text-sm transition-colors ${
                submitting || isSubmitted || isExpired
                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              }`}
            >
              {submitting ? '⏳ Submitting...' : isSubmitted ? '✓ Submitted' : '🚀 Submit Solution'}
            </button>
          </div>

          {/* Run Results */}
          <TestResultsPanel runResults={runResults} />
        </div>
      </div>
    </div>
  );
};

export default CodingTest;
