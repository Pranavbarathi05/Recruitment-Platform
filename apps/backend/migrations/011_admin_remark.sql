-- ============================================================
-- Migration 011: Admin Submission Remarks
-- ============================================================
-- Adds ONE private administrative remark per assessment submission.
--
-- The canonical record for an assessment submission is
-- public.assessment_attempts (one row per attempt, carrying the frozen
-- question selections, scores, and status), so the remark is stored
-- directly on that table — no second submission table, no redesign.
--
-- SAFE: Additive only. Existing rows keep NULL (no remark).
-- RERUN-SAFE: ADD COLUMN IF NOT EXISTS; index/policy guarded.
--
-- Security model (matches migrations 003/005/010):
--   - The FastAPI backend uses service_role, which bypasses RLS.
--     All remark read/write goes through admin-only endpoints
--     (require_admin on profiles.is_admin).
--   - Candidates have NO grant on assessment_attempts at all
--     (migration 005 revoked SELECT for authenticated/anon), so the
--     browser can never read the column directly.
--   - RLS is NOT disabled. The existing SELECT-own-attempts policy is
--     kept purely as defense-in-depth.
-- ============================================================

-- ============================================================
-- 1. ADD THE REMARK COLUMN
-- ============================================================
-- Nullable: NULL means "no remark" (button renders faded/disabled).

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS admin_remark TEXT;

-- ============================================================
-- 2. EXPLICIT GRANTS (idempotent re-assertion, matches migration 005)
-- ============================================================
-- service_role keeps full access (used by FastAPI admin endpoints).
GRANT ALL ON public.assessment_attempts TO service_role;

-- Defense-in-depth: the candidate roles must have no direct access to
-- assessment_attempts (already revoked in migration 005; re-asserted here
-- so this migration is self-contained and safe on fresh databases too).
REVOKE ALL ON public.assessment_attempts FROM authenticated;
REVOKE ALL ON public.assessment_attempts FROM anon;

-- ============================================================
-- 3. RLS: UNCHANGED
-- ============================================================
-- RLS stays ENABLED on assessment_attempts with the existing
-- "Users can view own attempts" SELECT policy (migration 003) intact.
-- No new policy is needed: admins never touch this table as the
-- `authenticated` role (they go through FastAPI/service_role), and
-- candidates have no grant, so RLS never exposes admin_remark.
-- DO NOT add a "read own rows" policy that returns admin_remark to
-- candidates — the FastAPI layer is the only reader.

-- ============================================================
-- 4. OPTIONAL INDEX (admin dashboards filter/search remarks)
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_attempts_admin_remark
    ON public.assessment_attempts(admin_remark)
    WHERE admin_remark IS NOT NULL;

-- ============================================================
-- Verification (run manually after applying):
--   SELECT column_name, data_type FROM information_schema.columns
--   WHERE table_schema = 'public'
--     AND table_name = 'assessment_attempts'
--     AND column_name = 'admin_remark';
-- Should return exactly one row of type text.
-- ============================================================
