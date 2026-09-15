/**
 * Shared word-count / word-limit helpers for descriptive answers.
 *
 * Canonical rule (mirrors the backend `count_words` in
 * routers/assessment.py): trim, split on runs of whitespace
 * (spaces/newlines/tabs), ignore empty tokens.
 *   "hello   world\nthis" -> 3 words
 *
 * Used for the displayed counter, typed input, pasted input and the value
 * actually stored — one implementation everywhere.
 */

/**
 * Count words on the whitespace-run rule. Empty/whitespace-only -> 0.
 * @param {string} text
 * @returns {number}
 */
export function countWords(text) {
  if (!text) return 0;
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  return tokens.length;
}

/**
 * Constrain `text` to at most `limit` words on the same whitespace rule.
 * Words are preserved exactly (whitespace runs between kept words are kept
 * as-is); everything from the (limit+1)-th word on is dropped.
 *
 * Returns `text` unchanged when `limit` is falsy (NULL/unlimited) or the
 * text is already within the limit, so no-work cases never rewrite input.
 *
 * @param {string} text
 * @param {number|null|undefined} limit
 * @returns {string}
 */
export function limitToWords(text, limit) {
  if (!limit || limit <= 0 || !text) return text || '';
  const tokens = text.trim().split(/\s+/).filter(Boolean);
  if (tokens.length <= limit) return text;

  // Walk the string keeping the first `limit` word tokens plus the
  // whitespace that follows each, then trim the dangling tail whitespace.
  const re = /(\s*)(\S+)/g;
  let kept = 0;
  let end = 0;
  while (re.exec(text) !== null) {
    kept += 1;
    end = re.lastIndex;
    if (kept === limit) break;
  }
  return text.slice(0, end).trimEnd();
}
