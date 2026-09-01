-- ============================================================
-- Migration 006: Combined MCQ + Coding Assessment System
-- ============================================================
-- Architecture: ONE assessment attempt contains BOTH MCQ and Coding.
--
-- Adds:
--   1. coding_problems — admin-managed problem bank
--   2. coding_test_cases — public + hidden test cases
--   3. coding_submissions — per-problem server-evaluated results
--   4. coding_drafts — autosave drafts
--   5. coding_problem_count on assessment_config
--   6. coding problem columns on assessment_attempts
--   7. Combined scoring columns on assessment_attempts
--   8. RLS, indexes, triggers, GRANTs
--
-- Does NOT add assessment_type — MCQ and Coding are sections
-- of ONE assessment attempt, not separate assessment types.
--
-- SAFE: Additive only. Does not modify existing data or tables.
-- ============================================================

-- ============================================================
-- 0. SAFETY CHECK
-- ============================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'coding_problems' AND table_schema = 'public') THEN
        RAISE EXCEPTION 'MIGRATION BLOCKED: coding_problems table already exists';
    END IF;
END $$;

-- ============================================================
-- 1. ASSESSMENT CONFIG — Add coding_problem_count
-- ============================================================
-- The config now has BOTH mcq question count and coding problem count.
-- total_questions remains the MCQ question count.
-- coding_problem_count is how many coding problems per assessment.

ALTER TABLE public.assessment_config
    ADD COLUMN IF NOT EXISTS coding_problem_count INTEGER NOT NULL DEFAULT 2
    CHECK (coding_problem_count >= 0);

-- ============================================================
-- 2. ASSESSMENT ATTEMPTS — Add coding + combined scoring columns
-- ============================================================
-- selected_coding_problem_ids: frozen JSONB array of coding problem UUIDs
-- total_coding_problems: number of coding problems in this attempt
-- mcq_score / mcq_max_score: MCQ section scoring
-- coding_score / coding_max_score: coding section scoring

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS selected_coding_problem_ids JSONB DEFAULT '[]'::jsonb;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS total_coding_problems INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS mcq_score INTEGER DEFAULT 0;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS mcq_max_score INTEGER DEFAULT 0;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS coding_score INTEGER DEFAULT 0;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS coding_max_score INTEGER DEFAULT 0;

-- ============================================================
-- 3. CODING PROBLEMS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.coding_problems (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES public.domains(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'medium'
        CHECK (difficulty IN ('easy', 'medium', 'hard')),
    constraints TEXT,
    input_format TEXT,
    output_format TEXT,
    explanation TEXT,
    starter_code JSONB DEFAULT '{}',
    supported_languages JSONB NOT NULL DEFAULT '["python3", "cpp", "java"]'::jsonb,
    time_limit_ms INTEGER NOT NULL DEFAULT 2000 CHECK (time_limit_ms > 0),
    memory_limit_mb INTEGER NOT NULL DEFAULT 256 CHECK (memory_limit_mb > 0),
    points INTEGER NOT NULL DEFAULT 10 CHECK (points > 0),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_problems_domain_id ON public.coding_problems(domain_id);
CREATE INDEX IF NOT EXISTS idx_coding_problems_is_active ON public.coding_problems(is_active);
CREATE INDEX IF NOT EXISTS idx_coding_problems_domain_active ON public.coding_problems(domain_id, is_active);

DROP TRIGGER IF EXISTS update_coding_problems_updated_at ON public.coding_problems;
CREATE TRIGGER update_coding_problems_updated_at
    BEFORE UPDATE ON public.coding_problems
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 4. CODING TEST CASES TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.coding_test_cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    problem_id UUID NOT NULL REFERENCES public.coding_problems(id) ON DELETE CASCADE,
    input TEXT NOT NULL,
    expected_output TEXT NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT false,
    points INTEGER NOT NULL DEFAULT 1 CHECK (points > 0),
    ordering INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_coding_test_cases_problem_id ON public.coding_test_cases(problem_id);
CREATE INDEX IF NOT EXISTS idx_coding_test_cases_public ON public.coding_test_cases(problem_id, is_public);

-- ============================================================
-- 5. CODING SUBMISSIONS TABLE
-- ============================================================
-- Each submission is for one problem within the shared assessment attempt.
-- UNIQUE(attempt_id, problem_id) prevents duplicate submissions per problem.

CREATE TABLE IF NOT EXISTS public.coding_submissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id UUID NOT NULL REFERENCES public.assessment_attempts(id) ON DELETE CASCADE,
    problem_id UUID NOT NULL REFERENCES public.coding_problems(id) ON DELETE RESTRICT,
    language TEXT NOT NULL,
    source_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'passed', 'failed', 'error', 'timeout')),
    score INTEGER DEFAULT 0,
    max_score INTEGER DEFAULT 0,
    tests_passed INTEGER DEFAULT 0,
    tests_total INTEGER DEFAULT 0,
    execution_time_ms INTEGER,
    memory_used_mb NUMERIC,
    error_message TEXT,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, problem_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_submissions_attempt_id ON public.coding_submissions(attempt_id);
CREATE INDEX IF NOT EXISTS idx_coding_submissions_problem_id ON public.coding_submissions(problem_id);

-- ============================================================
-- 6. CODING DRAFTS TABLE (AUTOSAVE)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.coding_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id UUID NOT NULL REFERENCES public.assessment_attempts(id) ON DELETE CASCADE,
    problem_id UUID NOT NULL REFERENCES public.coding_problems(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    source_code TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, problem_id)
);

CREATE INDEX IF NOT EXISTS idx_coding_drafts_attempt_id ON public.coding_drafts(attempt_id);

DROP TRIGGER IF EXISTS update_coding_drafts_updated_at ON public.coding_drafts;
CREATE TRIGGER update_coding_drafts_updated_at
    BEFORE UPDATE ON public.coding_drafts
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 7. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE public.coding_problems ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coding_test_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coding_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coding_drafts ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 8. GRANTS
-- ============================================================

-- service_role: full access (bypasses RLS)
GRANT ALL ON public.coding_problems TO service_role;
GRANT ALL ON public.coding_test_cases TO service_role;
GRANT ALL ON public.coding_submissions TO service_role;
GRANT ALL ON public.coding_drafts TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- Explicitly deny all access to authenticated and anon
REVOKE ALL ON public.coding_problems FROM authenticated;
REVOKE ALL ON public.coding_problems FROM anon;
REVOKE ALL ON public.coding_test_cases FROM authenticated;
REVOKE ALL ON public.coding_test_cases FROM anon;
REVOKE ALL ON public.coding_submissions FROM authenticated;
REVOKE ALL ON public.coding_submissions FROM anon;
REVOKE ALL ON public.coding_drafts FROM authenticated;
REVOKE ALL ON public.coding_drafts FROM anon;
