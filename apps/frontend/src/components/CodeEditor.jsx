import Editor from '@monaco-editor/react';
import PropTypes from 'prop-types';

/**
 * CodeEditor Component
 * 
 * A functional code editor powered by Monaco Editor for candidates to write solutions.
 * Supports multiple programming languages with syntax highlighting.
 * 
 * @component
 * @param {string} language - Programming language for the editor (default: 'python')
 * @param {string} theme - Editor theme (default: 'vs-dark')
 * @param {string} defaultValue - Default code in the editor
 * @param {Function} onChange - Callback when code changes
 * @param {string} className - Additional CSS classes
 * @returns {JSX.Element} The CodeEditor component
 */
function CodeEditor({
  language = 'python',
  theme = 'vs-dark',
  defaultValue = '# Write your Python code here\n\n',
  onChange,
  className = ''
}) {
  const handleChange = (value) => {
    if (onChange) {
      onChange(value);
    }
  };

  return (
    <div className={`code-editor-container ${className}`}>
      <Editor
        height="500px"
        language={language}
        theme={theme}
        defaultValue={defaultValue}
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
  defaultValue: PropTypes.string,
  onChange: PropTypes.func,
  className: PropTypes.string,
};

export default CodeEditor;
