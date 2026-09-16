-- ============================================================
-- Migration 015: domains.assessment_scope + Organizational Roles domain
-- ============================================================
-- PHASE 2 (schema foundations only). Adds ONE column to the existing
-- public.domains table and inserts ONE new domain. It changes no
-- other table and no application behaviour.
--
-- WHY THIS COLUMN EXISTS
--   Until now every domain was implicitly "a technical subject you
--   pick from a list". The approved architecture introduces a second
--   KIND of assessment: the Organizational Roles assessment for
--   semester 1, whose configuration is COMMON across semesters and
--   whose content is not a technical specialization.
--
--   assessment_scope is therefore a property of the DOMAIN (what kind
--   of assessment it belongs to), NOT a property of the semester. It
--   is deliberately NOT a semester key: the same organizational
--   configuration applies no matter which semester reaches it.
--
-- WHY NOT A SEPARATE TABLE
--   The organizational assessment is still a domain: it is selected
--   like a domain, candidates are capped by the same max_domains
--   rule, and its questions live in the same mcq_questions table.
--   A one-column discriminator keeps the existing domain selection,
--   filtering, and admin infrastructure untouched.
--
-- domains.duration_minutes IS NOT TOUCHED
--   It stays exactly as it is and remains DEPRECATED/INERT. The
--   organizational domain row below gets the same default the other
--   domains have, purely to satisfy the existing NOT NULL constraint.
--   Nothing reads it, and this migration does not begin reading it.
--   The timer stays global + assessment_program/module-config driven.
--
-- NO SEMESTER-SPECIFIC DOMAIN ROWS
--   The Organizational Roles domain is a single row. It is NOT
--   duplicated per semester, and no existing domain is duplicated.
--
-- SAFE: Additive only. Existing domains keep working unchanged; the
--   new column defaults to 'technical' so every pre-existing row is
--   correct without a backfill.
-- RERUN-SAFE: ADD COLUMN IF NOT EXISTS; constraint dropped/re-added;
--   seed upserts on the existing UNIQUE(slug) constraint.
-- ============================================================

-- ============================================================
-- 1. ADD THE COLUMN
-- ============================================================
-- NOT NULL DEFAULT 'technical': every existing domain is a technical
-- domain, so the default is correct for all current rows and no
-- separate backfill is required.

ALTER TABLE public.domains
    ADD COLUMN IF NOT EXISTS assessment_scope TEXT NOT NULL DEFAULT 'technical';

-- ============================================================
-- 2. CHECK CONSTRAINT
-- ============================================================
-- Dropped-then-added so the migration is rerun-safe (matching the
-- assessment_attempts_status_check pattern in migration 008).

ALTER TABLE public.domains
    DROP CONSTRAINT IF EXISTS domains_assessment_scope_check;

ALTER TABLE public.domains
    ADD CONSTRAINT domains_assessment_scope_check
    CHECK (assessment_scope IN ('technical', 'organizational'));

-- ============================================================
-- 3. ASSERT THE EXISTING FIVE DOMAINS ARE TECHNICAL
-- ============================================================
-- These five rows were seeded in migration 001 and already satisfy
-- the column default. This statement is an explicit, idempotent
-- assertion of the requirement that they remain technical — it is a
-- no-op on any database where they are already correct, and it never
-- inserts or deletes a domain.
--
-- NOTE: it deliberately targets ONLY these five slugs. It does not
-- blanket-update the table, so any domain an admin has since
-- classified as 'organizational' is left alone.

UPDATE public.domains
SET assessment_scope = 'technical'
WHERE slug IN (
    'machineLearning',
    'webDevelopment',
    'userInterface',
    'cyberSecurity',
    'backendDevelopment'
)
AND assessment_scope <> 'technical';

-- ============================================================
-- 4. INSERT THE ORGANIZATIONAL ROLES DOMAIN
-- ============================================================
-- Follows the migration 001 seed conventions: name, slug,
-- duration_minutes, is_active. `description` is set in the same
-- sentence style used by the migration 003 description seeds.
--
-- duration_minutes = 20 is the column default used by every other
-- domain row and is INERT (the timer does not read it).
--
-- ON CONFLICT (slug) DO UPDATE: guarantees assessment_scope is
-- 'organizational' even if the row already exists (e.g. an admin
-- created it by hand first and it took the 'technical' default).
-- Enforcing the invariant is the point of this migration, so DO
-- NOTHING would be too weak here.

INSERT INTO public.domains (
    name, slug, duration_minutes, is_active, description, assessment_scope
) VALUES (
    'Organizational Roles',
    'organizationalRoles',
    20,
    true,
    'Assess your understanding of organizational structures, team roles, and professional responsibilities.',
    'organizational'
)
ON CONFLICT (slug) DO UPDATE
    SET assessment_scope = 'organizational';

-- ============================================================
-- Verification (run manually after applying):
--   SELECT slug, assessment_scope, is_active
--   FROM public.domains ORDER BY assessment_scope, slug;
-- Must show:
--   organizationalRoles  | organizational | true
--   backendDevelopment   | technical      | true
--   cyberSecurity        | technical      | true
--   machineLearning      | technical      | true
--   userInterface        | technical      | true
--   webDevelopment       | technical      | true
--
--   -- scope must be constrained:
--   UPDATE public.domains SET assessment_scope = 'bogus'
--   WHERE slug = 'cyberSecurity';   -- ERROR
--
--   -- exactly ONE organizational domain, and NO per-semester rows:
--   SELECT count(*) FROM public.domains
--   WHERE assessment_scope = 'organizational';   -- 1
--   SELECT count(*) FROM public.domains;          -- 6
-- ============================================================
