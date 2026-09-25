-- ============================================================
-- Migration 023: Optional network-integrity monitoring
-- ============================================================
-- Adds the two persisted facts the optional assessment
-- network-integrity monitor needs. Nothing else changes.
--
--   1. assessment_config.network_integrity_monitoring
--        The ADMIN TOGGLE. Default FALSE, so every existing
--        assessment keeps behaving exactly as it does today and
--        monitoring never starts until an admin turns it on.
--
--   2. assessment_attempts.termination_reason
--        WHY an attempt ended, when it did not end by ordinary
--        submission. NULL means "ordinary submission" (or a legacy
--        row), so the normal result presentation is untouched.
--        Currently written as 'network_integrity_violation'.
--
-- WHY ONLY TWO COLUMNS
--   The per-attempt FREEZE of the policy needs no column: the
--   frozen plan snapshot (migration 017, assessment_attempts.plan
--   JSONB) already stores the complete AssessmentPlan as JSON, and
--   `network_integrity_monitoring` is carried inside it. A plan
--   snapshot created before this migration simply has no such key
--   and is read as "monitoring disabled", which is the correct
--   historical behaviour for those attempts.
--
-- SAFE: additive only, no backfill, no data rewritten, no row
--       modified. Existing attempts keep termination_reason NULL.
-- RERUN-SAFE: ADD COLUMN IF NOT EXISTS; grants are idempotent.
-- ============================================================

-- ============================================================
-- 1. THE ADMIN TOGGLE (global, default OFF)
-- ============================================================

ALTER TABLE public.assessment_config
    ADD COLUMN IF NOT EXISTS network_integrity_monitoring BOOLEAN NOT NULL DEFAULT false;

-- ============================================================
-- 2. THE TERMINATION REASON (per attempt, nullable)
-- ============================================================
-- Nullable by design:
--   NULL            -> ordinary submission (the default for every
--                      existing and future normal attempt)
--   'network_integrity_violation' -> policy termination
--
-- No CHECK constraint is added: the value is written by the
-- backend from a fixed allowlist, and a future trigger must be an
-- added enum value rather than a migration.

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS termination_reason TEXT;

-- ============================================================
-- 3. GRANTS (re-asserted, matches migrations 004 / 005 / 011)
-- ============================================================
-- service_role keeps full access (the FastAPI backend is the only
-- reader/writer of both columns). Candidate roles must have no
-- direct access: assessment_config is candidate-invisible, and
-- assessment_attempts was revoked for authenticated/anon in 005.

GRANT ALL ON public.assessment_config TO service_role;
REVOKE ALL ON public.assessment_config FROM authenticated;
REVOKE ALL ON public.assessment_config FROM anon;

GRANT ALL ON public.assessment_attempts TO service_role;
REVOKE ALL ON public.assessment_attempts FROM authenticated;
REVOKE ALL ON public.assessment_attempts FROM anon;

-- ============================================================
-- 4. INDEX (admin results filter by termination reason)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_attempts_termination_reason
    ON public.assessment_attempts(termination_reason)
    WHERE termination_reason IS NOT NULL;

-- ============================================================
-- Verification (run manually after applying):
--   SELECT column_name, data_type, column_default, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'public'
--     AND ((table_name = 'assessment_config'
--           AND column_name = 'network_integrity_monitoring')
--       OR (table_name = 'assessment_attempts'
--           AND column_name = 'termination_reason'));
-- Expects exactly two rows:
--   assessment_config.network_integrity_monitoring  boolean  default false  NOT NULL
--   assessment_attempts.termination_reason          text     (nullable)
--
-- Confirm monitoring is OFF everywhere after applying:
--   SELECT id, name, network_integrity_monitoring FROM public.assessment_config;
-- ============================================================
