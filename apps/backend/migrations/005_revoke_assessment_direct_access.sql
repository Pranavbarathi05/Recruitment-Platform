-- ============================================================
-- Migration 005: Revoke Candidate Direct Access to Assessment Tables
-- ============================================================
-- Purpose:
--   Candidates access assessment data ONLY through FastAPI
--   (which uses service_role, bypassing RLS). The authenticated
--   role currently has GRANT SELECT on assessment_attempts and
--   assessment_answers, which means a candidate could use the
--   Supabase JS client to directly query scoring fields:
--     - score, max_score (assessment_attempts)
--     - is_correct (assessment_answers)
--
-- This migration revokes those direct SELECT permissions,
-- closing the only remaining path for candidates to retrieve
-- scoring information outside the controlled FastAPI layer.
--
-- The RLS policies from migration 003 are preserved as
-- defense-in-depth, though they are now functionally redundant
-- for the authenticated role (no GRANT = no access).
--
-- service_role is NOT affected — it bypasses RLS and retains
-- all required access for the backend.
--
-- SAFE: Additive only. Revokes permissions, does not modify data.
-- ============================================================

-- ============================================================
-- 1. assessment_attempts: Revoke authenticated SELECT
-- ============================================================
-- The frontend NEVER directly queries this table.
-- All access goes through FastAPI using service_role.
-- Revoking SELECT prevents candidates from reading score,
-- max_score, selected_question_ids, or any other column
-- directly via the Supabase JS client.

REVOKE SELECT ON public.assessment_attempts FROM authenticated;
REVOKE SELECT ON public.assessment_attempts FROM anon;

-- ============================================================
-- 2. assessment_answers: Revoke authenticated SELECT
-- ============================================================
-- Same reasoning. The frontend never directly queries this.
-- Revoking prevents candidates from reading is_correct,
-- selected_option, or any other answer data directly.

REVOKE SELECT ON public.assessment_answers FROM authenticated;
REVOKE SELECT ON public.assessment_answers FROM anon;

-- ============================================================
-- 3. Verify service_role retains access (defensive check)
-- ============================================================
-- service_role bypasses RLS entirely, so REVOKE from
-- authenticated/anon does not affect it. The backend can
-- still read/write all assessment tables normally.
-- No additional GRANTs needed here — migration 003 already
-- granted service_role ALL on all tables.

-- No action required. This comment documents the verification.

-- ============================================================
-- SECURITY MODEL SUMMARY (post-migration)
-- ============================================================
--
-- | Table                  | authenticated    | anon    | service_role |
-- |------------------------|------------------|---------|--------------|
-- | profiles               | SELECT, UPDATE* | SELECT  | ALL          |
-- | candidates             | SELECT           | none    | ALL          |
-- | domains                | SELECT           | SELECT  | ALL          |
-- | mcq_questions          | none             | none    | ALL          |
-- | assessment_config      | none             | none    | ALL          |
-- | assessment_attempts    | none  ← NEW      | none    | ALL          |
-- | assessment_answers     | none  ← NEW      | none    | ALL          |
--
-- * profiles UPDATE restricted to (full_name, email) columns only
--
-- Candidate data access path:
--   Browser → JWT → FastAPI → service_role → PostgreSQL
--   (never direct Supabase → PostgreSQL)
