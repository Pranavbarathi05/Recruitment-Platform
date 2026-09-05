/**
 * Client-side execution support matrix.
 *
 * The Run button executes code in the candidate's browser (Web Worker + WASM)
 * for languages listed in CLIENT_RUNNABLE_LANGUAGES. For languages without a
 * browser runtime the existing server-side run endpoint is used instead, so the
 * platform keeps working — see docs/limitations in README.
 *
 * Run results are candidate feedback only. They are NEVER authoritative:
 * scoring happens exclusively server-side on Submit.
 */
export const CLIENT_RUNNABLE_LANGUAGES = ['python3'];

export const CLIENT_EXECUTION_HINTS = {
  python3: 'Python 3 runs locally in your browser via Pyodide (WASM).',
};

export function isClientRunnable(language) {
  return CLIENT_RUNNABLE_LANGUAGES.includes(language);
}