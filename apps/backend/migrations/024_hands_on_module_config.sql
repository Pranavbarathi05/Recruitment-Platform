-- ============================================================
-- Migration 024: hands_on_module on assessment_module_config
-- ============================================================
-- Declares WHICH hands-on challenge module a domain's hands-on module row
-- installs (e.g. 'sql_injection_employee_portal', 'sql_wasm',
-- 'pandas_wasm'). The planner groups same-module requirements across the
-- selected domains: one group quota = the LARGEST per-domain request (never
-- the sum), and every challenge drawn for the group counts towards each
-- member domain's requirement.
--
-- DevOps + Web Development both enable the SQL module -> the candidate
-- performs exactly ONE SQL challenge and it satisfies both domains.
-- Domains with genuinely different modules stay in separate groups.
--
-- NULL (the default) keeps the pre-module behaviour: the planner falls back
-- to per-challenge deduplication. Legacy rows stay valid; authors opt in by
-- setting the column.
--
-- SAFE: Additive only. RERUN-SAFE: IF NOT EXISTS.
-- ============================================================

ALTER TABLE public.assessment_module_config
    ADD COLUMN IF NOT EXISTS hands_on_module TEXT;
