-- ============================================================
-- Migration 018: assessment_program.mcq_total (derived technical MCQ)
-- ============================================================
-- FINAL CORE assessment architecture. Adds ONE column to the existing
-- public.assessment_program table. It changes no other table and no
-- existing data.
--
-- WHY THIS COLUMN EXISTS
--   The final assessment model fixes the technical MCQ quantity as a
--   PROGRAM-level rule, not a per-domain configuration value:
--
--       one selected domain  -> 20 MCQs
--       two selected domains -> 10 MCQs from each domain
--
--   i.e. every technical candidate receives the SAME TOTAL (20),
--   split evenly across the selected domains. That total is a property
--   of the assessment programme, so it lives here, next to the other
--   programme-level policy (scope / tier / max_domains / coding_enabled).
--
-- WHY NOT assessment_module_config.mcq_count
--   mcq_count is keyed by (domain_id, applies_to) — one fixed number
--   per domain and tier, independent of how many domains the candidate
--   selected. It therefore CANNOT express the 20-or-10 split: authoring
--   mcq_count = 20 would hand a two-domain candidate 40 MCQs (20+20),
--   and authoring 10 would hand a single-domain candidate only 10.
--   Technical MCQ quantity is consequently no longer read from
--   mcq_count at all; that column remains the configurable quantity for
--   the ORGANIZATIONAL scope, where the admin genuinely chooses it.
--
-- THE 40-QUESTION POOLS ARE CONTENT, NOT CONFIGURATION
--   The separate "40 active MCQs per domain per tier" (semester 3 for
--   junior, semester 5 for senior) is a QUESTION-BANK inventory
--   requirement. It is deliberately NOT represented here and NOT
--   enforced by a constraint: the pool size is data, and the planner
--   already fails loudly when a pool cannot satisfy the derived count.
--
-- SPLIT DIVISIBILITY
--   mcq_total must divide evenly by the number of selected domains. The
--   CHECK below only asserts positivity; the planner refuses an
--   indivisible total at plan time (INVALID_PROGRAM) rather than
--   silently rounding, because a remainder would mean the candidate
--   receives a different total than the programme specifies.
--
-- DEFAULT 20
--   Matches the final requirement exactly and keeps every existing
--   programme row correct without a backfill.
--
-- SAFE: Additive only. NOT NULL with a default, so existing rows are
--   valid immediately and no UPDATE/backfill is required.
-- RERUN-SAFE: ADD COLUMN IF NOT EXISTS; constraint dropped/re-added
--   (matching the migration 015 domains_assessment_scope_check pattern).
-- ============================================================

-- ============================================================
-- 1. ADD THE COLUMN
-- ============================================================

ALTER TABLE public.assessment_program
    ADD COLUMN IF NOT EXISTS mcq_total INTEGER NOT NULL DEFAULT 20;

-- ============================================================
-- 2. CHECK CONSTRAINT
-- ============================================================
-- A technical assessment cannot present zero MCQs, and a negative or
-- zero total would make the derived split meaningless. Upper bound is
-- generous (the exact 20 is a programme value, not a schema rule).

ALTER TABLE public.assessment_program
    DROP CONSTRAINT IF EXISTS assessment_program_mcq_total_check;

ALTER TABLE public.assessment_program
    ADD CONSTRAINT assessment_program_mcq_total_check
    CHECK (mcq_total > 0 AND mcq_total <= 200);

-- ============================================================
-- Verification (run manually after applying):
--   SELECT semester, scope, tier, max_domains, coding_enabled, mcq_total
--   FROM public.assessment_program ORDER BY semester;
-- Must show mcq_total = 20 on all four rows:
--   1 | organizational | NULL   | 1 | false | 20
--   3 | technical      | junior | 2 | true  | 20
--   5 | technical      | senior | 2 | true  | 20
--   7 | none           | NULL   | 1 | false | 20
--
--   -- positivity must be constrained:
--   UPDATE public.assessment_program SET mcq_total = 0 WHERE semester = 3;    -- ERROR
--   UPDATE public.assessment_program SET mcq_total = -5 WHERE semester = 3;   -- ERROR
-- ============================================================
