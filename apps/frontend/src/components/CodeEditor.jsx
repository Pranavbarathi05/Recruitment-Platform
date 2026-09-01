import Editor from '@monaco-editor/react';
import PropTypes from 'prop-types';

/**
 * CodeEditor Component
 *
 * A controlled code editor powered by Monaco Editor.
 * Uses `value` (not `defaultValue`) so the editor updates when the active problem changes.
 * Parent should use `key={problemId}` on this component to force a fresh Monaco instance per problem.
 */
function CodeEditor({
  language = 'python',
  theme = 'vs-dark',
  value = '',
  onChange,
  className = '',
}) {
  const handleChange = (val) => {
    if (onChange) {
      onChange(val);
    }
  };

  return (
    <div className={`code-editor-container h-full ${className}`}>
      <Editor
        height="100%"
        language={language}
        theme={theme}
        value={value}
        onChange={handleChange}
        options={{
          minimap: { enabled: false },
          fontSize: 14,
          fontFamily: "'Fira Code', 'Courier New', monospace",
          lineNumbers: 'on',
          scrollBeyondLastLine: false,
          automaticLayout: true,
          tabSize: 4,
          insertSpaces: true,
          wordWrap: 'on',
        }}
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
};

export default CodeEditor;
