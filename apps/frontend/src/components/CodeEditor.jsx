import { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import PropTypes from 'prop-types';

/**
 * CodeEditor Component
 *
 * A controlled code editor powered by Monaco Editor.
 * Uses `value` (not `defaultValue`) so the editor updates when the active problem changes.
 * Parent should use `key={problemId}` on this component to force a fresh Monaco instance per problem.
 *
 * MONACO IS BUNDLED LOCALLY, NEVER LOADED FROM A CDN
 *   `@monaco-editor/react` defaults to fetching Monaco from jsDelivr at runtime,
 *   which is unreachable on the isolated deployment LAN — that made every coding
 *   editor hang forever on "Loading…" in production. `./monacoSetup` imports the
 *   `monaco-editor` npm package, wires its web workers and calls
 *   `loader.config({ monaco })`, so the loader always resolves the local build.
 *
 *   That setup module is large (~3.5 MB raw), so it is imported on demand — the
 *   first time an editor is actually about to render — instead of being part of
 *   the app's initial download. The import is memoized at module scope, so every
 *   editor instance (and every problem switch) reuses the one load, and no
 *   editor is ever mounted before the configuration has been applied (mounting
 *   early would let the loader fall back to its CDN default and hang).
 */
let monacoSetupPromise = null;

function loadMonacoSetup() {
  if (!monacoSetupPromise) {
    monacoSetupPromise = import('./monacoSetup');
  }
  return monacoSetupPromise;
}

/**
 * Monaco defaults. Callers may override any of them through `options` — the
 * WASM challenges, for example, pass `{ readOnly: submitted }` so a submitted
 * challenge cannot be edited. A `height` prop is accepted for symmetry with
 * the wrapper div; the editor always fills its container.
 */
const DEFAULT_EDITOR_OPTIONS = {
  minimap: { enabled: false },
  fontSize: 14,
  fontFamily: "'Fira Code', 'Courier New', monospace",
  lineNumbers: 'on',
  scrollBeyondLastLine: false,
  automaticLayout: true,
  tabSize: 4,
  insertSpaces: true,
  wordWrap: 'on',
};

function CodeEditor({
  language = 'python',
  theme = 'vs-dark',
  value = '',
  onChange,
  className = '',
  height = '100%',
  options = null,
}) {
  const [monacoReady, setMonacoReady] = useState(false);

  useEffect(() => {
    let active = true;
    loadMonacoSetup().then(() => {
      if (active) setMonacoReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  const handleChange = (val) => {
    if (onChange) {
      onChange(val);
    }
  };

  if (!monacoReady) {
    // Brief, same-origin chunk load. Deliberately no "Loading…" copy: a
    // permanent loading state was the production symptom, and the editor
    // appears as soon as the bundled setup resolves.
    return <div className={`code-editor-container h-full ${className}`} />;
  }

  return (
    <div className={`code-editor-container h-full ${className}`}>
      <Editor
        height={height}
        language={language}
        theme={theme}
        value={value}
        onChange={handleChange}
        options={{ ...DEFAULT_EDITOR_OPTIONS, ...(options || {}) }}
      />
    </div>
  );
}

CodeEditor.propTypes = {
  language: PropTypes.string,
  theme: PropTypes.string,
  value: PropTypes.string,
  onChange: PropTypes.func,
  className: PropTypes.string,
  height: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  options: PropTypes.object,
};

export default CodeEditor;
