-- ============================================================
-- Migration 021: Activate the final technical domain catalogue
-- ============================================================
-- ROOT CAUSE THIS FIXES
--   Candidate domain availability (GET /assessment/available-domains)
--   resolves the candidate's semester to an assessment_program scope and
--   then returns domains where:
--
--       is_active = true AND assessment_scope = <programme scope>
--
--   The technical catalogue rows (Web Development, Machine Learning,
--   DevOps) exist and already carry assessment_scope = 'technical', but
--   they are is_active = false. A 3rd/5th semester candidate therefore
--   gets only the one remaining active technical domain (Cyber Security),
--   even though the other technical domains are configured and listed in
--   the Admin panel (which lists EVERY domain, active or not, with only a
--   small Active/Inactive badge).
--
--   Migration 019 added DevOps and reactivated Cyber Security, but it
--   assumed Web Development / Machine Learning were still active. On this
--   database they are not, so the final technical catalogue was never
--   actually reachable. This migration closes that gap.
--
-- WHAT THIS IS NOT
--   It is NOT "make all domains visible": only the documented final
--   technical catalogue is asserted active, and only those exact rows are
--   touched (matched by their UNIQUE slug). assessment_scope is
--   re-asserted as 'technical' in the same statement, so each row can only
--   ever be offered to a technical programme.
--
-- DELIBERATELY NOT TOUCHED: App Development (backendDevelopment) and
--   Test (userInterface). They are not part of the final technical
--   catalogue; whether they should be retired is a separate product
--   decision, so their is_active state is left exactly as an operator set
--   it. No row is inserted, deleted, renamed, or given a new scope.
--
-- SAFE: Data-only; no schema change. RERUN-SAFE: the WHERE clause is false
--   once a row already satisfies the invariant, so re-running never
--   rewrites a row and never bumps updated_at for an already-correct one.
-- ============================================================

UPDATE public.domains
SET is_active = true,
    assessment_scope = 'technical'
WHERE slug IN (
    'webDevelopment',
    'machineLearning',
    'devOps',
    'cyberSecurity'
)
AND (is_active = false OR assessment_scope <> 'technical');

-- ============================================================
-- Verification (run manually after applying):
--   SELECT slug, assessment_scope, is_active
--   FROM public.domains
--   WHERE slug IN (
--       'webDevelopment', 'machineLearning', 'devOps', 'cyberSecurity'
--   )
--   ORDER BY slug;
--   -- webDevelopment | technical | true
--   -- machineLearning | technical | true
--   -- devOps          | technical | true
--   -- cyberSecurity   | technical | true
--
--   -- and the two non-catalogue rows must be unchanged:
--   SELECT slug, is_active FROM public.domains
--   WHERE slug IN ('backendDevelopment', 'userInterface');
-- ============================================================
