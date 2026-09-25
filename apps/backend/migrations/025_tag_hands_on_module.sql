-- ============================================================
-- Migration 025: Tag hands_on_module on the SQL-challenge domains
-- ============================================================
-- Populates assessment_module_config.hands_on_module (added by migration
-- 024) from the challenges the domain actually runs, so the planner can
-- deduplicate hands-on requirements across the selected domains:
--
--   App Development + Web Development  -> ONE SQL challenge
--   App Development + DevOps           -> ONE SQL challenge
--   Web Development  + DevOps          -> ONE SQL challenge
--
-- and leaves genuinely different modules (e.g. SQL + pandas) as two
-- separate requirements.
--
-- SOURCE OF TRUTH
--   Module identity is hands_on_questions.challenge_type. A config row is
--   auto-tagged ONLY when every active challenge overlapping its domain
--   resolves to ONE single challenge type (the SQL challenge today). A
--   domain with a mixed or empty pool is deliberately left NULL: the
--   planner then keeps the conservative per-domain allocation, and an
--   operator sets the module explicitly via the admin API instead of the
--   migration guessing.
--
-- SAFE: Data-only; clears nothing that is already set. RERUN-SAFE: the
--   WHERE clauses are false once the rows are tagged.
-- ============================================================

UPDATE public.assessment_module_config c
SET hands_on_module = t.challenge_type
FROM (
    SELECT d.id AS domain_id, ct.challenge_type
    FROM public.domains d
    JOIN LATERAL (
        SELECT h.challenge_type
        FROM public.hands_on_questions h
        WHERE h.is_active AND d.id = ANY (h.domain_ids)
        GROUP BY h.challenge_type
        HAVING COUNT(DISTINCT h.challenge_type) = 1
    ) ct ON true
) t
WHERE c.domain_id = t.domain_id
  AND c.hands_on_enabled
  AND c.hands_on_module IS NULL;

-- ============================================================
-- Verification (run manually after applying):
--   SELECT domain_id, applies_to, hands_on_enabled, hands_on_module
--   FROM public.assessment_module_config
--   WHERE hands_on_enabled
--   ORDER BY domain_id, applies_to;
--   -- every enabled row whose domain runs only the SQL challenge now
--   -- carries hands_on_module = 'sql_injection_employee_portal'
-- ============================================================
