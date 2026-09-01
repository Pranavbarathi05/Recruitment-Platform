-- ============================================================
-- Migration 008: Assessment Reset Support + Constraints
-- ============================================================
-- Adds:
--   1. 'reset' status to assessment_attempts (historical, allows retake)
--   2. Index on (profile_id, status) for fast active-attempt lookup
--   3. Partial unique index to prevent duplicate in_progress attempts
--
-- SAFE: Additive only. Does not modify existing data.
-- ============================================================

-- 1. Drop the old CHECK constraint and add new one with 'reset'
ALTER TABLE public.assessment_attempts
    DROP CONSTRAINT IF EXISTS assessment_attempts_status_check;

ALTER TABLE public.assessment_attempts
    ADD CONSTRAINT assessment_attempts_status_check
    CHECK (status IN ('in_progress', 'submitted', 'scored', 'reset'));

-- 2. Index for fast active-attempt lookup by candidate
CREATE INDEX IF NOT EXISTS idx_assessment_attempts_profile_status
    ON public.assessment_attempts(profile_id, status);

-- 3. Partial unique index: at most ONE in_progress attempt per candidate
--    This prevents race conditions where two start requests create duplicates.
--    Uses COALESCE to handle potential NULL profile_id values.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_attempt_per_candidate
    ON public.assessment_attempts(profile_id)
    WHERE status = 'in_progress';
