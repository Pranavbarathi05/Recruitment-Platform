-- ============================================================
-- Migration 013: Hands-On score columns on assessment_attempts
-- ============================================================
-- FIXES: POST /assessment/attempt/{id}/submit failing with
--   APIError PGRST204: "Could not find the 'hands_on_max_score' column of
--   'assessment_attempts' in the schema cache"
-- which left every attempt status='in_progress' (resumable, timer kept
-- running) even though the UI showed success — _score_attempt() wrote
-- hands_on_score / hands_on_max_score before the finalization update, but no
-- migration had ever created those columns (012 added only the selection
-- columns; 006 established the sibling mcq_score/coding_score pattern).
--
-- Additive and data-preserving: two nullable INTEGER columns, defaults 0,
-- matching the mcq_score / mcq_max_score / coding_score / coding_max_score
-- columns from migration 006. No policies, grants, indexes or triggers.
-- RERUN-SAFE (idempotent).
-- ============================================================

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS hands_on_score INTEGER DEFAULT 0;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS hands_on_max_score INTEGER DEFAULT 0;
