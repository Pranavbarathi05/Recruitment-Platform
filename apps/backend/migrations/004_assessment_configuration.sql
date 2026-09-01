-- ============================================================
-- Migration 004: Assessment Configuration & Timer Enforcement
-- ============================================================
-- This migration adds:
--   1. assessment_config table (strongly typed columns)
--   2. expires_at column to assessment_attempts
--   3. Partial unique index to prevent duplicate active attempts
--   4. Partial unique index to enforce single active config
--   5. CHECK constraint: total_questions must be even when max_domains=2
--   6. RLS and GRANTs for the config table
--   7. Idempotent default MCQ assessment configuration seed
--
-- Distribution rule (hardcoded, not configurable):
--   - 1 selected domain → 100% of questions from that domain
--   - 2 selected domains → exactly 50/50 split
--   - If total_questions is odd and max_domains=2 → reject config
--   - Max selectable domains is always ≤ 2
--
-- RERUN-SAFE: All CREATE statements use IF NOT EXISTS.
-- The seed is idempotent (DO block checks before inserting).
-- SAFE: Additive only. Does not drop tables or delete data.
-- ============================================================

-- ============================================================
-- 0. CHECK for existing duplicate in_progress attempts
-- ============================================================
-- If any candidate already has multiple in_progress attempts,
-- the partial unique index creation would fail ambiguously.
-- We detect this first and raise a clear error.

DO $$
DECLARE
    dup_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO dup_count FROM (
        SELECT profile_id
        FROM public.assessment_attempts
        WHERE status = 'in_progress'
        GROUP BY profile_id
        HAVING COUNT(*) > 1
    ) dups;

    IF dup_count > 0 THEN
        RAISE EXCEPTION
            'MIGRATION BLOCKED: % candidate(s) have multiple in_progress attempts. '
            'Resolve these before applying the unique index. '
            'Query: SELECT profile_id, COUNT(*) FROM public.assessment_attempts '
            'WHERE status = ''in_progress'' GROUP BY profile_id HAVING COUNT(*) > 1;',
            dup_count;
    END IF;
END $$;

-- ============================================================
-- 1. ASSESSMENT CONFIGURATION TABLE
-- ============================================================
-- Strongly typed configuration for assessment parameters.
-- Designed to later support MCQ-only, coding-only, or combined
-- assessments by adding an `assessment_type` column if needed.
--
-- Constraints enforced at the database level:
--   total_questions > 0
--   duration_minutes > 0
--   max_domains BETWEEN 1 AND 2
--   total_questions must be even when max_domains = 2
--     (enforced by: max_domains = 1 OR total_questions % 2 = 0)

CREATE TABLE IF NOT EXISTS public.assessment_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    total_questions INTEGER NOT NULL CHECK (total_questions > 0),
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    max_domains INTEGER NOT NULL CHECK (max_domains >= 1 AND max_domains <= 2),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- When max_domains = 2, total_questions must be even for a 50/50 split.
    -- When max_domains = 1, any positive total is valid.
    CHECK (max_domains = 1 OR total_questions % 2 = 0)
);

-- updated_at trigger
DROP TRIGGER IF EXISTS update_assessment_config_updated_at ON public.assessment_config;
CREATE TRIGGER update_assessment_config_updated_at
    BEFORE UPDATE ON public.assessment_config
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 2. PARTIAL UNIQUE INDEX: ENFORCE SINGLE ACTIVE CONFIG
-- ============================================================
-- The assessment engine expects exactly ONE active configuration.
-- This partial unique index ensures at most one row can have
-- is_active = true.

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_config
    ON public.assessment_config (is_active)
    WHERE is_active = true;

-- ============================================================
-- 3. SEED DEFAULT MCQ ASSESSMENT CONFIGURATION (IDEMPOTENT)
-- ============================================================
-- Only inserts if no row named 'MCQ Assessment' exists.
-- Safe to rerun — will not create duplicates.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.assessment_config
        WHERE name = 'MCQ Assessment'
    ) THEN
        INSERT INTO public.assessment_config (
            name, total_questions, duration_minutes, max_domains, is_active
        ) VALUES (
            'MCQ Assessment',
            20,    -- total questions (even → valid for 2-domain 50/50)
            20,    -- duration in minutes
            2,     -- max domains (cannot exceed 2)
            true   -- active
        );
    END IF;
END $$;

-- ============================================================
-- 4. ADD expires_at TO ASSESSMENT ATTEMPTS
-- ============================================================
-- Computed at attempt creation: started_at + configured duration.
-- Used by the backend to enforce server-side timer expiration.

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;

-- Backfill existing in_progress attempts (if any exist)
UPDATE public.assessment_attempts
SET expires_at = started_at + (duration_minutes || ' minutes')::INTERVAL
WHERE expires_at IS NULL AND status = 'in_progress';

-- ============================================================
-- 5. PARTIAL UNIQUE INDEX: PREVENT DUPLICATE ACTIVE ATTEMPTS
-- ============================================================
-- Each candidate may have at most ONE in_progress attempt at a time.
-- This is a database-level safety net that complements the
-- application-level check.
-- The check in step 0 ensures no duplicates exist before creation.

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_attempt_per_candidate
    ON public.assessment_attempts(profile_id)
    WHERE status = 'in_progress';

-- ============================================================
-- 6. INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_assessment_config_active
    ON public.assessment_config(is_active);

CREATE INDEX IF NOT EXISTS idx_attempts_expires_at
    ON public.assessment_attempts(expires_at);

-- ============================================================
-- 7. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE public.assessment_config ENABLE ROW LEVEL SECURITY;

-- No candidate-facing policies.
-- Config is read/written exclusively via FastAPI using service_role.
-- Candidates have no GRANT on this table.

-- ============================================================
-- 8. GRANTS
-- ============================================================

-- service_role: full access (bypasses RLS, used by FastAPI backend)
GRANT ALL ON public.assessment_config TO service_role;

-- Explicitly deny access to other roles
REVOKE ALL ON public.assessment_config FROM authenticated;
REVOKE ALL ON public.assessment_config FROM anon;
