/**
 * Shared helper for generating candidate-visible Python starter code from
 * function-based coding problem metadata.
 *
 * The generated starter must match the configured:
 *  - function_name
 *  - class_name (if any)
 *  - function_signature (kept only for parameter names; annotations removed)
 *
 * The candidate sees ONLY the function/class boilerplate; the harness and test
 * invocation are generated server-side and in the Python runner worker.
 *
 * NOTE: This intentionally does NOT attempt to edit C++ or Java starter code.
 * This task is scoped to the Python function-based flow.
 *
 * The extraction rules mirror services/harness.py `_parse_python_param_names` /
 * `_generate_python_starter_code` so the admin default and the candidate fallback
 * produce identical output for the same metadata.
 */

/**
 * @param {string} functionName
 * @param {string|null} className
 * @param {string|null} functionSignature
 * @returns {string}
 */
export function generatePythonStarterCode(functionName, className, functionSignature) {
  if (!functionName) {
    throw new Error('function_name is required for Python starter code');
  }

  const rawNames = extractParamNames(functionSignature);
  const params = rawNames.filter((n) => n !== 'self' && n !== 'cls');
  const bodyParams = params.length ? params : ['arg1', 'arg2'];

  if (className) {
    if (!className.trim()) {
      throw new Error('class_name must not be blank when provided');
    }
    return (
      `class ${className.trim()}:\n` +
      `    def ${functionName}(self, ${bodyParams.join(', ')}):\n` +
      `        # Write your solution here\n` +
      `        pass\n`
    );
  }

  return (
    `def ${functionName}(${bodyParams.join(', ')}):\n` +
    `    # Write your solution here\n` +
    `    pass\n`
  );
}

/**
 * Extract parameter names from a Python function signature string, preserving
 * declaration order and discarding type annotations, default values, and the
 * special self/cls tokens. When the signature has no useful parameter list this
 * returns the empty list (callers fall back to generic placeholders).
 */
function extractParamNames(signature) {
  if (!signature || !signature.trim()) {
    return [];
  }

  const openParen = signature.indexOf('(');
  const closeParen = signature.lastIndexOf(')');
  if (openParen === -1 || closeParen === -1 || closeParen < openParen) {
    return [];
  }

  const paramsStr = signature.slice(openParen + 1, closeParen).trim();
  if (!paramsStr) {
    return [];
  }

  const names = [];
  for (const rawPart of paramsStr.split(',')) {
    let part = rawPart.trim();
    if (!part) {
      continue;
    }

    // Drop return annotation, then default value.
    const arrowIdx = part.indexOf('->');
    if (arrowIdx !== -1) {
      part = part.slice(0, arrowIdx).trim();
    }
    const eqIdx = part.indexOf('=');
    if (eqIdx !== -1) {
      part = part.slice(0, eqIdx).trim();
    }

    // `name: Type` -> name.
    const colonIdx = part.indexOf(':');
    if (colonIdx !== -1) {
      const candidate = part.slice(0, colonIdx).trim();
      if (candidate && isIdentifier(candidate) && candidate !== 'self' && candidate !== 'cls') {
        names.push(candidate);
        continue;
      }
      // The text before the colon was not a clean name; recover from the rest.
      part = part.slice(colonIdx + 1).trim();
    }

    // Fallback: keep the last whitespace-separated plain identifier that is
    // not self/cls.
    const tokens = part.split(/\s+/);
    for (let i = tokens.length - 1; i >= 0; i--) {
      const tok = tokens[i];
      if (tok === 'self' || tok === 'cls') {
        continue;
      }
      if (isIdentifier(tok)) {
        names.push(tok);
        break;
      }
    }
  }

  return names;
}

/** Match Python identifier semantics closely enough for parameter names. */
function isIdentifier(value) {
  return /^[A-Za-z_][A-Za-z0-9_]*$/.test(value);
}
