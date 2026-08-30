-- ============================================================
-- Migration 002: Remove obsolete 'CSE' default from candidates.branch
-- ============================================================
-- The candidates.branch column was created with DEFAULT 'CSE'.
-- Branch values are now controlled at the application layer
-- (Signup.jsx dropdown). This migration removes the default
-- so that branch is a required, non-defaulted TEXT column.
--
-- SAFE: Does not modify existing rows or drop any tables.
-- ============================================================

-- 1. Remove the DEFAULT from candidates.branch
ALTER TABLE public.candidates
    ALTER COLUMN branch DROP DEFAULT;

-- 2. Replace the handle_new_user() trigger to remove the
--    COALESCE fallback to 'CSE'. If branch is not provided,
--    we still store NULL rather than a stale default.
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
DECLARE
    v_full_name TEXT;
    v_email TEXT;
    v_usn TEXT;
    v_semester INTEGER;
    v_branch TEXT;
BEGIN
    -- Extract fields from Supabase Auth metadata
    v_full_name := COALESCE(NEW.raw_user_meta_data->>'full_name', '');
    v_email := COALESCE(NEW.email, '');
    v_usn := NEW.raw_user_meta_data->>'usn';
    v_semester := (NEW.raw_user_meta_data->>'semester')::INTEGER;
    v_branch := NEW.raw_user_meta_data->>'branch';

    -- 1. Always create the profile
    INSERT INTO public.profiles (id, full_name, email)
    VALUES (NEW.id, v_full_name, v_email);

    -- 2. Create candidate row if the required fields are present
    IF v_usn IS NOT NULL AND v_usn != '' THEN
        INSERT INTO public.candidates (profile_id, usn, semester, branch)
        VALUES (
            NEW.id,
            v_usn,
            COALESCE(v_semester, 1),
            v_branch
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = public;
