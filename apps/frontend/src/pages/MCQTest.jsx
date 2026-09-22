import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import CodeEditor from '../components/CodeEditor';
import TestResultsPanel from '../components/TestResultsPanel';
import SqlWasmChallenge from '../components/SqlWasmChallenge';
import PandasWasmChallenge from '../components/PandasWasmChallenge';
import { runCodeLocally, isClientRunnable } from '../execution/runner';
import { generatePythonStarterCode } from '../utils/codingStarterCode';
import { countWords, limitToWords } from '../utils/wordLimit';

// Hands-On challenge — the SQLi "Employee Portal" server is reached through
// the same Gateway as the rest of the platform (Traefik routes /challenge/*
// to it; see gateway/docker-compose.yml). A relative URL keeps the candidate
// on the Gateway origin — internal challenge hosts/ports are never exposed.
// The challenge's challenge_url field is admin metadata for record-keeping;
// candidate rendering always uses this Gateway-relative path.
const CHALLENGE_IFRAME_URL = '/challenge/';

// How long to wait for requestFullscreen() to settle before treating it as
// failed. Chrome answers in milliseconds; the bound only exists so a browser
// that never settles the promise cannot strand the candidate on a disabled
// "Entering…" button.
const FULLSCREEN_SETTLE_TIMEOUT_MS = 3000;

/**
 * Resolve to 'resolved' | 'rejected' | 'timeout'. The timer is always cleared
 * once the request settles, so no stray timeouts are left behind.
 */
function promiseWithTimeout(promise, ms) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => finish('timeout'), ms);
    Promise.resolve(promise).then(
      () => finish('resolved'),
      () => finish('rejected'),
    );
  });
}

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
  { value: 'c', label: 'C' },
];

const INT32_MIN = -2147483648;
const INT32_MAX = 2147483647;

// ---- Starter generation (mirrors the backend harness contract) ----
//
// The candidate writes ONLY the function/method; the hidden harness invokes it
// (apps/backend/services/harness.py, and the mirror in execution/harness.js):
//
//   python3: class_name set -> _instance = ClassName(); _instance.fn(...)
//            class_name null -> free call fn(...)
//   cpp:     class_name set -> ClassName _obj; _obj.fn(...)
//            class_name null -> free call fn(...) with native args materialized
//                               from the JSON test data
//   java:    the harness ALWAYS instantiates class_name or "Solution" and calls
//            the instance method _obj.fn(...) (legacy fallback included)
//
// Types: function_signature verbatim when configured; otherwise inferred from
// the first public test case's arguments/expected_output using the SAME
// JSON-shape rules as the backend's legacy arg specs (_cpp_legacy_arg_spec /
// _java_legacy_arg_spec), so the starter and the harness always agree.

function inferCppType(v) {
  if (v === null || v === undefined) return 'int';
  if (typeof v === 'boolean') return 'bool';
  if (typeof v === 'string') return 'std::string';
  if (typeof v === 'number') {
    if (!Number.isInteger(v)) return 'double';
    if (v < INT32_MIN || v > INT32_MAX) return 'long long';
    return 'int';
  }
  if (Array.isArray(v)) {
    if (v.length && v.every((x) => typeof x === 'string')) return 'std::vector<std::string>';
    if (v.length && v.every((x) => Array.isArray(x))) {
      if (v[0] && v[0].length && v[0].every((x) => typeof x === 'string')) {
        return 'std::vector<std::vector<std::string>>';
      }
      return 'std::vector<std::vector<int>>';
    }
    if (v.length && v.every((x) => typeof x === 'boolean')) return 'std::vector<bool>';
    if (v.length && v.every((x) => typeof x === 'number')) {
      if (v.some((x) => !Number.isInteger(x))) return 'std::vector<double>';
      if (v.some((x) => x < INT32_MIN || x > INT32_MAX)) return 'std::vector<long long>';
      return 'std::vector<int>';
    }
    return 'std::vector<int>';
  }
  return 'int';
}

function inferJavaType(v) {
  if (v === null || v === undefined) return 'int';
  if (typeof v === 'boolean') return 'boolean';
  if (typeof v === 'string') return 'String';
  if (typeof v === 'number') {
    if (!Number.isInteger(v)) return 'double';
    if (v < INT32_MIN || v > INT32_MAX) return 'long';
    return 'int';
  }
  if (Array.isArray(v)) {
    if (v.length && v.every((x) => typeof x === 'string')) return 'String[]';
    if (v.length && v.every((x) => typeof x === 'number')) {
      if (v.some((x) => !Number.isInteger(x))) return 'double[]';
      if (v.some((x) => x < INT32_MIN || x > INT32_MAX)) return 'long[]';
      return 'int[]';
    }
    if (v.length && v.every((x) => typeof x === 'boolean')) return 'boolean[]';
    return 'int[]';
  }
  return 'int';
}

function inferLangType(lang, v) {
  return lang === 'cpp' ? inferCppType(v) : inferJavaType(v);
}

function getStarterTypes(problem, lang) {
  // Parameter arity/types: first public test case with arguments.
  const tcs = problem?.test_cases || [];
  const firstWithArgs = tcs.find(
    (tc) => Array.isArray(tc.arguments) && tc.arguments.length > 0
  );
  const args = firstWithArgs ? firstWithArgs.arguments : [];
  const params = args.map((v, i) => ({ type: inferLangType(lang, v), name: `arg${i + 1}` }));
  // Return type: shape of the first expected output.
  const retType = tcs.length ? inferLangType(lang, tcs[0].expected_output) : (lang === 'cpp' ? 'int' : 'int');
  return { params, retType };
}

function getStarterParamsText(params) {
  return params.map((p) => `${p.type} ${p.name}`).join(', ');
}

const getDefaultStarter = (lang, problem) => {
  // Use problem's per-language starter code if available
  if (problem?.starter_code?.[lang] && problem.starter_code[lang].trim()) {
    return problem.starter_code[lang];
  }

  const functionName = problem?.function_name || 'solve';
  const className = problem?.class_name || null;
  const signature = (problem?.function_signature || '').trim();

  // --- Python ---
  if (lang === 'python3') {
    if (signature) {
      // Existing metadata mechanism: parses names, honors class_name.
      try {
        return generatePythonStarterCode(functionName, className, signature);
      } catch {
        /* fall through to inference */
      }
    }
    const { params } = getStarterTypes(problem, lang);
    const names = params.map((p) => p.name).join(', ');
    if (className) {
      return (
        `class ${className}:\n` +
        `    def ${functionName}(self, ${names}):\n` +
        `        # Write your solution here\n` +
        `        pass\n`
      );
    }
    return (
      `def ${functionName}(${names}):\n` +
      `    # Write your solution here\n` +
      `    pass\n`
    );
  }

  // --- C++ ---
  if (lang === 'cpp') {
    const body = (indent) => `${indent}// Write your solution here`;
    if (signature) {
      const head = signature.replace(/;\s*$/, '');
      if (className) {
        return (
          `class ${className} {\npublic:\n` +
          `    ${head} {\n        ${body('')}\n    }\n` +
          `};\n`
        );
      }
      return `${head} {\n    ${body('')}\n}\n`;
    }
    const { params, retType } = getStarterTypes(problem, lang);
    const paramsText = getStarterParamsText(params);
    if (className) {
      return (
        `class ${className} {\npublic:\n` +
        `    ${retType} ${functionName}(${paramsText}) {\n` +
        `        ${body('')}\n    }\n` +
        `};\n`
      );
    }
    return `${retType} ${functionName}(${paramsText}) {\n    ${body('')}\n}\n`;
  }

  // --- C (server-side only; the harness requires an explicit C function_signature) ---
  if (lang === 'c') {
    // Mirror the backend's C starter contract (services/harness.py:
    // generate_c_starter_code): the candidate sees ONLY the verbatim signature
    // function — no main(), no I/O. The generated harness owns invocation.
    const cSignature = (signature || '').trim().replace(/;\s*$/, '');
    if (cSignature) {
      const usesBool = /\b(_Bool|bool)\b/.test(cSignature);
      return (
        (usesBool ? '#include <stdbool.h>\n\n' : '') +
        `${cSignature} {\n    // Write your solution here\n}\n`
      );
    }
    return (
      '// This problem needs a C function_signature (e.g. int add(int a, int b)).\n' +
      `int ${functionName}(void) {\n    // Write your solution here\n}\n`
    );
  }

  // --- Java (harness always invokes an instance method on class_name or "Solution") ---
  {
    const javaClassName = className || 'Solution';
    let method;
    if (signature) {
      method = signature.replace(/;\s*$/, '').trim();
      if (!/^public\b/.test(method)) method = `public ${method}`;
      method = `${method} {\n        // Write your solution here\n    }`;
    } else {
      const { params, retType } = getStarterTypes(problem, lang);
      method = `public ${retType} ${functionName}(${getStarterParamsText(params)}) {\n        // Write your solution here\n    }`;
    }
    return `class ${javaClassName} {\n    ${method}\n}\n`;
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
  const [submitError, setSubmitError] = useState(null);
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

  // Descriptive state
  const [descriptiveQuestions, setDescriptiveQuestions] = useState([]);
  const [descriptiveAnswers, setDescriptiveAnswers] = useState({});
  const [descriptiveIndex, setDescriptiveIndex] = useState(0);
  const [hasDescriptive, setHasDescriptive] = useState(false);

  // Hands-On state
  const [handsOnQuestions, setHandsOnQuestions] = useState([]);
  const [handsOnResults, setHandsOnResults] = useState({}); // questionId -> result
  const [hasHandsOn, setHasHandsOn] = useState(false);

  const autosaveTimerRef = useRef(null);
  const lastSavedRef = useRef({}); // { [problemId]: lastSavedCode }

  // ========== FULLSCREEN PROCTORING ==========
  // While the attempt is active the candidate must stay in fullscreen. Leaving
  // it shows a blocking overlay with a 15-second countdown; hitting zero
  // submits the attempt through the SAME authoritative submit path as the
  // "Finish Assessment" button.
  const [fullscreenExited, setFullscreenExited] = useState(false);
  const [fullscreenSeconds, setFullscreenSeconds] = useState(15);
  const [fullscreenError, setFullscreenError] = useState('');
  const [restoringFullscreen, setRestoringFullscreen] = useState(false);

  // Entry gate. Fullscreen is normally entered from the "Start Assessment"
  // click (the only user activation available before this page renders). If
  // the workspace could not inherit an active fullscreen session — deep link,
  // page refresh, or a rejected start-time request — the candidate is asked
  // for the gesture here instead of silently losing proctoring. The exit
  // penalty below is only ever armed after fullscreen was genuinely entered.
  const [fullscreenEntryRequired, setFullscreenEntryRequired] = useState(false);
  const [fullscreenEntryError, setFullscreenEntryError] = useState('');
  const [enteringFullscreen, setEnteringFullscreen] = useState(false);

  // Single submission guard shared by the manual button, the existing duration
  // timer and the fullscreen-timeout auto-submit.
  const hasSubmittedRef = useRef(false);
  const isSubmittingRef = useRef(false);
  // Fullscreen bookkeeping (refs so event listeners and timers never go stale).
  const fsEnteredRef = useRef(false);
  const fsExitTimerRef = useRef(null);
  const fsTimerRunningRef = useRef(false);
  const assessmentActiveRef = useRef(false);
  const submitRef = useRef(null);

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
          setDescriptiveQuestions(mcqData.descriptive_questions || []);
          setDescriptiveAnswers(mcqData.descriptive_answers || {});
          setHasDescriptive((mcqData.descriptive_questions || []).length > 0);
          setHandsOnQuestions(mcqData.hands_on_questions || []);
          setHandsOnResults(
            Object.fromEntries((mcqData.hands_on_results || []).map((r) => [r.question_id, r]))
          );
          setHasHandsOn((mcqData.hands_on_questions || []).length > 0);
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
              const lang = p.draft.language || 'python3';
              states[p.id] = { code: p.draft.source_code, language: lang, drafts: { [lang]: p.draft.source_code } };
            } else {
              const defaultLang = p.supported_languages?.[0] || 'python3';
              const starter = getDefaultStarter(defaultLang, p);
              states[p.id] = { code: starter, language: defaultLang, drafts: { [defaultLang]: starter } };
            }
            if (p.submission_status) {
              subs[p.id] = { status: p.submission_status };
            }
          });
          setCodingStates(states);
          setCodingSubmissions(subs);
        }

        // Default to first available section
        if (mcqData && (mcqData.questions || []).length > 0) {
          setActiveTab('mcq');
        } else if ((mcqData?.descriptive_questions || []).length > 0) {
          setActiveTab('descriptive');
        } else if ((mcqData?.hands_on_questions || []).length > 0) {
          setActiveTab('handson');
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

  // ========== DESCRIPTIVE: SAVE ANSWER ==========
  const saveDescriptiveAnswer = useCallback(async (questionId, text) => {
    setDescriptiveAnswers((prev) => {
      const next = { ...prev, [questionId]: text };
      if (attemptId) {
        fetch(`${apiUrl}/assessment/attempt/${attemptId}/descriptive-answers`, {
          method: 'PUT', headers: getAuthHeaders(), credentials: 'include',
          body: JSON.stringify({ question_id: questionId, answer_text: text }),
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

  // ========== HANDS-ON: SUBMIT (evidence + flag) ==========
  // One submission per challenge: the backend rejects a second PUT with 409
  // and returns a neutral ack (never verified/score), so the candidate is
  // not told whether their flag was correct.
  const submitHandsOn = useCallback(async (questionId, submittedInput, submittedFlag, clientScore) => {
    const body = { question_id: questionId, submitted_input: submittedInput, submitted_flag: submittedFlag };
    // WASM challenges send client_score; the backend caps it at max points.
    if (clientScore !== undefined && clientScore !== null) {
      body.client_score = clientScore;
      body.submitted_code = submittedInput;
    }
    const resp = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/hands-on`, {
      method: 'PUT', headers: getAuthHeaders(), credentials: 'include',
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (resp.status === 409) {
      // Backend enforces one submission per challenge: a 409 means a result
      // already exists (refresh, second tab, direct API call). Lock the form
      // with the neutral confirmation — never reveal correctness or score.
      setHandsOnResults((prev) => ({
        ...prev,
        [questionId]: {
          ...(prev[questionId] || {}),
          question_id: questionId,
          submitted_input: submittedInput,
          submitted_flag: (submittedFlag || '').trim(),
          submitted_at: new Date().toISOString(),
        },
      }));
      return { status: 'already_submitted' };
    }
    if (!resp.ok) {
      throw new Error(data.detail || 'Failed to submit challenge');
    }
    setHandsOnResults((prev) => ({
      ...prev,
      [questionId]: {
        ...(prev[questionId] || {}),
        question_id: questionId,
        submitted_input: submittedInput,
        submitted_flag: (submittedFlag || '').trim(),
        submitted_at: new Date().toISOString(),
      },
    }));
    return data;
  }, [attemptId, apiUrl, getAuthHeaders]);

  // ========== CODING: RUN CODE ==========
  //
  // Client-side execution (Web Worker + WASM) for languages with a browser
  // runtime — currently python3 via Pyodide. Run never touches the submission
  // flow and its result is feedback only, never authoritative scoring.
  // Languages without a client-side runtime fall back to the existing
  // server-side run endpoint so the platform keeps working.
  const runCodeOnServer = async (problem, state) => {
    const resp = await fetch(`${apiUrl}/coding/attempt/${attemptId}/run`, {
      method: 'POST', headers: getAuthHeaders(), credentials: 'include',
      body: JSON.stringify({ problem_id: problem.id, language: state.language, source_code: state.code }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to run code');
    }
    return resp.json();
  };

  const handleRunCode = async () => {
    const current = getCurrentCodingProblem();
    if (!current || codingRunning) return;
    const { problem, state } = current;
    setCodingRunning(true);
    setCodingRunResults(null);
    try {
      const result = isClientRunnable(state.language)
        ? await runCodeLocally({
            language: state.language,
            sourceCode: state.code,
            testCases: problem.test_cases || [], // public tests only
            functionName: problem.function_name || 'solve',
            className: problem.class_name || null,
            timeLimitMs: problem.time_limit_ms || 2000,
          })
        : await runCodeOnServer(problem, state);
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
  // One guard for every submit trigger (manual, duration timer, fullscreen
  // timeout). Refs — not state — so two triggers in the same tick can never
  // both fire before a re-render.
  const handleSubmitAll = async () => {
    if (hasSubmittedRef.current || isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const resp = await fetch(`${apiUrl}/assessment/attempt/${attemptId}/submit`, {
        method: 'POST', headers: getAuthHeaders(), credentials: 'include',
      });
      // 409 = the attempt was already finalized server-side (e.g. submit ran
      // twice, or the timer auto-submit raced a manual submit) — that is a
      // success from the candidate's point of view.
      if (!resp.ok && resp.status !== 409) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Submission failed (${resp.status})`);
      }
      // Finalized: stop proctoring and never submit again.
      hasSubmittedRef.current = true;
      assessmentActiveRef.current = false;
      clearFullscreenTimer();
      setFullscreenExited(false);
      navigate(`/assessment/${attemptId}/submitted`);
    } catch (err) {
      // NEVER navigate to the confirmation screen on a failed submit — the
      // attempt is NOT finalized and must stay resumable. Surface the error
      // and let the candidate retry; their answers are all still saved.
      setSubmitError(err.message || 'Submission failed. Please try again.');
    } finally {
      isSubmittingRef.current = false;
      setSubmitting(false);
    }
  };

  // Keep a ref to the latest submit function for listeners/timers declared
  // before it (they run after render, so this is always current).
  submitRef.current = handleSubmitAll;

  // ========== FULLSCREEN LIFECYCLE ==========
  const clearFullscreenTimer = useCallback(() => {
    if (fsExitTimerRef.current !== null) {
      clearInterval(fsExitTimerRef.current);
      fsExitTimerRef.current = null;
    }
    fsTimerRunningRef.current = false;
  }, []);

  const requestFullscreen = useCallback(async () => {
    const el = typeof document !== 'undefined' ? document.documentElement : null;
    if (!el || typeof el.requestFullscreen !== 'function') return false;
    // Mark the intent synchronously: a fullscreenchange for a genuine loss can
    // arrive before the request promise settles. Cleared again on failure.
    fsEnteredRef.current = true;

    let outcome = 'pending';
    try {
      // Some embedded/hosted browsers accept the request but never settle the
      // promise, which would leave the button stuck on "Entering…" forever.
      // Bound the wait; the fullscreenchange listener stays authoritative, so
      // a late success still clears the prompt.
      outcome = await promiseWithTimeout(el.requestFullscreen(), FULLSCREEN_SETTLE_TIMEOUT_MS);
    } catch {
      // Browser policy (no user gesture), permission, or unsupported — treat
      // as "could not enter" and never lock the candidate out.
      outcome = 'rejected';
    }

    if (outcome === 'resolved') return true;
    if (outcome === 'timeout' && typeof document !== 'undefined' && document.fullscreenElement) {
      return true;
    }
    fsEnteredRef.current = false;
    return false;
  }, []);

  const startFullscreenTimer = useCallback((skipIfRunning = false) => {
    if (skipIfRunning && fsTimerRunningRef.current) return;
    // Prevent duplicate intervals across rerenders.
    clearFullscreenTimer();
    fsTimerRunningRef.current = true;
    setFullscreenSeconds(15);
    fsExitTimerRef.current = setInterval(() => {
      setFullscreenSeconds((prev) => {
        if (prev <= 1) {
          if (fsExitTimerRef.current !== null) {
            clearInterval(fsExitTimerRef.current);
            fsExitTimerRef.current = null;
          }
          fsTimerRunningRef.current = false;
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, [clearFullscreenTimer]);

  const showFullscreenOverlay = useCallback(() => {
    if (hasSubmittedRef.current) return;
    setFullscreenError('');
    setFullscreenExited(true);
    startFullscreenTimer(true);
  }, [startFullscreenTimer]);

  // Watch fullscreen only while the attempt is genuinely active (in progress
  // and not yet submitted/scored). A submitted attempt never fetches attempt
  // data, so `assessmentActive` stays false and proctoring stays off.
  const assessmentActive = !loading && !error && !!attemptData && !hasSubmittedRef.current;

  useEffect(() => {
    assessmentActiveRef.current = assessmentActive;
    if (!assessmentActive || typeof document === 'undefined') return undefined;

    // Do NOT call requestFullscreen() here: a mount-time request has no user
    // activation and every browser rejects it. Fullscreen is requested from
    // the "Start Assessment" click instead (pages/Domains.jsx) — this effect
    // only adopts an already-active session or asks for a fresh gesture.
    const el = document.documentElement;
    const supported =
      !!el && typeof el.requestFullscreen === 'function' && document.fullscreenEnabled !== false;

    if (document.fullscreenElement) {
      // Pre-existing protection from before the workspace mounted, e.g. the
      // candidate refreshed the page while still in fullscreen.
      fsEnteredRef.current = true;
      setFullscreenEntryRequired(false);
    } else if (supported && !fsEnteredRef.current) {
      // No active session and no gesture yet: recovery (never a penalty).
      setFullscreenEntryRequired(true);
    }

    const onFullscreenChange = () => {
      if (!assessmentActiveRef.current || hasSubmittedRef.current) return;
      if (document.fullscreenElement) {
        fsEnteredRef.current = true;
        clearFullscreenTimer();
        setFullscreenExited(false);
        setFullscreenError('');
        setFullscreenEntryRequired(false);
        setFullscreenEntryError('');
      } else if (fsEnteredRef.current) {
        showFullscreenOverlay();
      }
    };

    document.addEventListener('fullscreenchange', onFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange);
  }, [assessmentActive, requestFullscreen, clearFullscreenTimer, showFullscreenOverlay]);

  // The countdown only runs while the overlay is up.
  useEffect(() => {
    if (!fullscreenExited) clearFullscreenTimer();
  }, [fullscreenExited, clearFullscreenTimer]);

  // Countdown reached zero: submit through the guarded path exactly once.
  useEffect(() => {
    if (fullscreenExited && fullscreenSeconds === 0) {
      submitRef.current?.();
    }
  }, [fullscreenExited, fullscreenSeconds]);

  // Unmount: drop listeners and timers, and release any fullscreen we hold.
  useEffect(() => () => {
    clearFullscreenTimer();
    if (typeof document !== 'undefined' && document.fullscreenElement && typeof document.exitFullscreen === 'function') {
      try { document.exitFullscreen(); } catch { /* ignore */ }
    }
  }, [clearFullscreenTimer]);

  const handleReturnToFullscreen = async () => {
    if (restoringFullscreen) return;
    setRestoringFullscreen(true);
    setFullscreenError('');
    const ok = await requestFullscreen();
    if (ok) {
      clearFullscreenTimer();
      setFullscreenExited(false);
      setFullscreenError('');
    } else {
      // Keep the overlay and the running countdown — do NOT reset the timer.
      setFullscreenError('Fullscreen could not be restored. Please try again.');
    }
    setRestoringFullscreen(false);
  };

  // Entry gate action: this is a real user gesture, so requestFullscreen() is
  // allowed. A rejection never starts the exit countdown — the candidate is
  // simply asked again.
  const handleEnterFullscreen = async () => {
    if (enteringFullscreen) return;
    setEnteringFullscreen(true);
    setFullscreenEntryError('');
    const ok = await requestFullscreen();
    if (ok) {
      setFullscreenEntryRequired(false);
    } else {
      setFullscreenEntryError('Fullscreen could not be enabled. Please try again.');
    }
    setEnteringFullscreen(false);
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
  // The assessment is non-interactive while either fullscreen prompt is up.
  const interactionLocked = fullscreenExited || fullscreenEntryRequired;

  return (
    /* ROOT: flex-1 fills remaining viewport after Navbar. No overflow on body. */
    <div className="flex-1 flex flex-col min-h-0 bg-theme-primary overflow-hidden">

      {/* Everything below the overlay is made inert while the candidate is out
          of fullscreen so pointer and keyboard interaction cannot reach the
          test. `inert` also removes the subtree from the tab order. */}
      <div
        className={interactionLocked ? 'flex-1 flex flex-col min-h-0 pointer-events-none select-none' : 'flex-1 flex flex-col min-h-0'}
        inert={interactionLocked ? true : undefined}
        aria-hidden={interactionLocked ? true : undefined}
      >

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
            {hasDescriptive && (
              <button
                onClick={() => setActiveTab('descriptive')}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'descriptive' ? 'bg-blue-600 text-white' : 'text-theme-muted hover:text-theme-primary'
                }`}
              >
                Descriptive ({descriptiveQuestions.length})
              </button>
            )}
            {hasHandsOn && (
              <button
                onClick={() => setActiveTab('handson')}
                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'handson' ? 'bg-blue-600 text-white' : 'text-theme-muted hover:text-theme-primary'
                }`}
              >
                Hands-On ({handsOnQuestions.length})
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

      {/* ===== SUBMIT ERROR BANNER — attempt NOT finalized, candidate can retry ===== */}
      {submitError && (
        <div role="alert" className="shrink-0 bg-red-900/40 border-b border-red-500 px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
          <p className="text-red-200 text-sm">
            <span className="font-bold">Submission failed:</span> {submitError}
            {' '}— your attempt has NOT been finalized; all saved answers are kept. Please retry.
          </p>
          <button
            onClick={handleSubmitAll}
            disabled={submitting}
            className="shrink-0 bg-green-600 hover:bg-green-700 text-white px-3 py-1.5 rounded text-sm font-semibold disabled:opacity-50"
          >
            {submitting ? 'Submitting…' : 'Retry submission'}
          </button>
        </div>
      )}

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

        {/* Descriptive Section */}
        {activeTab === 'descriptive' && (
          <DescriptiveSection
            questions={descriptiveQuestions}
            answers={descriptiveAnswers}
            currentIndex={descriptiveIndex}
            setCurrentIndex={setDescriptiveIndex}
            saveAnswer={saveDescriptiveAnswer}
          />
        )}

        {/* Hands-On Section */}
        {activeTab === 'handson' && (
          <HandsOnSection
            questions={handsOnQuestions}
            results={handsOnResults}
            onSubmit={submitHandsOn}
          />
        )}

        {/* Coding Section */}
        {activeTab === 'coding' && currentCodingProblem && (
          <CodingSection
            attemptId={attemptId}
            problems={codingProblems}
            currentIndex={codingIndex}
            setCurrentIndex={(idx) => {
              setCodingIndex(idx);
              setCodingRunResults(null); // clear results when switching problems
            }}
            language={currentCodingState.language}
            setLanguage={(lang) => setCodingStates((prev) => {
              const st = prev[currentCodingProblem.id] || { code: '', language: 'python3', drafts: {} };
              if (lang === st.language) return prev;
              // Save current code under the outgoing language, then load the new
              // language's own code: its typed draft if any, else its starter.
              const drafts = { ...st.drafts, [st.language]: st.code };
              const nextCode = drafts[lang] !== undefined ? drafts[lang] : getDefaultStarter(lang, currentCodingProblem);
              return {
                ...prev,
                [currentCodingProblem.id]: { ...st, language: lang, code: nextCode, drafts },
              };
            })}
            sourceCode={currentCodingState.code}
            setSourceCode={(code) => setCodingStates((prev) => {
              const st = prev[currentCodingProblem.id] || { code: '', language: 'python3', drafts: {} };
              return {
                ...prev,
                [currentCodingProblem.id]: { ...st, code, drafts: { ...st.drafts, [st.language]: code } },
              };
            })}
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

      {fullscreenExited ? (
        <FullscreenExitOverlay
          seconds={fullscreenSeconds}
          error={fullscreenError}
          busy={restoringFullscreen}
          submitError={submitError}
          onReturn={handleReturnToFullscreen}
        />
      ) : fullscreenEntryRequired && (
        <FullscreenEntryGate
          error={fullscreenEntryError}
          busy={enteringFullscreen}
          showSkip={!!fullscreenEntryError}
          onEnter={handleEnterFullscreen}
          onSkip={() => setFullscreenEntryRequired(false)}
        />
      )}
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
// DESCRIPTIVE SUB-COMPONENT
// ============================================================

function DescriptiveSection({ questions, answers, currentIndex, setCurrentIndex, saveAnswer }) {
  if (questions.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-theme-muted">
        <p>No descriptive questions in this assessment.</p>
      </div>
    );
  }

  const q = questions[currentIndex];
  const answeredCount = Object.keys(answers).length;
  // Hard input constraint: every change (typed, pasted, or editing a saved
  // answer) is constrained to the configured word limit before it is stored.
  // word_limit is NULL/undefined = unlimited (schema allows NULL or > 0).
  const wordLimit = q.word_limit || null;
  const currentText = limitToWords(answers[q.id] || '', wordLimit);
  const wordCount = countWords(currentText);

  return (
    <div className="h-full flex flex-col">
      {/* Question area */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-3xl mx-auto">
          {/* Progress bar */}
          <div className="flex items-center gap-4 mb-6">
            <span className="text-sm text-theme-muted">
              Question {currentIndex + 1} of {questions.length}
            </span>
            <span className="text-sm text-green-400">
              {answeredCount} answered
            </span>
          </div>

          {/* Question text */}
          <div className="bg-theme-secondary rounded-lg p-6 mb-4">
            <p className="text-theme-primary whitespace-pre-wrap text-lg leading-relaxed">{q.question_text}</p>
          </div>

          {/* Image */}
          {q.image_url && (
            <div className="mb-4">
              <img src={q.image_url} alt="Question image" className="max-h-80 rounded-lg border border-theme-secondary" />
            </div>
          )}

          {/* Answer textarea */}
          <div className="mt-4">
            <label className="block text-sm font-medium text-theme-primary mb-2">Your Answer</label>
            <textarea
              value={currentText}
              onChange={(e) => saveAnswer(q.id, limitToWords(e.target.value, wordLimit))}
              rows={10}
              className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary text-sm resize-y min-h-[200px]"
              placeholder="Type your answer here..."
            />
            <div className="flex justify-between mt-2 text-sm text-theme-muted">
              <span>
                Word count: {wordCount}{wordLimit ? ` / ${wordLimit}` : ''}
              </span>
              {wordLimit && (
                <span className="text-theme-muted">
                  Word limit: {wordLimit}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="shrink-0 bg-theme-secondary border-t border-theme-border px-6 py-3">
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
// HANDS-ON SUB-COMPONENT
// Shared challenge website + two-field submission (evidence + flag).
// ============================================================

function HandsOnSection({ questions, results, onSubmit }) {
  // Hooks must run unconditionally — the empty-state return comes after them.
  const q = questions[0];
  const result = q ? results[q.id] : undefined;

  // For CTF challenges
  const [sqlInput, setSqlInput] = useState(result?.submitted_input || '');
  const [flagInput, setFlagInput] = useState(result?.submitted_flag || '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  // One submission per challenge: a stored result (from the questions
  // endpoint or from a successful submit) locks the form permanently.
  const [submitted, setSubmitted] = useState(!!result);
  const submittedRef = useRef(!!result);

  if (questions.length === 0 || !q) {
    return (
      <div className="h-full flex items-center justify-center text-theme-muted">
        <p>No hands-on challenges in this assessment.</p>
      </div>
    );
  }

  // WASM challenge types: delegate to specialized components
  const challengeType = q.challenge_type;
  if (challengeType === 'sql_wasm') {
    return (
      <div className="h-full flex flex-col">
        {/* Challenge header */}
        <div className="shrink-0 bg-theme-secondary px-6 py-3 border-b border-theme-border">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-theme-primary">{q.title}</h2>
            <span className="text-xs px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded capitalize">{q.difficulty}</span>
            <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{q.points} pts</span>
            <span className="text-xs px-2 py-0.5 bg-orange-900/50 text-orange-300 rounded">SQL WASM</span>
            {submitted && <span className="text-xs px-2 py-0.5 rounded font-semibold bg-green-900/50 text-green-300">Submitted</span>}
          </div>
          <p className="text-theme-muted text-sm mt-1 line-clamp-2">{q.description}</p>
        </div>
        {/* Editor + Runner */}
        <div className="flex-1 min-h-0">
          <SqlWasmChallenge
            problem={q}
            onSubmit={async ({ questionId, submittedCode, clientScore }) => {
              await onSubmit(questionId, submittedCode, '', clientScore);
              submittedRef.current = true;
              setSubmitted(true);
            }}
            submitted={submitted}
          />
        </div>
      </div>
    );
  }

  if (challengeType === 'pandas_wasm') {
    return (
      <div className="h-full flex flex-col">
        {/* Challenge header */}
        <div className="shrink-0 bg-theme-secondary px-6 py-3 border-b border-theme-border">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-theme-primary">{q.title}</h2>
            <span className="text-xs px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded capitalize">{q.difficulty}</span>
            <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{q.points} pts</span>
            <span className="text-xs px-2 py-0.5 bg-orange-900/50 text-orange-300 rounded">Pandas WASM</span>
            {submitted && <span className="text-xs px-2 py-0.5 rounded font-semibold bg-green-900/50 text-green-300">Submitted</span>}
          </div>
          <p className="text-theme-muted text-sm mt-1 line-clamp-2">{q.description}</p>
        </div>
        {/* Editor + Runner */}
        <div className="flex-1 min-h-0">
          <PandasWasmChallenge
            problem={q}
            onSubmit={async ({ questionId, submittedCode, clientScore }) => {
              await onSubmit(questionId, submittedCode, '', clientScore);
              submittedRef.current = true;
              setSubmitted(true);
            }}
            submitted={submitted}
          />
        </div>
      </div>
    );
  }

  // Default: CTF challenge (sql_injection_employee_portal)
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting || submittedRef.current) return;
    setSubmitting(true);
    setError('');
    try {
      await onSubmit(q.id, sqlInput, flagInput);
      submittedRef.current = true;
      setSubmitted(true);
    } catch (err) {
      setError(err.message || 'Failed to submit');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        {/* Challenge header */}
        <div className="bg-theme-secondary rounded-lg p-6 mb-6">
          <div className="flex items-start justify-between mb-3">
            <h2 className="text-xl font-bold text-theme-primary">{q.title}</h2>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-xs px-2 py-0.5 bg-purple-900/50 text-purple-300 rounded capitalize">{q.difficulty}</span>
              <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded">{q.points} pts</span>
              {submitted && (
                <span className="text-xs px-2 py-0.5 rounded font-semibold bg-blue-900/50 text-blue-300">
                  Submitted
                </span>
              )}
            </div>
          </div>
          <p className="text-theme-secondary whitespace-pre-wrap text-sm">{q.description}</p>
        </div>

        {/* Challenge website — embedded when possible, open-in-new-tab otherwise */}
        <div className="bg-theme-secondary rounded-lg overflow-hidden mb-6">
          <div className="px-4 py-2 border-b border-theme-border flex items-center justify-between">
            <span className="text-sm font-medium text-theme-primary">Challenge Website</span>
            <a
              href={CHALLENGE_IFRAME_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300"
            >
              Open in new tab ↗
            </a>
          </div>
          <iframe
            src={CHALLENGE_IFRAME_URL}
            title="Hands-on challenge"
            className="w-full h-[480px] border-0 bg-white"
            sandbox="allow-scripts allow-same-origin allow-forms"
          />
        </div>

        {/* Submission form — exactly two fields */}
        <form onSubmit={handleSubmit} className="bg-theme-secondary rounded-lg p-6">
          <h3 className="text-lg font-bold text-theme-primary mb-4">Submit Your Solution</h3>

          <div className="mb-4">
            <label className="block text-sm font-medium text-theme-primary mb-1">SQL Input Used</label>
            <textarea
              value={sqlInput}
              onChange={(e) => setSqlInput(e.target.value)}
              rows={5}
              disabled={submitted}
              readOnly={submitted}
              className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary text-sm font-mono resize-y disabled:opacity-60"
              placeholder="Paste the SQL input/payload you used..."
            />
            <p className="text-xs text-theme-muted mt-1">
              Stored as evidence of your approach. Not automatically verified.
            </p>
          </div>

          <div className="mb-4">
            <label className="block text-sm font-medium text-theme-primary mb-1">Flag</label>
            <input
              value={flagInput}
              onChange={(e) => setFlagInput(e.target.value)}
              disabled={submitted}
              readOnly={submitted}
              className="w-full px-4 py-3 bg-theme-input border border-theme-secondary rounded-lg text-theme-primary text-sm font-mono disabled:opacity-60"
              placeholder="FLAG{...}"
            />
          </div>

          {error && (
            <p className="text-sm text-red-300 bg-red-900/30 border border-red-500 rounded px-3 py-2 mb-3">{error}</p>
          )}
          {submitted && (
            <p className="text-sm text-theme-secondary bg-theme-tertiary border border-theme-border rounded px-3 py-2 mb-3">
              Challenge submitted. Your response has been recorded.
            </p>
          )}

          {!submitted && (
            <button
              type="submit"
              disabled={submitting}
              className="w-full px-4 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-semibold disabled:opacity-50"
            >
              {submitting ? 'Submitting...' : 'Submit Challenge'}
            </button>
          )}
        </form>
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
            language={language === 'python3' ? 'python' : language === 'cpp' ? 'cpp' : language === 'c' ? 'c' : 'java'}
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
        <TestResultsPanel runResults={runResults} />
      </div>
    </div>
  );
}


// ============================================================
// FULLSCREEN-EXIT OVERLAY
// A fixed, maximum z-index layer covering the whole viewport. It is
// intentionally NOT dismissable by Escape, a backdrop click or any other
// action — the only control is "Return to Fullscreen".
// ============================================================

function FullscreenEntryGate({ error, busy, showSkip, onEnter, onSkip }) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="Fullscreen Required"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90 backdrop-blur-sm px-4"
    >
      <div className="w-full max-w-md bg-theme-secondary border border-theme-border rounded-2xl p-8 text-center shadow-2xl">
        <h2 className="text-2xl font-bold text-theme-primary mb-3">Fullscreen Required</h2>
        <p className="text-theme-secondary text-sm mb-6">
          This assessment runs in fullscreen. Enter fullscreen to begin — the
          assessment is paused until then.
        </p>

        <button
          type="button"
          onClick={onEnter}
          disabled={busy}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold disabled:opacity-50"
        >
          {busy ? 'Entering…' : 'Enter Fullscreen'}
        </button>

        {error && (
          <p className="text-sm text-red-300 bg-red-900/30 border border-red-500/50 rounded px-3 py-2 mt-4">
            {error}
          </p>
        )}

        {/* Only offered after a request actually failed, so a browser that can
            enter fullscreen never shows an escape hatch. */}
        {showSkip && (
          <button
            type="button"
            onClick={onSkip}
            className="mt-4 text-xs text-theme-muted underline hover:text-theme-secondary"
          >
            Continue without fullscreen
          </button>
        )}
      </div>
    </div>
  );
}


function FullscreenExitOverlay({ seconds, error, busy, submitError, onReturn }) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label="Fullscreen Required"
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/90 backdrop-blur-sm px-4"
    >
      <div className="w-full max-w-md bg-theme-secondary border border-theme-border rounded-2xl p-8 text-center shadow-2xl">
        <h2 className="text-2xl font-bold text-theme-primary mb-3">Fullscreen Required</h2>
        <p className="text-theme-secondary text-sm mb-6">
          Please return to fullscreen mode to continue your assessment. The
          assessment is paused until fullscreen is restored.
        </p>

        <p className="text-theme-muted text-xs uppercase tracking-wider mb-1">Time remaining</p>
        <p
          data-testid="fullscreen-countdown"
          aria-live="polite"
          className="text-5xl font-mono font-bold text-red-400 mb-6"
        >
          {seconds}
        </p>

        <button
          type="button"
          onClick={onReturn}
          disabled={busy}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white px-6 py-3 rounded-lg font-semibold disabled:opacity-50"
        >
          {busy ? 'Returning…' : 'Return to Fullscreen'}
        </button>

        {error && (
          <p className="text-sm text-red-300 bg-red-900/30 border border-red-500/50 rounded px-3 py-2 mt-4">
            {error}
          </p>
        )}
        {submitError && (
          <p role="alert" className="text-sm text-red-300 bg-red-900/30 border border-red-500/50 rounded px-3 py-2 mt-4">
            Submission failed: {submitError} — your attempt has NOT been finalized.
            Return to fullscreen to retry.
          </p>
        )}
      </div>
    </div>
  );
}


export default AssessmentWorkspace;
