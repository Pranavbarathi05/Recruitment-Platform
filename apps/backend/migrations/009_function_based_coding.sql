-- ============================================================
-- Migration 009: Function-Based Coding Problems
-- ============================================================
-- Replaces stdin/stdout model with LeetCode-style function model.
--
-- Changes:
--   1. coding_problems: add function_name, class_name, function_signature
--   2. coding_test_cases: add arguments (JSONB), rename columns
--   3. Preserve backward compatibility (old columns remain)
--
-- SAFE: Additive only. Does not delete or modify existing data.
-- Old test cases can be migrated manually or left as-is.
-- ============================================================

-- 1. Add function metadata to coding_problems
ALTER TABLE public.coding_problems
    ADD COLUMN IF NOT EXISTS function_name TEXT NOT NULL DEFAULT 'solve';

ALTER TABLE public.coding_problems
    ADD COLUMN IF NOT EXISTS class_name TEXT DEFAULT NULL;

ALTER TABLE public.coding_problems
    ADD COLUMN IF NOT EXISTS function_signature TEXT DEFAULT NULL;

-- 2. Add arguments column to coding_test_cases (JSONB array of arguments)
--    Each element is one argument to the function.
--    Example: [[2,7,11,15], 9] for twoSum(nums, target)
ALTER TABLE public.coding_test_cases
    ADD COLUMN IF NOT EXISTS arguments JSONB DEFAULT NULL;
