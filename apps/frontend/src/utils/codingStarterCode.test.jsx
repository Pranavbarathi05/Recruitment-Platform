import { describe, it, expect } from 'vitest';
import { generatePythonStarterCode } from './codingStarterCode';

describe('generatePythonStarterCode', () => {
  it('produces a free function starter from function_name and signature parameter names', () => {
    const starter = generatePythonStarterCode(
      'solve',
      null,
      'def solve(nums: list[int], target: int) -> list[int]:',
    );
    expect(starter).toContain('def solve(nums, target):');
    expect(starter).not.toContain('self');
    expect(starter).not.toContain('class Solution');
  });

  it('produces a Solution class starter when class_name is provided', () => {
    const starter = generatePythonStarterCode(
      'twoSum',
      'Solution',
      'def twoSum(self, nums: List[int], target: int) -> List[int]:',
    );
    expect(starter).toContain('class Solution:');
    expect(starter).toContain('def twoSum(self, nums, target):');
  });

  it('falls back to generic param names when signature is blank', () => {
    const starter = generatePythonStarterCode('solve', null, null);
    expect(starter).toContain('def solve(arg1, arg2):');
  });

  it('throws when function_name is missing', () => {
    expect(() => generatePythonStarterCode('', null, null)).toThrow(
      /function_name is required/,
    );
  });

  it('throws when class_name is blank', () => {
    expect(() => generatePythonStarterCode('solve', '   ', null)).toThrow(
      /class_name must not be blank/,
    );
  });

  it('handles a signature with no parameter list by falling back to generic names', () => {
    const starter = generatePythonStarterCode('solve', null, 'def solve():');
    expect(starter).toContain('def solve(arg1, arg2):');
  });
});
