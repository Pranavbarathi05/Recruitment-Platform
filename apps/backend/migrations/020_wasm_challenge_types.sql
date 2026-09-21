-- ============================================================
-- Migration 020: WASM Hands-On challenge types (DEV ONLY)
-- ============================================================
-- Extends the hands_on_questions table to support:
--   'sql_wasm'      — browser-local SQL via DuckDB-WASM
--   'pandas_wasm'   — browser-local Python/Pandas via Pyodide
--
-- Adds JSONB columns for the dataset, schema, starter code,
-- validation spec, and expected answer.
--
-- SAFE: Additive only. Drops and re-creates the CHECK constraint.
-- The existing sql_injection_employee_portal rows are preserved.
-- ============================================================

-- 1. Drop the old CHECK constraint and add the new one with WASM types
ALTER TABLE public.hands_on_questions
    DROP CONSTRAINT IF EXISTS hands_on_questions_challenge_type_check;

ALTER TABLE public.hands_on_questions
    ADD CONSTRAINT hands_on_questions_challenge_type_check
    CHECK (challenge_type IN (
        'sql_injection_employee_portal',
        'sql_wasm',
        'pandas_wasm'
    ));

-- 2. Add WASM-specific JSONB columns (nullable — existing rows unaffected)
ALTER TABLE public.hands_on_questions
    ADD COLUMN IF NOT EXISTS schema_sql TEXT;

ALTER TABLE public.hands_on_questions
    ADD COLUMN IF NOT EXISTS dataset_json JSONB;

ALTER TABLE public.hands_on_questions
    ADD COLUMN IF NOT EXISTS starter_code TEXT;

ALTER TABLE public.hands_on_questions
    ADD COLUMN IF NOT EXISTS validation_spec JSONB;

ALTER TABLE public.hands_on_questions
    ADD COLUMN IF NOT EXISTS expected_answer TEXT;
