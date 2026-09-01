-- ============================================================
-- Migration 007: Remove coding_problems.domain_id
-- ============================================================
-- Coding problems are GLOBAL and domain-independent.
-- A coding problem can be given to any candidate regardless of
-- their selected assessment domains.
--
-- This migration:
--   1. Drops the FK constraint on coding_problems.domain_id
--   2. Drops indexes that reference domain_id
--   3. Drops the domain_id column
--
-- SAFE: Only removes the domain relationship from coding_problems.
-- Does NOT touch:
--   - assessment_attempts.selected_coding_problem_ids
--   - assessment_attempts.domain_ids (MCQ domain selection)
--   - mcq_questions.domain_id (MCQ domain filtering)
--   - coding_problems data (rows remain, column is removed)
--   - coding_test_cases, coding_submissions, coding_drafts
-- ============================================================

-- 1. Drop indexes that reference domain_id on coding_problems
DROP INDEX IF EXISTS public.idx_coding_problems_domain_active;
DROP INDEX IF EXISTS public.idx_coding_problems_domain_id;

-- 2. Drop the foreign key constraint
--    PostgreSQL auto-generates inline FK constraint names as:
--    <table>_<column>_fkey
ALTER TABLE public.coding_problems
    DROP CONSTRAINT IF EXISTS coding_problems_domain_id_fkey;

-- 3. Drop the column
ALTER TABLE public.coding_problems
    DROP COLUMN IF EXISTS domain_id;

-- ============================================================
-- Verification query (optional, for manual run confirmation):
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'coding_problems' AND column_name = 'domain_id';
-- Should return 0 rows after this migration.
-- ============================================================
