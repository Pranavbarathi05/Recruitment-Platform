import { describe, it, expect } from 'vitest';
import { countWords, limitToWords } from './wordLimit';

describe('countWords', () => {
  it('counts 0 for empty string', () => {
    expect(countWords('')).toBe(0);
  });

  it('counts 0 for whitespace-only text', () => {
    expect(countWords('   \n\t  ')).toBe(0);
  });

  it('counts a single word', () => {
    expect(countWords('hello')).toBe(1);
  });

  it('collapses runs of whitespace (spaces/newlines/tabs)', () => {
    expect(countWords('hello   world\nthis')).toBe(3);
    expect(countWords('a\tb\nc  d')).toBe(4);
  });

  it('does not count leading/trailing whitespace', () => {
    expect(countWords('  one two  ')).toBe(2);
  });
});

describe('limitToWords', () => {
  it('returns text unchanged when limit is null/undefined/0', () => {
    const text = 'one two three four five';
    expect(limitToWords(text, null)).toBe(text);
    expect(limitToWords(text, undefined)).toBe(text);
    expect(limitToWords(text, 0)).toBe(text);
  });

  it('returns text unchanged when under the limit', () => {
    expect(limitToWords('one two', 5)).toBe('one two');
  });

  it('returns text unchanged when exactly at the limit', () => {
    expect(limitToWords('one two three', 3)).toBe('one two three');
  });

  it('constrains over-limit typed text to the first N words', () => {
    expect(limitToWords('one two three four', 3)).toBe('one two three');
  });

  it('constrains over-limit pasted text to the first N words', () => {
    const pasted = Array.from({ length: 500 }, (_, i) => `w${i}`).join(' ');
    const out = limitToWords(pasted, 100);
    expect(countWords(out)).toBe(100);
    expect(out).toBe(Array.from({ length: 100 }, (_, i) => `w${i}`).join(' '));
  });

  it('handles newlines and tabs as separators', () => {
    expect(limitToWords('one two\nthree\tfour five', 3)).toBe('one two\nthree');
  });

  it('preserves internal whitespace between kept words', () => {
    expect(limitToWords('one   two\nthree four', 3)).toBe('one   two\nthree');
  });

  it('never returns more words than the limit', () => {
    expect(countWords(limitToWords('a b c d e f g', 4))).toBe(4);
  });

  it('handles empty text', () => {
    expect(limitToWords('', 5)).toBe('');
  });
});
