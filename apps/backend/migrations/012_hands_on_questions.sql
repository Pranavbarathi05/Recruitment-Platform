-- ============================================================
-- Migration 012: Hands-On Challenges (SQL Injection micro-CTF)
-- ============================================================
-- Adds:
--   1. hands_on_questions table (challenge metadata + expected flag)
--   2. Hands-On columns on assessment_attempts (frozen selection)
--   3. hands_on_question_count on assessment_config
--   4. assessment_hands_on_results table (evidence + verified flag result)
--   5. RLS (both tables; no candidate policies — all access via service_role)
--   6. GRANTs (narrow service_role grants; candidate roles fully revoked)
--
-- SAFE: Additive only. Does not drop tables or delete data.
-- RERUN-SAFE: All CREATE statements are idempotent. No policies are created,
--   so no DO $$ policy-guard blocks are needed in this migration.
-- ============================================================

-- ============================================================
-- 1. HANDS-ON QUESTIONS TABLE
-- ============================================================
-- Each challenge belongs to zero or more domains via domain_ids UUID[]
-- (same multi-domain convention as descriptive_questions).
--
-- challenge_type is a fixed registry, NOT arbitrary execution:
--   'sql_injection_employee_portal' → the shared Employee Portal challenge.
-- The admin configures metadata (title/description/difficulty/points) and
-- the expected flag. The challenge URL is displayed to candidates.
--
-- expected_flag is SECRET. RLS + GRANTs below guarantee it can only leave
-- the database through the service_role connection used by FastAPI admin
-- endpoints; candidate-facing endpoints never select it.
--
-- points: 0–1000. Awarded in full when the submitted flag matches exactly
-- (after trimming surrounding whitespace); 0 otherwise.

CREATE TABLE IF NOT EXISTS public.hands_on_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    domain_ids UUID[] NOT NULL DEFAULT '{}',
    challenge_type TEXT NOT NULL DEFAULT 'sql_injection_employee_portal'
        CHECK (challenge_type IN ('sql_injection_employee_portal')),
    difficulty TEXT NOT NULL DEFAULT 'medium'
        CHECK (difficulty IN ('easy', 'medium', 'hard')),
    points INTEGER NOT NULL DEFAULT 100 CHECK (points >= 0 AND points <= 1000),
    challenge_url TEXT NOT NULL,
    expected_flag TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hands_on_is_active
    ON public.hands_on_questions(is_active);

CREATE INDEX IF NOT EXISTS idx_hands_on_domain_ids
    ON public.hands_on_questions USING GIN (domain_ids);

-- updated_at trigger (function already exists from migration 010)
DROP TRIGGER IF EXISTS update_hands_on_questions_updated_at ON public.hands_on_questions;
CREATE TRIGGER update_hands_on_questions_updated_at
    BEFORE UPDATE ON public.hands_on_questions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();


-- ============================================================
-- 2. ASSESSMENT ATTEMPTS: HANDS-ON SELECTION COLUMNS
-- ============================================================
-- Same frozen-selection pattern as descriptive questions (migration 010).

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS selected_hands_on_question_ids JSONB NOT NULL DEFAULT '[]';

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS total_hands_on_questions INTEGER NOT NULL DEFAULT 0;


-- ============================================================
-- 3. ASSESSMENT CONFIG: HANDS-ON COUNT
-- ============================================================
-- Default 0 → every existing assessment behaves exactly as before.

ALTER TABLE public.assessment_config
    ADD COLUMN IF NOT EXISTS hands_on_question_count INTEGER NOT NULL DEFAULT 0;


-- ============================================================
-- 4. ASSESSMENT HANDS-ON RESULTS TABLE
-- ============================================================
-- One row per (attempt, challenge). Holds:
--   submitted_input  → the SQL payload the candidate pasted (EVIDENCE ONLY —
--                      stored verbatim, never parsed, executed or verified)
--   submitted_flag   → the flag the candidate claims to have discovered
--   verified         → true iff submitted_flag == expected flag (exact,
--                      after trimming surrounding whitespace)
--   score            → full question points when verified, else 0
--
-- UNIQUE(attempt_id, question_id) makes resubmission an idempotent UPDATE.
-- The candidate-facing endpoint returns only verified/score — never the
-- expected flag, and the submitted input is never re-evaluated.

CREATE TABLE IF NOT EXISTS public.assessment_hands_on_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id UUID NOT NULL REFERENCES public.assessment_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.hands_on_questions(id) ON DELETE RESTRICT,
    submitted_input TEXT NOT NULL DEFAULT '',
    submitted_flag TEXT NOT NULL DEFAULT '',
    verified BOOLEAN NOT NULL DEFAULT false,
    score INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_hands_on_results_attempt_id
    ON public.assessment_hands_on_results(attempt_id);


-- ============================================================
-- 5. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE public.hands_on_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assessment_hands_on_results ENABLE ROW LEVEL SECURITY;

-- hands_on_questions: NO policies at all. Admin CRUD goes through FastAPI
-- using service_role (bypasses RLS). Candidates have no GRANT on this table,
-- so the expected flag cannot be read directly even by authenticated users.

-- assessment_hands_on_results: NO policies either. Candidates reach their
-- results exclusively through FastAPI (service_role); they have no direct
-- Supabase access, so a candidate-read policy would only widen the surface
-- without any client that needs it.


-- ============================================================
-- 6. GRANTS
-- ============================================================

-- service_role: narrowly scoped to ONLY the two new hands-on tables.
-- Broader grants on other tables remain governed by earlier migrations —
-- this migration must not widen privileges on unrelated tables.
GRANT ALL ON public.hands_on_questions TO service_role;
GRANT ALL ON public.assessment_hands_on_results TO service_role;

-- Defense-in-depth: strip the default PUBLIC grant on both new tables so no
-- role inherits access implicitly. No explicit grants exist for candidate
-- roles; every read/write flows through FastAPI's service_role connection.
REVOKE ALL ON public.hands_on_questions FROM PUBLIC;
REVOKE ALL ON public.assessment_hands_on_results FROM PUBLIC;

-- hands_on_questions: admin-only via service_role. No candidate/anon access
-- whatsoever — this is what protects expected_flag.
REVOKE ALL ON public.hands_on_questions FROM authenticated;
REVOKE ALL ON public.hands_on_questions FROM anon;

-- assessment_hands_on_results: no candidate/anon access at all. All writes
-- and reads go through FastAPI using service_role (backend-authoritative).
REVOKE ALL ON public.assessment_hands_on_results FROM authenticated;
REVOKE ALL ON public.assessment_hands_on_results FROM anon;
