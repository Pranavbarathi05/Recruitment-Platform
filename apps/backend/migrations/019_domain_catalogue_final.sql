-- ============================================================
-- Migration 019: Final technical domain catalogue (DevOps + Cyber Security)
-- ============================================================
-- FINAL CORE assessment architecture. DATA-ONLY migration: it changes
-- no schema. It performs two catalogue corrections required by the
-- final technical domain list:
--
--   technical:      Web Development, Machine Learning,
--                   Cyber Security, DevOps
--   organizational: Organizational Roles
--
--   1. INSERT the DevOps domain (it does not exist yet).
--   2. ACTIVATE Cyber Security (it exists but is is_active = false,
--      so it is currently invisible to /assessment/available-domains
--      and rejected by the planner as DOMAIN_INACTIVE).
--
-- NOT APPLIED AUTOMATICALLY
--   This migration is authored for later review and application. It has
--   been verified against a throwaway PostgreSQL instance only. Nothing
--   here has been run against the shared DEV/production Supabase
--   database, and no real assessment data is modified by authoring it.
--
-- WHY AN INSERT FOR DevOps
--   The final catalogue needs four technical domains but only three
--   exist. Following the migration 015 convention for Organizational
--   Roles: one row, no per-semester duplication, duration_minutes left
--   at the inert 20 default (domains.duration_minutes remains
--   DEPRECATED and is still not read by the timer).
--
-- WHY AN UPDATE FOR CYBER SECURITY
--   Cyber Security already exists as a technical domain but is
--   deactivated. The final model gives it a senior practical (the
--   existing SQL Injection Hands-on), which requires the domain to be
--   selectable again. The UPDATE is targeted at ONE slug and asserts
--   the two invariants the planner depends on: scope = 'technical'
--   (so it is only ever offered to technical programmes) and
--   is_active = true.
--
-- DELIBERATELY NOT TOUCHED: Backend Development and User Interface
--   They are not in the final technical list, but their fate is a
--   separate product decision. This migration neither deactivates nor
--   renames them. They remain active technical domains; if they should
--   be retired, that is a later, explicit change.
--
-- DELIBERATELY NOT TOUCHED: question banks and module configuration
--   No MCQs, no descriptive questions, no hands-on challenges and no
--   assessment_module_config rows are created here. Content authoring
--   is a separate phase.
--
-- SAFE: Data-only; additive (one INSERT, one targeted UPDATE). No row
--   is deleted and no other domain is altered.
-- RERUN-SAFE: the INSERT conflicts on the existing UNIQUE(slug)
--   constraint and updates nothing (DO NOTHING), so re-running never
--   rewrites a domain an admin has since edited; the UPDATE is a no-op
--   once the row already satisfies the invariant.
-- ============================================================

-- ============================================================
-- 1. INSERT THE DevOps DOMAIN
-- ============================================================
-- assessment_scope is 'technical' explicitly (rather than relying on the
-- column default) so this statement states its own intent.
--
-- DO NOTHING (not DO UPDATE, unlike migration 015): migration 015 had to
-- force an invariant an admin could plausibly get wrong. Here the
-- invariant is simply "this row exists"; if an admin has already created
-- a DevOps domain by hand, that row is left exactly as authored.

INSERT INTO public.domains (
    name, slug, duration_minutes, is_active, description, assessment_scope
) VALUES (
    'DevOps',
    'devOps',
    20,
    true,
    'Assess your understanding of CI/CD pipelines, infrastructure automation, containerisation, and reliable deployment practices.',
    'technical'
)
ON CONFLICT (slug) DO NOTHING;

-- ============================================================
-- 2. ACTIVATE CYBER SECURITY
-- ============================================================
-- Targeted at exactly one slug. Also re-asserts assessment_scope =
-- 'technical', because the planner only offers a domain to a programme
-- whose scope matches, and the senior Cyber Security practical depends
-- on the domain being both active and technical.

UPDATE public.domains
SET is_active = true,
    assessment_scope = 'technical'
WHERE slug = 'cyberSecurity'
AND (is_active = false OR assessment_scope <> 'technical');

-- ============================================================
-- Verification (run manually after applying):
--   SELECT slug, assessment_scope, is_active
--   FROM public.domains ORDER BY assessment_scope, slug;
-- Must show at least:
--   organizationalRoles  | organizational | true
--   cyberSecurity        | technical      | true   <-- reactivated
--   devOps               | technical      | true   <-- new
--   machineLearning      | technical      | true
--   webDevelopment       | technical      | true
--
--   -- the exact final technical catalogue:
--   SELECT slug FROM public.domains
--   WHERE assessment_scope = 'technical' AND is_active
--   ORDER BY slug;
--   -- devOps, cyberSecurity, machineLearning, webDevelopment
--   -- (plus backendDevelopment / userInterface if still active)
--
--   -- exactly one organizational domain is preserved:
--   SELECT count(*) FROM public.domains
--   WHERE assessment_scope = 'organizational';   -- 1
-- ============================================================
