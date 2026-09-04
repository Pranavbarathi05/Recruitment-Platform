import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import CodeEditor from '../components/CodeEditor';

/**
 * Combined Assessment Workspace
 *
 * ONE attempt contains BOTH MCQ and Coding sections.
 * ONE shared timer. ONE final submission.
 *
 * Layout: Viewport-locked IDE style (LeetCode-inspired)
 * - No document-level scrolling
 * - Fixed header with tabs and timer
 * - Independent scrolling for problem statements
 * - Monaco editor fills available space
 * - Action bar always visible
 */

const CODING_LANGUAGES = [
  { value: 'python3', label: 'Python 3' },
  { value: 'cpp', label: 'C++' },
  { value: 'java', label: 'Java' },
];

const getDefaultStarter = (lang, problem) => {
  // Use problem's per-language starter code if available
  if (problem?.starter_code?.[lang]) {
    return problem.starter_code[lang];
  }
  // Fallback defaults
  switch (lang) {
    case 'python3': return '# Write your solution here\nclass Solution:\n    def solve(self, *args):\n        pass\n';
    case 'cpp': return 'class Solution {\npublic:\n    // Write your solution here\n};\n';
    case 'java': return 'class Solution {\n    // Write your solution here\n}\n';
    default: return '';
  }
};

const AssessmentWorkspace = () => {
  const { attemptId } = useParams();
  const navigate = useNavigate();
  const { getAuthHeaders } = useAuth();

  const [activeTab, setActiveTab] = useState('mcq');

  // Shared state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [timeRemaining, setTimeRemaining] = useState(0);
  const [attemptData, setAttemptData] = useState(null);

  // MCQ state
  const [mcqQuestions, setMcqQuestions] = useState([]);
  const [mcqAnswers, setMcqAnswers] = useState({});
  const [mcqIndex, setMcqIndex] = useState(0);
  const [hasMcq, setHasMcq] = useState(false);

  // Coding state — per-problem { [problemId]: { code, language } }
  const [codingProblems, setCodingProblems] = useState([]);
  const [codingStates, setCodingStates] = useState({});
  const [codingIndex, setCodingIndex] = useState(0);
  const [codingRunning, setCodingRunning] = useState(false);
  const [codingSubmitting, setCodingSubmitting] = useState(false);
  const [codingRunResults, setCodingRunResults] = useState(null);
  const [codingSubmissions, setCodingSubmissions] = useState({});
  const [hasCoding, setHasCoding] = useState(false);

  const autosaveTimerRef = useRef(null);
  const lastSavedRef = useRef({}); // { [problemId]: lastSavedCode }

  const apiUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  // ========== FETCH ATTEMPT DATA ==========
  useEffect(() => {
    if (!attemptId) return;

    const fetchAll = async () => {
      try {
        setLoading(true);

        // Fetch MCQ questions
        const mcqResp = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/questions`, { credentials: 'include' });
        let mcqData = null;
        if (mcqResp.ok) {
          mcqData = await mcqResp.json();
          setMcqQuestions(mcqData.questions || []);
          setMcqAnswers(mcqData.answers || {});
          setAttemptData(mcqData);
          setHasMcq((mcqData.questions || []).length > 0);

          if (mcqData.expires_at) {
            const remaining = Math.max(0, Math.floor((new Date(mcqData.expires_at).getTime() - Date.now()) / 1000));
            setTimeRemaining(remaining);
          }
        }

        // Fetch coding problems
        const codingResp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/problems`, { credentials: 'include' });
        if (codingResp.ok) {
          const codingData = await codingResp.json();
          const problems = codingData.problems || [];
          setCodingProblems(problems);
          setHasCoding(problems.length > 0);

          // Initialize per-problem state from drafts or starter code
          const states = {};
          const subs = {};
          problems.forEach((p) => {
            if (p.draft) {
              states[p.id] = { code: p.draft.source_code, language: p.draft.language || 'python3' };
            } else {
              const defaultLang = p.supported_languages?.[0] || 'python3';
              states[p.id] = { code: getDefaultStarter(defaultLang, p), language: defaultLang };
            }
            if (p.submission_status) {
              subs[p.id] = { status: p.submission_status };
            }
          });
          setCodingStates(states);
          setCodingSubmissions(subs);
        }

        // Default to MCQ if available, else Coding
        if (mcqData && (mcqData.questions || []).length > 0) {
          setActiveTab('mcq');
        } else {
          setActiveTab('coding');
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchAll();
  }, [attemptId, apiUrl]);

  // ========== SHARED TIMER ==========
  useEffect(() => {
    if (timeRemaining <= 0 && attemptData && !loading) {
      handleSubmitAll();
      return;
    }
    const interval = setInterval(() => {
      setTimeRemaining((prev) => {
        if (prev <= 1) { clearInterval(interval); return 0; }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [timeRemaining <= 0 && attemptData && !loading]);

  // ========== CODING: AUTOSAVE (per-problem) ==========
  useEffect(() => {
    if (!hasCoding || codingProblems.length === 0 || codingIndex >= codingProblems.length) return;
    const problem = codingProblems[codingIndex];
    if (!problem) return;

    const currentCode = codingStates[problem.id]?.code || '';
    const lastSaved = lastSavedRef.current[problem.id];
    if (currentCode === lastSaved) return;

    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(async () => {
      // Cookie auth — always available
      const lang = codingStates[problem.id]?.language || 'python3';
      try {
        await fetch(`${apiUrl}/coding/attempt/${attemptId}/draft`, {
          method: 'PUT', headers: getAuthHeaders(), credentials: 'include',
          body: JSON.stringify({ problem_id: problem.id, language: lang, source_code: currentCode }),
        });
        lastSavedRef.current[problem.id] = currentCode;
      } catch { /* silent */ }
    }, 2000);
    return () => { if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current); };
  }, [codingStates, codingIndex, codingProblems, hasCoding, attemptId, apiUrl]);

  // ========== MCQ: SAVE ANSWER ==========
  const saveMcqAnswer = useCallback(async (questionId, option) => {
    // Update local state with functional updater (always fresh)
    setMcqAnswers((prev) => {
      const next = { ...prev, [questionId]: option };
      // Persist to backend (fire-and-forget, using ref for stable headers)
      if (attemptId) {
        fetch(`${apiUrl}/assessment/attempt/${attemptId}/answers`, {
          method: 'PUT', headers: getAuthHeaders(), credentials: 'include',
          body: JSON.stringify({ question_id: questionId, selected_option: option }),
        }).catch(() => {});
      }
      return next;
    });
  }, [attemptId, apiUrl]);

  // Wrapper to get current problem's state
  const getCurrentCodingProblem = useCallback(() => {
    const problem = codingProblems[codingIndex];
    if (!problem) return null;
    return { problem, state: codingStates[problem.id] || { code: '', language: 'python3' } };
  }, [codingProblems, codingIndex, codingStates]);

  // ========== CODING: RUN CODE ==========
  const handleRunCode = async () => {
    const current = getCurrentCodingProblem();
    if (!current || codingRunning) return;
    const { problem, state } = current;
    setCodingRunning(true);
    setCodingRunResults(null);
    try {
      const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/run`, {
        method: 'POST', headers: getAuthHeaders(), credentials: 'include',
        body: JSON.stringify({ problem_id: problem.id, language: state.language, source_code: state.code }),
      });
      const result = await resp.json();
      setCodingRunResults(result);
    } catch (err) {
      setCodingRunResults({ all_passed: false, results: [], error: err.message });
    } finally {
      setCodingRunning(false);
    }
  };

  // ========== CODING: SUBMIT SOLUTION ==========
  const handleSubmitSolution = async () => {
    const current = getCurrentCodingProblem();
    if (!current || codingSubmitting) return;
    const { problem, state } = current;
    setCodingSubmitting(true);
    try {
      const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/submit`, {
        method: 'POST', headers: getAuthHeaders(), credentials: 'include',
        body: JSON.stringify({ problem_id: problem.id, language: state.language, source_code: state.code }),
      });
      if (resp.ok) {
        const result = await resp.json();
        setCodingSubmissions((prev) => ({ ...prev, [problem.id]: result }));
        setCodingRunResults(null);
      }
    } catch { /* handled */ } finally {
      setCodingSubmitting(false);
    }
  };

  // ========== FINAL SUBMISSION ==========
  const handleSubmitAll = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const resp = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/submit`, {
        method: 'POST', headers: getAuthHeaders(), credentials: 'include',
      });
      if (!resp.ok && resp.status !== 409) {
        const err = await resp.json();
        throw new Error(err.detail || 'Failed to submit');
      }
    } catch { /* navigate regardless */ }
    navigate(`/assessment/${attemptId}/submitted`);
  };

  // ========== HELPERS ==========
  const formatTime = (s) => `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

  // Current coding problem helpers
  const currentCodingProblem = codingProblems[codingIndex] || null;
  const currentCodingState = currentCodingProblem ? (codingStates[currentCodingProblem.id] || { code: '', language: 'python3' }) : { code: '', language: 'python3' };

  // ========== LOADING / ERROR ==========
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-theme-primary">
        <div className="animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-blue-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center bg-theme-primary">
        <div className="text-center bg-theme-secondary rounded-lg p-8 max-w-md">
          <h2 className="text-2xl font-bold text-theme-primary mb-4">Error</h2>
          <p className="text-theme-muted mb-6">{error}</p>
          <button onClick={() => navigate('/domains')} className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold">
            Back to Domains
          </button>
        </div>
      </div>
    );
  }

  const isWarning = timeRemaining <= 300 && timeRemaining > 0;

  return (
    /* ROOT: flex-1 fills remaining viewport after Navbar. No overflow on body. */
    <div className="flex-1 flex flex-col min-h-0 bg-theme-primary overflow-hidden">

      {/* ===== ASSESSMENT HEADER — always visible, never scrolls ===== */}
      <div className="shrink-0 bg-theme-secondary border-b border-theme-border px-6 py-3 flex items-center justify-between z-10">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-bold text-theme-primary">DSC Recruitment Assessment</h1>
          {/* Section Tabs */}
          <div className="flex bg-theme-primary rounded-lg p-1">
            {hasMcq && (
              <button
                onClick={() => setActiveTab('mcq')}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'mcq' ? 'bg-blue-600 text-white' : 'text-theme-muted hover:text-theme-primary'
                }`}
              >
                MCQ ({mcqQuestions.length})
              </button>
            )}
            {hasCoding && (
              <button
                onClick={() => setActiveTab('coding')}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'coding' ? 'bg-blue-600 text-white' : 'text-theme-muted hover:text-theme-primary'
                }`}
              >
                Coding ({codingProblems.length})
              </button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className={`px-4 py-2 rounded-lg font-mono text-lg font-bold ${
            isWarning ? 'bg-red-900/50 text-red-300 border-2 border-red-500 animate-pulse'
              : 'bg-blue-900/50 text-blue-300 border-2 border-blue-500'
          }`}>
            ⏱ {formatTime(timeRemaining)}
          </div>
          <button onClick={handleSubmitAll} disabled={submitting}
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg font-semibold text-sm disabled:opacity-50">
            {submitting ? 'Submitting...' : 'Finish Assessment'}
          </button>
        </div>
      </div>

      {/* ===== WORKSPACE CONTENT — fills remaining height, no overflow ===== */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {/* MCQ Section */}
        {activeTab === 'mcq' && (
          <MCQSection
            questions={mcqQuestions}
            answers={mcqAnswers}
            currentIndex={mcqIndex}
            setCurrentIndex={setMcqIndex}
            saveAnswer={saveMcqAnswer}
          />
        )}

        {/* Coding Section */}
        {activeTab === 'coding' && currentCodingProblem && (
          <CodingSection
            attemptId={attemptId}
            problems={codingProblems}
            currentIndex={codingIndex}
            setCurrentIndex={setCodingIndex}
            language={currentCodingState.language}
            setLanguage={(lang) => setCodingStates((prev) => ({
              ...prev,
              [currentCodingProblem.id]: { ...prev[currentCodingProblem.id], language: lang },
            }))}
            sourceCode={currentCodingState.code}
            setSourceCode={(code) => setCodingStates((prev) => ({
              ...prev,
              [currentCodingProblem.id]: { ...prev[currentCodingProblem.id], code },
            }))}
            running={codingRunning}
            submitting={codingSubmitting}
            runResults={codingRunResults}
            submissions={codingSubmissions}
            onRun={handleRunCode}
            onSubmit={handleSubmitSolution}
          />
        )}
      </div>
    </div>
  );
};


// ============================================================
// MCQ SUB-COMPONENT
// ============================================================

function MCQSection({ questions, answers, currentIndex, setCurrentIndex, saveAnswer }) {
  if (questions.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-theme-muted">
        <p>No MCQ questions in this assessment.</p>
      </div>
    );
  }

  const q = questions[currentIndex];
  const answeredCount = Object.keys(answers).length;

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <p className="text-theme-muted">
            Question {currentIndex + 1} of {questions.length}
            {q.domainName && <span className="ml-2">· {q.domainName}</span>}
          </p>
          <span className="text-theme-muted text-sm">{answeredCount}/{questions.length} answered</span>
        </div>

        <div className="w-full bg-theme-secondary rounded-full h-2 mb-6">
          <div className="bg-blue-500 h-2 rounded-full transition-all" style={{ width: `${((currentIndex + 1) / questions.length) * 100}%` }} />
        </div>

        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <h2 className="text-lg font-semibold text-theme-primary mb-6">{q.question_text}</h2>
          <div className="space-y-3">
            {['A', 'B', 'C', 'D'].map((opt) => {
              const text = q[`option_${opt.toLowerCase()}`];
              const selected = answers[q.id] === opt;
              return (
                <button key={opt} onClick={() => saveAnswer(q.id, opt)}
                  className={`w-full text-left p-4 rounded-lg border-2 transition-all ${
                    selected ? 'border-blue-500 bg-blue-900/30' : 'border-theme-primary bg-theme-primary hover:border-blue-400'
                  }`}>
                  <span className="font-bold mr-3">{opt}.</span>{text}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex justify-between items-center">
          <button onClick={() => setCurrentIndex((p) => Math.max(0, p - 1))} disabled={currentIndex === 0}
            className="px-6 py-2 rounded-lg bg-theme-secondary text-theme-primary disabled:opacity-50">Previous</button>
          <div className="hidden md:flex flex-wrap gap-1 max-w-md">
            {questions.map((qq, i) => (
              <button key={qq.id} onClick={() => setCurrentIndex(i)}
                className={`w-8 h-8 rounded text-sm font-medium ${
                  i === currentIndex ? 'bg-blue-600 text-white' : answers[qq.id] ? 'bg-green-600 text-white' : 'bg-theme-secondary text-theme-muted'
                }`}>{i + 1}</button>
            ))}
          </div>
          {currentIndex < questions.length - 1 ? (
            <button onClick={() => setCurrentIndex((p) => p + 1)}
              className="px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold">Next</button>
          ) : null}
        </div>
      </div>
    </div>
  );
}


// ============================================================
// CODING SUB-COMPONENT
// LeetCode-style split pane layout
// ============================================================

function CodingSection({
  problems, currentIndex, setCurrentIndex,
  language, setLanguage, sourceCode, setSourceCode,
  running, submitting, runResults, submissions, onRun, onSubmit,
}) {

  if (problems.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-theme-muted">
        <p>No coding problems in this assessment.</p>
      </div>
    );
  }

  const problem = problems[currentIndex];
  const sub = submissions[problem.id];
  const isSubmitted = !!sub;

  return (
    /* Full height, no overflow, horizontal split */
    <div className="h-full flex min-h-0 overflow-hidden">

      {/* ===== PROBLEM TABS (left edge) ===== */}
      {problems.length > 1 && (
        <div className="w-12 shrink-0 bg-theme-secondary border-r border-theme-border flex flex-col items-center py-2 gap-1">
          {problems.map((p, idx) => (
            <button key={p.id} onClick={() => setCurrentIndex(idx)}
              className={`w-8 h-8 rounded text-xs font-bold ${
                idx === currentIndex ? 'bg-blue-600 text-white' : submissions[p.id] ? 'bg-green-700 text-white' : 'bg-theme-tertiary text-theme-muted'
              }`}>{idx + 1}</button>
          ))}
        </div>
      )}

      {/* ===== LEFT PANE: Problem Statement ===== */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0 border-r border-theme-border">
        {/* Problem title bar */}
        <div className="shrink-0 px-6 py-3 bg-theme-secondary border-b border-theme-border">
          <div className="flex items-center gap-3">
            <h2 className="text-xl font-bold text-theme-primary">{problem.title}</h2>
            <span className="text-sm text-theme-muted">{problem.points} pts</span>
          </div>
          {problem.function_signature && (
            <div className="mt-1 font-mono text-xs text-blue-400 bg-theme-primary rounded px-2 py-1 inline-block">
              {problem.function_signature}
            </div>
          )}
        </div>

        {/* Scrollable problem content */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6">
          <div className="space-y-4">
            <div className="bg-theme-secondary rounded-lg p-4">
              <h3 className="font-semibold text-theme-primary mb-2">Description</h3>
              <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.description}</div>
            </div>

            {problem.constraints && (
              <div className="bg-theme-secondary rounded-lg p-4">
                <h3 className="font-semibold text-theme-primary mb-2">Constraints</h3>
                <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.constraints}</div>
              </div>
            )}

            {problem.input_format && (
              <div className="bg-theme-secondary rounded-lg p-4">
                <h3 className="font-semibold text-theme-primary mb-2">Input Format</h3>
                <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.input_format}</div>
              </div>
            )}

            {problem.output_format && (
              <div className="bg-theme-secondary rounded-lg p-4">
                <h3 className="font-semibold text-theme-primary mb-2">Output Format</h3>
                <div className="text-theme-secondary text-sm whitespace-pre-wrap">{problem.output_format}</div>
              </div>
            )}

            {problem.test_cases?.length > 0 && (
              <div className="bg-theme-secondary rounded-lg p-4">
                <h3 className="font-semibold text-theme-primary mb-2">Examples</h3>
                {problem.test_cases.map((tc, idx) => (
                  <div key={tc.id || idx} className="mb-3 last:mb-0">
                    <div className="text-xs text-theme-muted mb-1">Example {idx + 1}</div>
                    <div className="bg-theme-primary rounded p-3 font-mono text-sm">
                      {tc.arguments ? (
                        <>
                          <div className="mb-2">
                            <span className="text-theme-muted">Input:</span>
                            <pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{JSON.stringify(tc.arguments, null, 2)}</pre>
                          </div>
                          <div>
                            <span className="text-theme-muted">Output:</span>
                            <pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{JSON.stringify(tc.expected_output)}</pre>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="mb-2"><span className="text-theme-muted">Input:</span><pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{tc.input}</pre></div>
                          <div><span className="text-theme-muted">Output:</span><pre className="text-theme-secondary mt-1 whitespace-pre-wrap">{tc.expected_output}</pre></div>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ===== RIGHT PANE: Code Editor ===== */}
      <div className="w-[50%] min-w-[320px] flex flex-col min-h-0">

        {/* Language selector bar */}
        <div className="shrink-0 flex items-center gap-4 px-4 py-2 bg-theme-secondary border-b border-theme-border">
          <label className="text-sm text-theme-muted">Language:</label>
          <select value={language} onChange={(e) => setLanguage(e.target.value)} disabled={isSubmitted}
            className="bg-theme-primary text-theme-primary border border-theme-border rounded px-3 py-1.5 text-sm">
            {CODING_LANGUAGES.filter((l) => problem.supported_languages?.includes(l.value)).map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
          {isSubmitted && <span className="text-green-400 text-sm font-semibold">✓ Submitted</span>}
        </div>

        {/* Monaco Editor — takes remaining space */}
        <div className="flex-1 min-h-0 relative">
          <CodeEditor
            key={problem.id}
            language={language === 'python3' ? 'python' : language === 'cpp' ? 'cpp' : 'java'}
            value={sourceCode} onChange={(val) => setSourceCode(val || '')}
          />
        </div>

        {/* Action Bar — always visible */}
        <div className="shrink-0 flex items-center gap-4 px-4 py-3 bg-theme-secondary border-t border-theme-border">
          <button onClick={onRun} disabled={running || isSubmitted}
            className={`px-6 py-2 rounded-lg font-semibold text-sm ${running || isSubmitted ? 'bg-gray-600 text-gray-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700 text-white'}`}>
            {running ? '⏳ Running...' : '▶ Run Code'}
          </button>
          <button onClick={onSubmit} disabled={submitting || isSubmitted}
            className={`px-6 py-2 rounded-lg font-semibold text-sm ${submitting || isSubmitted ? 'bg-gray-600 text-gray-400 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700 text-white'}`}>
            {submitting ? '⏳ Submitting...' : isSubmitted ? '✓ Submitted' : '🚀 Submit Solution'}
          </button>
        </div>

        {/* Test Results Panel — bottom of right pane, scrollable */}
        {runResults && (
          <div className="shrink-0 h-48 border-t border-theme-border px-4 py-3 bg-theme-secondary overflow-y-auto">
            <h4 className="font-semibold text-theme-primary mb-2 text-sm">
              Test Results {runResults.all_passed ? '— All Passed ✓' : ''}
            </h4>
            {runResults.error ? (
              <div className="text-red-400 text-sm">{runResults.error}</div>
            ) : (
              <div className="space-y-2">
                {(runResults.results || []).map((r, idx) => (
                  <div key={r.id || idx} className={`text-sm p-2 rounded ${r.passed ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'}`}>
                    <span className="font-mono">{r.passed ? '✓' : '✗'} Sample {idx + 1}</span>
                    {!r.passed && r.actual_output !== undefined && (
                      <div className="mt-1 text-xs">
                        <div>Expected: <code className="text-green-200">{r.expected_output}</code></div>
                        <div>Got: <code className="text-red-200">{r.actual_output || '(empty)'}</code></div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}


export default AssessmentWorkspace;
