-- ============================================================
-- Migration 016: assessment_module_config (domain x tier module counts)
-- ============================================================
-- PHASE 2 (schema foundations only). Creates ONE new table. It
-- changes no existing table and no application behaviour.
--
-- WHY THIS TABLE EXISTS
--   Today every module count comes from the single active
--   public.assessment_config row: descriptive_question_count and
--   hands_on_question_count are each ONE global number, and MCQ
--   distribution is a hardcoded global 50/50 split of total_questions.
--   There is no way to say "CyberSec/Senior gets a hands-on
--   challenge, CyberSec/Junior does not".
--
--   This table is where that per-domain configuration will live.
--   Rows are keyed (domain_id, applies_to).
--
-- WHY (domain_id, applies_to) AND NOT (domain_id, semester)
--   There are two different configuration scopes:
--     1. organizational - ONE common configuration. Semester 1 is the
--        only program that reaches it, but the configuration itself
--        is NOT semester-specific, so keying it by semester would be
--        wrong (and would wrongly imply per-semester variation).
--     2. technical - Junior (semester 3) and Senior (semester 5).
--        Here the tier genuinely changes the counts, so it is the key.
--   assessment_program (migration 014) maps a candidate's semester to
--   ('organizational' | junior | senior | none); the planner will use
--   that mapping to look a row up here. Semester itself is never a
--   column here, which keeps one and only one semester->scope mapping
--   in the schema.
--
-- ADDITIONAL TIME IS BOUND TO THE MODULE THAT CARRIES IT
--   hands_on_additional_minutes is intentionally NOT a free-floating
--   "bonus minutes" field. It is the time that comes WITH the hands-on
--   module, which is why the constraints below forbid a disabled
--   hands-on module from carrying any of it. CyberSec/Senior would be
--   (hands_on_enabled=true, hands_on_count=1,
--   hands_on_additional_minutes=20); CyberSec/Junior would be
--   (false, 0, 0).
--
-- THIS TABLE IS INTENTIONALLY LEFT EMPTY
--   No configuration rows are inserted here. Authoring them is a
--   later phase, and until then the planner must NOT silently fall
--   back to the legacy global counts (that would wrongly hand a
--   candidate hands-on and coding time).
--
-- WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
--   - Does not touch assessment_config or remove any legacy column.
--   - Does not touch assessment_attempts.
--   - Does not touch domains.duration_minutes.
--   - Does not implement the planner, admin UI, or any endpoint.
--
-- SAFE: Additive only. New table, no existing data modified.
-- RERUN-SAFE: CREATE TABLE IF NOT EXISTS; index and trigger
--   guarded/dropped first.
-- ============================================================

-- ============================================================
-- 1. TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.assessment_module_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Deleting a domain removes its configuration with it.
    domain_id UUID NOT NULL
        REFERENCES public.domains(id) ON DELETE CASCADE,

    -- 'organizational' is the common, non-semester-specific scope.
    -- 'junior' / 'senior' are the two technical tiers.
    applies_to TEXT NOT NULL,

    mcq_count INTEGER NOT NULL DEFAULT 0,
    descriptive_count INTEGER NOT NULL DEFAULT 0,

    hands_on_enabled BOOLEAN NOT NULL DEFAULT false,
    hands_on_count INTEGER NOT NULL DEFAULT 0,

    -- Time that accompanies the hands-on module (see header note).
    hands_on_additional_minutes INTEGER NOT NULL DEFAULT 0,

    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Exactly ONE configuration per (domain, scope/tier).
    CONSTRAINT assessment_module_config_domain_applies_key
        UNIQUE (domain_id, applies_to),

    CONSTRAINT assessment_module_config_applies_to_check
        CHECK (applies_to IN ('junior', 'senior', 'organizational')),

    CONSTRAINT assessment_module_config_mcq_count_check
        CHECK (mcq_count >= 0),

    CONSTRAINT assessment_module_config_descriptive_count_check
        CHECK (descriptive_count >= 0),

    CONSTRAINT assessment_module_config_hands_on_count_check
        CHECK (hands_on_count >= 0),

    CONSTRAINT assessment_module_config_hands_on_minutes_check
        CHECK (hands_on_additional_minutes >= 0),

    -- A DISABLED hands-on module may not carry challenges ...
    CONSTRAINT assessment_module_config_hands_on_count_requires_enabled
        CHECK (hands_on_enabled = true OR hands_on_count = 0),

    -- ... and may not carry additional time either. This is the
    -- database-level guarantee against a disabled module silently
    -- granting the additional minutes that belong to it.
    CONSTRAINT assessment_module_config_hands_on_minutes_requires_enabled
        CHECK (hands_on_enabled = true OR hands_on_additional_minutes = 0)
);

-- updated_at trigger (same convention as 001/003/004/006)
DROP TRIGGER IF EXISTS update_assessment_module_config_updated_at
    ON public.assessment_module_config;
CREATE TRIGGER update_assessment_module_config_updated_at
    BEFORE UPDATE ON public.assessment_module_config
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 2. INDEXES
-- ============================================================
-- The (domain_id, applies_to) UNIQUE constraint already covers
-- domain_id-leading lookups. The planner also asks "every
-- organizational row" / "every senior row" without naming a domain,
-- so index applies_to on its own.

CREATE INDEX IF NOT EXISTS idx_assessment_module_config_applies_to
    ON public.assessment_module_config(applies_to);

-- ============================================================
-- 3. NO SEED DATA
-- ============================================================
-- Deliberately empty. Do NOT add INSERTs here; per-domain counts are
-- authored in a later phase through the admin UI. Until those rows
-- exist, configuration resolution for a domain has no answer and the
-- planner must fail loudly rather than inherit global legacy counts.

-- ============================================================
-- 4. ROW LEVEL SECURITY
-- ============================================================
-- Same model as assessment_config (migration 004) and
-- assessment_program (migration 014): admin/engine configuration,
-- read and written exclusively by the FastAPI backend using
-- service_role. No candidate-facing policies, no candidate grants.

ALTER TABLE public.assessment_module_config ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 5. GRANTS
-- ============================================================

-- service_role: full access (bypasses RLS, used by FastAPI backend)
GRANT ALL ON public.assessment_module_config TO service_role;

-- Explicitly deny access to other roles
REVOKE ALL ON public.assessment_module_config FROM authenticated;
REVOKE ALL ON public.assessment_module_config FROM anon;

-- ============================================================
-- Verification (run manually after applying):
--   SELECT count(*) FROM public.assessment_module_config;   -- 0
--
--   -- disabled hands-on cannot carry a count or time:
--   INSERT INTO public.assessment_module_config
--       (domain_id, applies_to, hands_on_enabled, hands_on_count)
--   VALUES ((SELECT id FROM public.domains WHERE slug = 'cyberSecurity'),
--           'junior', false, 1);                             -- ERROR
--
--   INSERT INTO public.assessment_module_config
--       (domain_id, applies_to, hands_on_enabled, hands_on_additional_minutes)
--   VALUES ((SELECT id FROM public.domains WHERE slug = 'cyberSecurity'),
--           'junior', false, 20);                            -- ERROR
--
--   -- duplicate configuration for one domain+tier:
--   ... inserted twice ...                                   -- ERROR (unique)
--
--   -- applies_to is constrained:
--   ... applies_to = 'sophomore' ...                         -- ERROR
-- ============================================================
