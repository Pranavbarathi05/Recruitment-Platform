-- ============================================================
-- Migration 014: Assessment Program (semester -> assessment scope)
-- ============================================================
-- PHASE 2 (schema foundations only) of the modular assessment
-- architecture. This migration creates ONE new table and seeds it.
-- It changes NO existing table and NO application behaviour.
--
-- WHY THIS TABLE EXISTS
--   Today the ONLY semester-aware branch in the whole assessment
--   engine is MCQ selection (routers/assessment.py filters
--   mcq_questions by candidates.semester). Every other assessment
--   decision is global, taken from the single active
--   public.assessment_config row.
--
--   The approved architecture needs a place to express per-semester
--   POLICY before any module counts can be resolved. This is that
--   place, and it is deliberately the ONLY table where `semester` is
--   a configuration key.
--
-- SOURCE OF TRUTH
--   candidates.semester (migration 001, tightened to 1/3/5/7 in
--   migration 003). This migration does NOT introduce a second
--   junior/senior candidate field and does NOT change candidate
--   semester handling. `tier` below is a derived LABEL for the
--   technical scope, not a candidate attribute.
--
-- APPROVED SEMANTICS (seeded at the bottom of this file)
--   semester 1 -> organizational, 1 domain,  no coding
--   semester 3 -> technical, junior, 2 domains, coding enabled
--   semester 5 -> technical, senior, 2 domains, coding enabled
--   semester 7 -> none, 1 domain, no coding
--
-- CODING COUNT IS INTENTIONALLY NOT HERE
--   There is deliberately NO coding_count_override column. For both
--   technical semesters the coding count stays global and continues
--   to come from assessment_config.coding_problem_count
--   (routers/assessment.py::_select_coding_problems). Only the
--   on/off decision lives here, in coding_enabled.
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
--   - Does not touch assessment_config (all its columns stay as-is,
--     including the now-legacy total_questions).
--   - Does not touch assessment_attempts.
--   - Does not touch domains.duration_minutes (still deprecated).
--   - Does not implement the planner/resolver.
--   - Does not change /assessment/start.
--
-- SAFE: Additive only. New table, no existing data modified.
-- RERUN-SAFE: CREATE TABLE IF NOT EXISTS; constraint and index names
--   guarded; seed is ON CONFLICT (semester) DO NOTHING.
-- ============================================================

-- ============================================================
-- 1. TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.assessment_program (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    semester INTEGER NOT NULL,
    scope TEXT NOT NULL,
    tier TEXT,
    max_domains INTEGER NOT NULL,
    coding_enabled BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One policy row per semester. Also gives the seed below a
    -- conflict target.
    CONSTRAINT assessment_program_semester_key UNIQUE (semester),

    -- Reuses the EXISTING semester value set verbatim
    -- (candidates.semester and mcq_questions.semester both use it).
    CONSTRAINT assessment_program_semester_check
        CHECK (semester IN (1, 3, 5, 7)),

    CONSTRAINT assessment_program_scope_check
        CHECK (scope IN ('organizational', 'technical', 'none')),

    -- tier is only meaningful for the technical scope.
    CONSTRAINT assessment_program_tier_check
        CHECK (tier IS NULL OR tier IN ('junior', 'senior')),

    -- A technical program MUST declare a tier; every non-technical
    -- program MUST leave it NULL. Keeps `tier` honest so the planner
    -- can never silently resolve the wrong configuration family.
    CONSTRAINT assessment_program_tier_scope_check
        CHECK (
            (scope = 'technical' AND tier IS NOT NULL)
            OR (scope <> 'technical' AND tier IS NULL)
        ),

    -- Mirrors assessment_config.max_domains, which caps the number of
    -- domains the existing engine can serve (1 or 2).
    CONSTRAINT assessment_program_max_domains_check
        CHECK (max_domains >= 1 AND max_domains <= 2)
);

-- updated_at trigger (same convention as 001/003/004/006)
DROP TRIGGER IF EXISTS update_assessment_program_updated_at
    ON public.assessment_program;
CREATE TRIGGER update_assessment_program_updated_at
    BEFORE UPDATE ON public.assessment_program
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 2. INDEXES
-- ============================================================
-- semester is already indexed by its UNIQUE constraint. scope is the
-- column the planner filters on to answer "is this a technical
-- assessment?", so index it for the admin/lookup path.

CREATE INDEX IF NOT EXISTS idx_assessment_program_scope
    ON public.assessment_program(scope);

-- ============================================================
-- 3. SEED THE FOUR APPROVED PROGRAM ROWS
-- ============================================================
-- Idempotent: ON CONFLICT (semester) DO NOTHING, so re-running this
-- migration never rewrites a program an admin has since edited.
--
-- semester 1: Organizational Roles only. Exactly ONE domain, and NO
--   coding. Coding is off because the organizational assessment is a
--   common non-technical test, not a domain-specific technical one.
-- semester 3: Junior technical. Coding enabled, count from global
--   assessment_config.coding_problem_count.
-- semester 5: Senior technical. Same, senior-tier configuration.
-- semester 7: No assessment.

INSERT INTO public.assessment_program (
    semester, scope, tier, max_domains, coding_enabled, is_active, notes
) VALUES
    (1, 'organizational', NULL,     1, false, true,
     'Organizational Roles only. Exactly one domain, no coding.'),
    (3, 'technical',      'junior', 2, true,  true,
     'Junior technical assessment. Coding count from global assessment_config.coding_problem_count.'),
    (5, 'technical',      'senior', 2, true,  true,
     'Senior technical assessment. Coding count from global assessment_config.coding_problem_count.'),
    (7, 'none',           NULL,     1, false, true,
     'No assessment.')
ON CONFLICT (semester) DO NOTHING;

-- ============================================================
-- 4. ROW LEVEL SECURITY
-- ============================================================
-- Same model as assessment_config (migration 004): this is
-- admin/engine configuration, read and written exclusively by the
-- FastAPI backend using service_role. There are deliberately NO
-- candidate-facing policies and no candidate-facing grants.

ALTER TABLE public.assessment_program ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 5. GRANTS
-- ============================================================

-- service_role: full access (bypasses RLS, used by FastAPI backend)
GRANT ALL ON public.assessment_program TO service_role;

-- Explicitly deny access to other roles
REVOKE ALL ON public.assessment_program FROM authenticated;
REVOKE ALL ON public.assessment_program FROM anon;

-- ============================================================
-- Verification (run manually after applying):
--   SELECT semester, scope, tier, max_domains, coding_enabled
--   FROM public.assessment_program ORDER BY semester;
-- Must return exactly these four rows:
--   1 | organizational | NULL   | 1 | false
--   3 | technical      | junior | 2 | true
--   5 | technical      | senior | 2 | true
--   7 | none           | NULL   | 1 | false
--
--   -- tier/scope coupling must reject these:
--   UPDATE public.assessment_program SET tier = 'junior' WHERE semester = 1;  -- ERROR
--   UPDATE public.assessment_program SET tier = NULL     WHERE semester = 3;  -- ERROR
-- ============================================================
