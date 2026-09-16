-- ============================================================
-- Migration 017: Assessment plan snapshot on assessment_attempts
-- ============================================================
-- PHASE 5 (plan persistence). Adds three columns to store the
-- frozen assessment plan resolved by the modular planner. This
-- supplements — but does not replace — the existing frozen
-- selection columns (selected_question_ids, total_questions, etc.)
-- which remain the single source of truth for backwards-
-- compatible legacy attempts.
--
-- WHY THESE COLUMNS EXIST
--   Legacy attempts (created before the modular planner) have no
--   plan snapshot. Their plan IS NULL. They continue to work
--   through the existing lifecycle unchanged.
--   New attempts (created through the planner) store the complete
--   AssessmentPlan as JSON, plus the decomposed base/additional
--   duration components, so the resolved configuration is always
--   reproducible and auditable.
--
-- DESIGN RULES
--   - plan IS NULL → legacy attempt. Not backfilled.
--   - plan JSONB   → new attempt. Populated at creation only.
--   - base_duration_minutes and additional_minutes are the
--     decomposed components of duration_minutes for audit.
--   - duration_minutes remains the authoritative timer source.
--   - No existing rows are modified or backfilled.
--   - No policies, grants, indexes or triggers are added.
-- RERUN-SAFE (idempotent): ADD COLUMN IF NOT EXISTS.
-- ============================================================

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS plan JSONB NULL;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS base_duration_minutes INTEGER NULL;

ALTER TABLE public.assessment_attempts
    ADD COLUMN IF NOT EXISTS additional_minutes INTEGER NOT NULL DEFAULT 0;
