import { useState, useEffect, useRef, useCallback } from 'react';
import CodeEditor from './CodeEditor';
import { SqlWasmRunner } from '../execution/sqlWasmRunner';
import { validateSql } from '../execution/validators';

/**
 * SQL WASM Challenge Component
 *
 * Renders a browser-local SQL challenge powered by DuckDB-WASM.
 * Candidate SQL is NEVER sent to the backend — execution is 100% client-side.
 *
 * Props:
 *   problem - Challenge object with schema_sql, dataset_json, starter_code, validation_spec
 *   onSubmit - Function called with { questionId, submittedCode, clientScore }
 *   submitted - Boolean, whether this challenge has already been submitted
 */
const SqlWasmChallenge = ({ problem, onSubmit, submitted }) => {
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
        const r = new SqlWasmRunner();
        await r.initialize({
          schema: problem.schema_sql,
          dataset: problem.dataset_json,
        });
        if (!cancelled) {
          runnerRef.current = r;
          setRunner(r);
          setSourceCode(problem.starter_code || '');
        }
      } catch (err) {
        if (!cancelled) {
          setError(`Failed to initialize SQL environment: ${err.message}`);
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
        const v = validateSql(res, problem.validation_spec);
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
      const v = validateSql(result, problem.validation_spec);
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
      <div className="flex flex-col items-center justify-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-t-4 border-b-4 border-blue-500 mb-4" />
        <p className="text-blue-300 text-sm">Preparing SQL environment...</p>
        <p className="text-theme-muted text-xs mt-1">Loading DuckDB-WASM runtime</p>
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
          language="sql"
          value={sourceCode}
          onChange={(val) => setSourceCode(val || '')}
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
          {error && result?.error && (
            <div className="px-4 py-3 text-red-300 text-sm font-mono">{result.error}</div>
          )}

          {result && !result.error && result.rows.length > 0 && (
            <div className="overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-theme-secondary">
                    {result.columns.map((col, i) => (
                      <th key={i} className="px-3 py-2 text-left text-theme-muted font-medium border-b border-theme-border">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row, i) => (
                    <tr key={i} className="border-b border-theme-border hover:bg-theme-secondary/50">
                      {row.map((val, j) => (
                        <td key={j} className="px-3 py-1.5 text-theme-primary font-mono text-xs">
                          {val === null ? <span className="text-theme-muted italic">NULL</span> : String(val)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {result && !result.error && result.rows.length === 0 && (
            <div className="px-4 py-3 text-theme-muted text-sm">Query returned no results.</div>
          )}

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

export default SqlWasmChallenge;
