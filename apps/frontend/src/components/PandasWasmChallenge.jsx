import { useState, useEffect, useRef, useCallback } from 'react';
import CodeEditor from './CodeEditor';
import { PandasWasmRunner } from '../execution/pandasWasmRunner';
import { validatePandas } from '../execution/validators';

/**
 * Pandas WASM Challenge Component
 *
 * Renders a browser-local Python/Pandas challenge powered by Pyodide.
 * Candidate Python is NEVER sent to the backend — execution is 100% client-side.
 *
 * Props:
 *   problem - Challenge object with dataset_json, starter_code, validation_spec
 *   onSubmit - Function called with { questionId, submittedCode, clientScore }
 *   submitted - Boolean, whether this challenge has already been submitted
 *   initialCode - Optional draft restored from the parent (per-question state
 *                 so switching Hands-On questions preserves the editor contents)
 *   onDraftChange - Called with the current editor contents on every edit
 */
const PandasWasmChallenge = ({ problem, onSubmit, submitted, initialCode, onDraftChange }) => {
  const [sourceCode, setSourceCode] = useState('');
  const [runner, setRunner] = useState(null);
  const [initializing, setInitializing] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [validation, setValidation] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const runnerRef = useRef(null);

  // Initialize runner
  useEffect(() => {
    let cancelled = false;

    const initRunner = async () => {
      try {
        setInitializing(true);
        const r = new PandasWasmRunner();
        await r.initialize({
          dataset: problem.dataset_json,
        });
        if (!cancelled) {
          runnerRef.current = r;
          setRunner(r);
          // Restore this question's draft when there is one (switched away
          // and back), otherwise start from the admin-provided starter.
          setSourceCode(initialCode ?? problem.starter_code ?? '');
        }
      } catch (err) {
        if (!cancelled) {
          setError(`Failed to initialize Python/Pandas environment: ${err.message}`);
        }
      } finally {
        if (!cancelled) setInitializing(false);
      }
    };

    initRunner();

    return () => {
      cancelled = true;
      if (runnerRef.current) {
        runnerRef.current.dispose().catch(() => {});
        runnerRef.current = null;
      }
    };
  }, [problem.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = useCallback(async () => {
    if (!runner || running || submitted) return;
    setRunning(true);
    setResult(null);
    setValidation(null);
    setError(null);

    try {
      const res = await runner.execute(sourceCode);
      setResult(res);

      if (problem.validation_spec) {
        const v = validatePandas(res, problem.validation_spec);
        setValidation(v);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }, [runner, sourceCode, running, submitted, problem]);

  const handleSubmit = useCallback(async () => {
    if (!result || submitting || submitted) return;
    setSubmitting(true);
    try {
      // The validator's verdict (binary) — never a point value. The backend
      // awards the challenge's points when this passes. WASM challenges have
      // no flag: nothing flag-shaped is sent.
      const v = validatePandas(result, problem.validation_spec);
      await onSubmit({
        questionId: problem.id,
        submittedCode: sourceCode,
        validationPassed: v.passed,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }, [result, sourceCode, submitting, submitted, onSubmit, problem]);

  if (initializing) {
    return (
      <div className="h-full flex flex-col items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-t-4 border-b-4 border-blue-500 mb-4" />
        <p className="text-blue-300 text-sm">Preparing Python/Pandas environment...</p>
        <p className="text-theme-muted text-xs mt-1">Loading Pyodide runtime (this may take a moment)</p>
      </div>
    );
  }

  if (error && !result) {
    return (
      <div className="bg-red-900/20 border border-red-500/30 rounded-lg p-4 text-red-300 text-sm">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Editor */}
      <div className="flex-1 min-h-0">
        <CodeEditor
          language="python"
          value={sourceCode}
          onChange={(val) => {
            const next = val || '';
            setSourceCode(next);
            onDraftChange?.(next);
          }}
          height="100%"
          options={{ readOnly: submitted }}
        />
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-3 px-4 py-2 bg-theme-secondary border-t border-theme-border">
        <button
          onClick={handleRun}
          disabled={running || submitted || initializing}
          className={`px-5 py-1.5 rounded-lg font-semibold text-sm transition-colors ${
            running || submitted || initializing
              ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-700 text-white'
          }`}
        >
          {running ? '⏳ Running...' : '▶ Run'}
        </button>

        <button
          onClick={handleSubmit}
          disabled={!result || submitting || submitted}
          className={`px-5 py-1.5 rounded-lg font-semibold text-sm transition-colors ${
            !result || submitting || submitted
              ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
              : 'bg-green-600 hover:bg-green-700 text-white'
          }`}
        >
          {submitted ? '✓ Submitted' : submitting ? '⏳ Submitting...' : '🚀 Submit'}
        </button>

        {validation && (
          <span className={`text-sm font-semibold ${validation.passed ? 'text-green-400' : 'text-red-400'}`}>
            {validation.passed ? '✓ Passed' : '✗ Failed'}
          </span>
        )}

        {result && (
          <span className="text-xs text-theme-muted ml-auto">
            {result.duration}ms
          </span>
        )}
      </div>

      {/* Results */}
      {(result || error) && (
        <div className="border-t border-theme-border bg-theme-primary max-h-60 overflow-auto">
          {/* Error */}
          {result?.error && (
            <div className="px-4 py-3 bg-red-900/20 text-red-300 text-sm font-mono whitespace-pre-wrap">{result.error}</div>
          )}

          {/* Dataframe result */}
          {result?.dataframe && (
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-theme-secondary">
                    {result.dataframe.columns.map((col, i) => (
                      <th key={i} className="px-3 py-2 text-left text-theme-muted font-medium border-b border-theme-border">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.dataframe.rows.map((row, i) => (
                    <tr key={i} className="border-b border-theme-border hover:bg-theme-secondary/50">
                      {row.map((val, j) => (
                        <td key={j} className="px-3 py-1.5 text-theme-primary font-mono text-xs">
                          {val === null ? <span className="text-theme-muted italic">None</span> : String(val)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Scalar result */}
          {result?.result && !result?.dataframe && (
            <div className="px-4 py-3 text-theme-primary font-mono text-sm">
              {result.result}
            </div>
          )}

          {/* Stdout */}
          {result?.stdout && (
            <div className="px-4 py-2 border-t border-theme-border">
              <span className="text-xs text-theme-muted">stdout:</span>
              <pre className="text-sm text-theme-primary font-mono whitespace-pre-wrap mt-1">{result.stdout}</pre>
            </div>
          )}

          {/* Stderr (non-error) */}
          {result?.stderr && !result?.error && (
            <div className="px-4 py-2 border-t border-theme-border">
              <span className="text-xs text-theme-muted">stderr:</span>
              <pre className="text-sm text-yellow-300 font-mono whitespace-pre-wrap mt-1">{result.stderr}</pre>
            </div>
          )}

          {/* Validation details */}
          {validation && !validation.passed && (
            <div className="px-4 py-2 bg-red-900/20 text-red-300 text-sm">
              {validation.details}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default PandasWasmChallenge;
