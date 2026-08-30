-- ============================================================
-- Migration 003: MCQ Assessment System
-- ============================================================
-- This migration adds:
--   1. Admin flag on profiles
--   2. Domain enhancements (description, updated_at)
--   3. Semester constraint change (1-8 -> 1/3/5/7)
--   4. MCQ question bank (with semester)
--   5. Assessment attempts (frozen question selection)
--   6. Assessment answers
--   7. RLS policies
--   8. Explicit GRANTs and REVOKEs
--   9. Domain description seed data
--  10. Updated auth trigger (no CSE fallback, strict validation)
--
-- SAFE: Additive only. Does not drop tables or delete data.
-- FAILS SAFE: If invalid semester values exist, the migration
-- halts with a clear error rather than silently modifying data.
-- ============================================================

-- ============================================================
-- 0. CHECK existing semesters before constraining
-- ============================================================
-- If any candidates have semesters outside {1,3,5,7}, the
-- migration FAILS with a clear error. The operator must fix
-- the invalid rows before re-running this migration.
-- We do NOT silently modify candidate data.

DO $$
DECLARE
    bad_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO bad_count
    FROM public.candidates
    WHERE semester NOT IN (1, 3, 5, 7);

    IF bad_count > 0 THEN
        RAISE EXCEPTION
            'MIGRATION BLOCKED: % candidate(s) have semesters outside {1,3,5,7}. '
            'Fix these rows before applying the constraint. '
            'Query: SELECT id, usn, semester FROM public.candidates WHERE semester NOT IN (1,3,5,7);',
            bad_count;
    END IF;
END $$;

-- ============================================================
-- 1. ALTER PROFILES: Add admin flag
-- ============================================================

ALTER TABLE public.profiles
    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;

-- ============================================================
-- 2. ALTER DOMAINS: Add description and updated_at
-- ============================================================

ALTER TABLE public.domains
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';

ALTER TABLE public.domains
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- updated_at trigger for domains
DROP TRIGGER IF EXISTS update_domains_updated_at ON public.domains;
CREATE TRIGGER update_domains_updated_at
    BEFORE UPDATE ON public.domains
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 3. ALTER CANDIDATES: Semester constraint 1-8 -> 1/3/5/7
-- ============================================================
-- Drop the old CHECK constraint, add the new one.
-- The old constraint was: CHECK (semester BETWEEN 1 AND 8)

ALTER TABLE public.candidates
    DROP CONSTRAINT IF EXISTS candidates_semester_check;

ALTER TABLE public.candidates
    ADD CONSTRAINT candidates_semester_check CHECK (semester IN (1, 3, 5, 7));

-- ============================================================
-- 4. MCQ QUESTIONS TABLE
-- ============================================================
-- Each MCQ belongs to one domain AND one semester.
-- The (domain_id, semester, is_active) index supports the
-- primary query pattern: selecting questions for a specific
-- domain + semester combination.

CREATE TABLE IF NOT EXISTS public.mcq_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES public.domains(id) ON DELETE RESTRICT,
    semester INTEGER NOT NULL CHECK (semester IN (1, 3, 5, 7)),
    question_text TEXT NOT NULL,
    option_a TEXT NOT NULL,
    option_b TEXT NOT NULL,
    option_c TEXT NOT NULL,
    option_d TEXT NOT NULL,
    correct_option TEXT NOT NULL CHECK (correct_option IN ('A', 'B', 'C', 'D')),
    explanation TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for MCQ query patterns
CREATE INDEX IF NOT EXISTS idx_mcq_domain_semester_active
    ON public.mcq_questions(domain_id, semester, is_active);
CREATE INDEX IF NOT EXISTS idx_mcq_domain_id
    ON public.mcq_questions(domain_id);
CREATE INDEX IF NOT EXISTS idx_mcq_is_active
    ON public.mcq_questions(is_active);

-- updated_at trigger for mcq_questions
DROP TRIGGER IF EXISTS update_mcq_questions_updated_at ON public.mcq_questions;
CREATE TRIGGER update_mcq_questions_updated_at
    BEFORE UPDATE ON public.mcq_questions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 5. ASSESSMENT ATTEMPTS TABLE
-- ============================================================
-- Tracks a candidate's MCQ assessment session.
-- selected_question_ids: frozen JSONB array of UUIDs.
-- domain_ids: JSONB array of 1-2 domain UUIDs.
-- Questions are immutable after attempt creation.

CREATE TABLE IF NOT EXISTS public.assessment_attempts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id UUID NOT NULL REFERENCES public.profiles(id),
    status TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'submitted', 'scored')),
    domain_ids JSONB NOT NULL,
    selected_question_ids JSONB NOT NULL,
    total_questions INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    score INTEGER DEFAULT 0,
    max_score INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_attempts_profile_id
    ON public.assessment_attempts(profile_id);
CREATE INDEX IF NOT EXISTS idx_attempts_status
    ON public.assessment_attempts(status);
CREATE INDEX IF NOT EXISTS idx_attempts_profile_status
    ON public.assessment_attempts(profile_id, status);

-- ============================================================
-- 6. ASSESSMENT ANSWERS TABLE
-- ============================================================
-- Stores each candidate's answer per question.
-- is_correct is computed on submission, not on each save.
-- UNIQUE(attempt_id, question_id) prevents duplicate answers.

CREATE TABLE IF NOT EXISTS public.assessment_answers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id UUID NOT NULL REFERENCES public.assessment_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.mcq_questions(id) ON DELETE RESTRICT,
    selected_option TEXT CHECK (selected_option IN ('A', 'B', 'C', 'D')),
    answered_at TIMESTAMPTZ,
    is_correct BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_answers_attempt_id
    ON public.assessment_answers(attempt_id);

-- ============================================================
-- 7. ROW LEVEL SECURITY (RLS)
-- ============================================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mcq_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assessment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assessment_answers ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 7a. RLS POLICIES — PROFILES
-- ============================================================

DROP POLICY IF EXISTS "Users can view own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;

CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- ============================================================
-- 7b. RLS POLICIES — CANDIDATES
-- ============================================================
-- Candidates can only VIEW their own record.
-- No INSERT/UPDATE policy — all candidate writes go through
-- FastAPI using service_role. This prevents candidates from
-- modifying their own semester, branch, or USN.

DROP POLICY IF EXISTS "Users can view own candidate record" ON public.candidates;
DROP POLICY IF EXISTS "Users can update own candidate record" ON public.candidates;

CREATE POLICY "Users can view own candidate record"
    ON public.candidates FOR SELECT
    USING (profile_id = auth.uid());

-- No INSERT policy: candidates created by handle_new_user() trigger (SECURITY DEFINER)
-- No UPDATE policy: candidate data immutable from candidate's perspective

-- ============================================================
-- 7c. RLS POLICIES — DOMAINS
-- ============================================================

DROP POLICY IF EXISTS "Anyone can view active domains" ON public.domains;

CREATE POLICY "Anyone can view active domains"
    ON public.domains FOR SELECT
    USING (is_active = true);

-- ============================================================
-- 7d. RLS POLICIES — MCQ QUESTIONS
-- ============================================================
-- Candidates do NOT directly access mcq_questions.
-- All question access goes through FastAPI using service_role.
-- No candidate-facing RLS policy is created.
-- service_role bypasses RLS entirely.

-- (no policies — candidates have no GRANT on this table)

-- ============================================================
-- 7e. RLS POLICIES — ASSESSMENT ATTEMPTS
-- ============================================================
-- Candidates can only SELECT their own attempts.
-- No INSERT/UPDATE — all writes go through FastAPI using service_role.

CREATE POLICY "Users can view own attempts"
    ON public.assessment_attempts FOR SELECT
    USING (profile_id = auth.uid());

-- No INSERT policy: attempts created by FastAPI/service_role
-- No UPDATE policy: attempts updated by FastAPI/service_role

-- ============================================================
-- 7f. RLS POLICIES — ASSESSMENT ANSWERS
-- ============================================================
-- Candidates can only SELECT their own answers.
-- No INSERT/UPDATE — all writes go through FastAPI using service_role.

CREATE POLICY "Users can view own answers"
    ON public.assessment_answers FOR SELECT
    USING (
        attempt_id IN (
            SELECT id FROM public.assessment_attempts
            WHERE profile_id = auth.uid()
        )
    );

-- No INSERT policy: answers saved by FastAPI/service_role
-- No UPDATE policy: answers updated by FastAPI/service_role

-- ============================================================
-- 8. EXPLICIT GRANT AND REVOKE STATEMENTS
-- ============================================================
-- This section explicitly defines every privilege for each role.
-- REVOKEs clear any stale grants from earlier migrations.
-- GRANTs define the minimal required access.

-- --- service_role: full access (bypasses RLS, used by FastAPI backend) ---
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- --- anon: minimal read-only access ---
-- Only needs to read active domains (e.g., for public landing pages).
GRANT SELECT ON public.domains TO anon;
-- Ensure anon has no write access to anything
REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM anon;
REVOKE USAGE ON ALL SEQUENCES IN SCHEMA public FROM anon;

-- --- authenticated: minimal access per table ---
-- profiles: can read own profile, can update own profile fields
-- (full_name, email only — is_admin is NOT updatable by candidates).
-- Column-level UPDATE grant prevents: UPDATE profiles SET is_admin = true
GRANT SELECT, UPDATE (full_name, email) ON public.profiles TO authenticated;

-- candidates: read-only. All writes through FastAPI/service_role.
-- Prevents candidates from modifying semester, branch, or USN.
GRANT SELECT ON public.candidates TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.candidates FROM authenticated;

-- domains: read-only for active domain listing
GRANT SELECT ON public.domains TO authenticated;

-- mcq_questions: NO access at all.
-- All question access goes through FastAPI using service_role.
-- Candidates must never query the question bank directly.
REVOKE ALL ON public.mcq_questions FROM authenticated;
REVOKE ALL ON public.mcq_questions FROM anon;

-- assessment_attempts: read-only. All writes through FastAPI/service_role.
GRANT SELECT ON public.assessment_attempts TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.assessment_attempts FROM authenticated;

-- assessment_answers: read-only. All writes through FastAPI/service_role.
GRANT SELECT ON public.assessment_answers TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.assessment_answers FROM authenticated;

-- ============================================================
-- 9. LOCK DOWN TRIGGER FUNCTION
-- ============================================================
-- handle_new_user() is a SECURITY DEFINER function invoked only
-- by the auth trigger on auth.users INSERT. Normal client roles
-- must never be able to call it directly.

REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM anon;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM authenticated;

-- ============================================================
-- 10. REPLACE AUTH TRIGGER — strict validation, no CSE fallback
-- ============================================================
-- The original trigger (migration 001) contains:
--   COALESCE(v_branch, 'CSE')
-- 'CSE' is no longer a valid branch.
--
-- Changes from original:
--   - semester: RAISE EXCEPTION if missing/invalid (no silent default)
--   - branch: RAISE EXCEPTION if missing (no 'CSE' fallback)
--   - usn: RAISE EXCEPTION if missing (required for candidate row)
--
-- Transactional behavior:
--   The profile INSERT and candidate INSERT are in the same
--   transaction. If the candidate INSERT fails (validation
--   error), the ENTIRE transaction rolls back — including the
--   profile INSERT. This is intentional: a partial record is
--   worse than a failed signup. The candidate must provide all
--   required fields for signup to succeed.
--
-- SECURITY DEFINER ensures the trigger runs with the function
-- owner's privileges, not the authenticated user's. This is
-- required because the trigger fires in the auth schema context.
-- SET search_path = public prevents search_path manipulation.

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
    v_full_name TEXT;
    v_email TEXT;
    v_usn TEXT;
    v_semester INTEGER;
    v_branch TEXT;
BEGIN
    -- Extract fields from Supabase Auth raw_user_meta_data
    v_full_name := COALESCE(NEW.raw_user_meta_data->>'full_name', '');
    v_email := COALESCE(NEW.email, '');
    v_usn := NULLIF(NEW.raw_user_meta_data->>'usn', '');
    v_semester := NULLIF(NEW.raw_user_meta_data->>'semester', '')::INTEGER;
    v_branch := NULLIF(NEW.raw_user_meta_data->>'branch', '');

    -- Validate required fields BEFORE any inserts.
    -- Failing early avoids a partial profile with no candidate.
    IF v_usn IS NULL THEN
        RAISE EXCEPTION 'Signup failed: USN is required for candidate registration';
    END IF;

    IF v_semester IS NULL OR v_semester NOT IN (1, 3, 5, 7) THEN
        RAISE EXCEPTION 'Signup failed: valid semester (1, 3, 5, or 7) is required';
    END IF;

    IF v_branch IS NULL THEN
        RAISE EXCEPTION 'Signup failed: branch is required for candidate registration';
    END IF;

    -- Create the profile record.
    -- If the subsequent candidate INSERT fails, this row is also
    -- rolled back (same transaction).
    INSERT INTO public.profiles (id, full_name, email)
    VALUES (NEW.id, v_full_name, v_email);

    -- Create the candidate record with validated required fields.
    -- All fields are validated above — no silent defaults or fallbacks.
    INSERT INTO public.candidates (profile_id, usn, semester, branch)
    VALUES (
        NEW.id,
        v_usn,
        v_semester,
        v_branch
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = public;

-- ============================================================
-- 11. SEED DOMAIN DESCRIPTIONS
-- ============================================================

UPDATE public.domains SET description = 'Test your knowledge of machine learning algorithms, neural networks, and data science concepts.' WHERE slug = 'machineLearning';
UPDATE public.domains SET description = 'Assess your skills in web technologies, frameworks, and modern development practices.' WHERE slug = 'webDevelopment';
UPDATE public.domains SET description = 'Evaluate your understanding of UI/UX design principles, CSS, and front-end development.' WHERE slug = 'userInterface';
UPDATE public.domains SET description = 'Challenge your knowledge of network security, cryptography, and ethical hacking.' WHERE slug = 'cyberSecurity';
UPDATE public.domains SET description = 'Test your expertise in server-side development, APIs, and database management.' WHERE slug = 'backendDevelopment';
