-- ============================================================
-- Migration 010: Descriptive Questions
-- ============================================================
-- Adds:
--   1. descriptive_questions table
--   2. assessment_descriptive_answers table
--   3. Descriptive columns on assessment_attempts
--   4. Descriptive count on assessment_config
--   5. Supabase Storage bucket for question images
--   6. RLS policies and GRANTs
--   7. updated_at trigger on descriptive_questions
--
-- SAFE: Additive only. Does not drop tables or delete data.
-- ============================================================

-- ============================================================
-- 1. DESCRIPTIVE QUESTIONS TABLE
-- ============================================================
-- Each question belongs to zero or more domains via domain_ids UUID[].
-- MCQ questions use a single domain_id FK; descriptive questions
-- use an array because they can be domain-agnostic or multi-domain.
-- is_active follows the existing MCQ/coding convention.

CREATE TABLE IF NOT EXISTS public.descriptive_questions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question_text TEXT NOT NULL,
    image_url TEXT,
    word_limit INTEGER CHECK (word_limit IS NULL OR word_limit > 0),
    domain_ids UUID[] NOT NULL DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for query patterns
CREATE INDEX IF NOT EXISTS idx_descriptive_is_active
    ON public.descriptive_questions(is_active);

CREATE INDEX IF NOT EXISTS idx_descriptive_domain_ids
    ON public.descriptive_questions USING GIN (domain_ids);

-- updated_at trigger
DROP TRIGGER IF EXISTS update_descriptive_questions_updated_at ON public.descriptive_questions;
CREATE TRIGGER update_descriptive_questions_updated_at
    BEFORE UPDATE ON public.descriptive_questions
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();


-- ============================================================
-- 2. ASSESSMENT DESCRIPTIVE ANSWERS TABLE
-- ============================================================
-- Stores each candidate's free-text answer for a descriptive question.
-- Follows the same pattern as assessment_answers (MCQ).
-- UNIQUE(attempt_id, question_id) prevents duplicate answers.
-- Descriptive answers are manually evaluated — no is_correct column.

CREATE TABLE IF NOT EXISTS public.assessment_descriptive_answers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    attempt_id UUID NOT NULL REFERENCES public.assessment_attempts(id) ON DELETE CASCADE,
    question_id UUID NOT NULL REFERENCES public.descriptive_questions(id) ON DELETE RESTRICT,
    answer_text TEXT NOT NULL DEFAULT '',
    answered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_desc_answers_attempt_id
    ON public.assessment_descriptive_answers(attempt_id);


-- ============================================================
-- 3. ASSESSMENT ATTEMPTS: ADD DESCRIPTIVE COLUMNS
-- ============================================================
-- selected_descriptive_question_ids: frozen JSONB array of UUIDs.
-- total_descriptive_questions: count for UI display.
-- Defaults ensure existing attempts are unaffected.

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS selected_descriptive_question_ids JSONB NOT NULL DEFAULT '[]';

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS total_descriptive_questions INTEGER NOT NULL DEFAULT 0;


-- ============================================================
-- 4. ASSESSMENT CONFIG: ADD DESCRIPTIVE COUNT
-- ============================================================

ALTER TABLE public.assessment_config
    ADD COLUMN IF NOT EXISTS descriptive_question_count INTEGER NOT NULL DEFAULT 0;


-- ============================================================
-- 5. SUPABASE STORAGE BUCKET FOR QUESTION IMAGES
-- ============================================================
-- Public bucket so candidates can render <img> tags.
-- Admin uploads go through FastAPI using service_role (bypasses RLS).

INSERT INTO storage.buckets (id, name, public)
VALUES ('question-images', 'question-images', true)
ON CONFLICT (id) DO NOTHING;

-- Public read policy: anyone can view question images
CREATE POLICY IF NOT EXISTS "question_images_public_read"
    ON storage.objects FOR SELECT
    USING (bucket_id = 'question-images');


-- ============================================================
-- 6. ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE public.descriptive_questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assessment_descriptive_answers ENABLE ROW LEVEL SECURITY;

-- descriptive_questions: no candidate-facing policies.
-- Admin CRUD goes through FastAPI using service_role.
-- Candidates have no GRANT on this table.

-- assessment_descriptive_answers: candidates SELECT own answers.
-- All writes go through FastAPI using service_role.

CREATE POLICY IF EXISTS "Users can view own descriptive answers"
    ON public.assessment_descriptive_answers FOR SELECT
    USING (
        attempt_id IN (
            SELECT id FROM public.assessment_attempts
            WHERE profile_id = auth.uid()
        )
    );


-- ============================================================
-- 7. GRANTS
-- ============================================================

-- service_role: full access (bypasses RLS, used by FastAPI backend)
GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- descriptive_questions: no access for candidates/anon
REVOKE ALL ON public.descriptive_questions FROM authenticated;
REVOKE ALL ON public.descriptive_questions FROM anon;

-- assessment_descriptive_answers: authenticated can SELECT own rows (via RLS)
GRANT SELECT ON public.assessment_descriptive_answers TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.assessment_descriptive_answers FROM authenticated;
REVOKE ALL ON public.assessment_descriptive_answers FROM anon;
