import PropTypes from 'prop-types';
import { formatValue } from '../execution/harness';

/**
 * Test Results Panel
 *
 * Renders structured Run results in the space that already existed for test
 * output in the coding UI. Handles every status the client-side executor (and
 * the server fallback) can produce:
 *
 *   passed         -> green ✓ with output when available
 *   failed         -> red ✗ with input / expected / actual
 *   compile_error  -> red ✗ with compiler diagnostics
 *   runtime_error  -> red ✗ with the exception/stderr
 *   timeout        -> amber ⏱ Time Limit Exceeded
 *
 * Also shows program stdout and any top-level execution error.
 */
const STATUS_META = {
  passed: {
    icon: '✓',
    label: 'Passed',
    className: 'bg-green-900/30 text-green-300',
  },
  failed: {
    icon: '✗',
    label: 'Wrong Answer',
    className: 'bg-red-900/30 text-red-300',
  },
  compile_error: {
    icon: '✗',
    label: 'Compilation Error',
    className: 'bg-red-900/30 text-red-300',
  },
  runtime_error: {
    icon: '✗',
    label: 'Runtime Error',
    className: 'bg-red-900/30 text-red-300',
  },
  timeout: {
    icon: '⏱',
    label: 'Time Limit Exceeded',
    className: 'bg-yellow-900/30 text-yellow-300',
  },
};

const DEFAULT_META = { icon: '✗', label: 'Failed', className: 'bg-red-900/30 text-red-300' };

function getStatusMeta(status) {
  return STATUS_META[status] || DEFAULT_META;
}

function ResultRow({ result, index }) {
  const meta = getStatusMeta(result.status);
  const isFailure = !result.passed;

  return (
    <div className={`text-sm p-2 rounded ${meta.className}`}>
      <div className="flex items-center gap-2">
        <span className="font-mono">
          {meta.icon} Sample {index + 1}
        </span>
        <span className="text-xs font-medium">{meta.label}</span>
        {typeof result.execution_time_ms === 'number' && result.execution_time_ms > 0 && (
          <span className="text-xs opacity-70 ml-auto font-mono">
            {result.execution_time_ms}ms
          </span>
        )}
      </div>

      {/* Wrong answer: input / expected / actual */}
      {isFailure && result.status === 'failed' && (
        <div className="mt-1 text-xs space-y-0.5">
          {result.input !== null && result.input !== undefined && (
            <div>
              <span className="text-theme-muted">Input: </span>
              <code className="text-theme-secondary">{formatValue(result.input)}</code>
            </div>
          )}
          <div>
            <span className="text-theme-muted">Expected: </span>
            <code className="text-green-200">{formatValue(result.expected_output)}</code>
          </div>
          <div>
            <span className="text-theme-muted">Got: </span>
            <code className="text-red-200">{formatValue(result.actual_output) || '(empty)'}</code>
          </div>
        </div>
      )}

      {/* Compile error diagnostics */}
      {isFailure && result.status === 'compile_error' && result.stderr && (
        <pre className="mt-1 text-xs whitespace-pre-wrap font-mono text-red-200">
          {result.stderr}
        </pre>
      )}

      {/* Runtime error / stderr */}
      {isFailure && result.status === 'runtime_error' && result.stderr && (
        <pre className="mt-1 text-xs whitespace-pre-wrap font-mono text-red-200">
          {result.stderr}
        </pre>
      )}

      {/* Timeout status */}
      {isFailure && result.status === 'timeout' && (
        <div className="mt-1 text-xs text-yellow-200">
          Execution exceeded the time limit and was stopped.
        </div>
      )}

      {/* Accepted: show produced output when available */}
      {result.passed && result.actual_output !== null && result.actual_output !== undefined && (
        <pre className="mt-1 text-xs whitespace-pre-wrap font-mono text-green-200">
          Output: {formatValue(result.actual_output)}
        </pre>
      )}
    </div>
  );
}

ResultRow.propTypes = {
  result: PropTypes.object.isRequired,
  index: PropTypes.number.isRequired,
};

function TestResultsPanel({ runResults }) {
  if (!runResults) return null;

  const results = runResults.results || [];

  return (
    <div className="shrink-0 border-t border-theme-border px-4 py-3 bg-theme-secondary max-h-64 overflow-y-auto">
      <h4 className="font-semibold text-theme-primary mb-2 text-sm">
        Test Results{' '}
        {runResults.all_passed ? (
          <span className="text-green-400">— All Passed ✓</span>
        ) : null}
      </h4>

      {/* Catastrophic execution failure (e.g. runtime could not initialize) */}
      {runResults.error && (
        <div className="text-red-400 text-sm mb-2">{runResults.error}</div>
      )}

      {/* Compilation diagnostics for the whole program */}
      {runResults.compilation_error && (
        <div className="bg-red-900/30 border border-red-700 rounded p-2 mb-2">
          <div className="text-red-300 text-xs font-semibold mb-1">Compilation Error</div>
          <pre className="text-red-200 text-xs whitespace-pre-wrap font-mono">
            {runResults.compilation_error}
          </pre>
        </div>
      )}

      {/* Program stdout captured during the run */}
      {runResults.stdout && (
        <div className="bg-theme-primary rounded p-2 mb-2">
          <div className="text-theme-muted text-xs font-semibold mb-1">Program Output</div>
          <pre className="text-theme-secondary text-xs whitespace-pre-wrap font-mono">
            {runResults.stdout}
          </pre>
        </div>
      )}

      {runResults.message && (
        <div className="text-yellow-300 text-sm mb-2">{runResults.message}</div>
      )}

      {results.length > 0 ? (
        <div className="space-y-2">
          {results.map((r, idx) => (
            <ResultRow key={r.id || idx} result={r} index={idx} />
          ))}
        </div>
      ) : (
        !runResults.error && (
          <div className="text-theme-muted text-sm">No results to display.</div>
        )
      )}
    </div>
  );
}

TestResultsPanel.propTypes = {
  runResults: PropTypes.object,
};

export default TestResultsPanel;