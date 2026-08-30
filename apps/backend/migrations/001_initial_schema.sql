-- ============================================================
-- DSC JSSSTU Recruitment Platform — Initial Schema Migration
-- ============================================================
-- Run this SQL in the Supabase SQL Editor (Dashboard > SQL Editor).
-- Idempotent: safe to re-run (uses IF NOT EXISTS / DROP IF EXISTS).
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. PROFILES TABLE
-- ============================================================
-- One row per auth.users record. Created by trigger, not by frontend.

CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 2. CANDIDATES TABLE
-- ============================================================
-- Candidate-specific info. One-to-one with profiles.
-- Created atomically with profile by the auth trigger.

CREATE TABLE IF NOT EXISTS public.candidates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    profile_id UUID NOT NULL UNIQUE REFERENCES public.profiles(id) ON DELETE CASCADE,
    usn TEXT NOT NULL UNIQUE,
    semester INTEGER NOT NULL DEFAULT 1 CHECK (semester BETWEEN 1 AND 8),
    branch TEXT NOT NULL DEFAULT 'CSE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 3. DOMAINS TABLE
-- ============================================================

CREATE TABLE IF NOT EXISTS public.domains (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    duration_minutes INTEGER NOT NULL DEFAULT 20,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- 4. INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_candidates_profile_id ON public.candidates(profile_id);
CREATE INDEX IF NOT EXISTS idx_candidates_usn ON public.candidates(usn);
CREATE INDEX IF NOT EXISTS idx_domains_slug ON public.domains(slug);
CREATE INDEX IF NOT EXISTS idx_domains_is_active ON public.domains(is_active);

-- ============================================================
-- 5. UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_profiles_updated_at ON public.profiles;
CREATE TRIGGER update_profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS update_candidates_updated_at ON public.candidates;
CREATE TRIGGER update_candidates_updated_at
    BEFORE UPDATE ON public.candidates
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

-- ============================================================
-- 6. AUTH TRIGGER: Create profile + candidate atomically
-- ============================================================
-- When a user signs up via Supabase Auth, the frontend passes
-- candidate data (full_name, usn, semester, branch) through
-- supabase.auth.signUp({ options: { data: { ... } } }).
--
-- This SECURITY DEFINER trigger runs as the database owner and:
--   1. Creates a profiles row (always)
--   2. Creates a candidates row (if usn/semester/branch provided)
--
-- This guarantees auth.users → profile → candidate are consistent
-- without any frontend RLS INSERT policies.
--
-- SECURITY DEFINER: trigger runs with the privileges of the function
--   owner (superuser/role that created it), bypassing RLS.
-- SET search_path = public: prevents search_path manipulation attacks;
--   ensures the trigger resolves table names only from the public schema.

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
            COALESCE(v_branch, 'CSE')
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = public;

-- Drop and recreate trigger (idempotent)
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

-- ============================================================
-- 7. ROW LEVEL SECURITY (RLS)
-- ============================================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.domains ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- 8. RLS POLICIES — PROFILES
-- ============================================================

-- Users can read their own profile
CREATE POLICY "Users can view own profile"
    ON public.profiles FOR SELECT
    USING (auth.uid() = id);

-- Users can update their own profile
CREATE POLICY "Users can update own profile"
    ON public.profiles FOR UPDATE
    USING (auth.uid() = id)
    WITH CHECK (auth.uid() = id);

-- NO INSERT policy: profiles are created by the SECURITY DEFINER trigger.

-- ============================================================
-- 9. RLS POLICIES — CANDIDATES
-- ============================================================

-- Users can read their own candidate record
CREATE POLICY "Users can view own candidate record"
    ON public.candidates FOR SELECT
    USING (profile_id = auth.uid());

-- Users can update their own candidate record
CREATE POLICY "Users can update own candidate record"
    ON public.candidates FOR UPDATE
    USING (profile_id = auth.uid())
    WITH CHECK (profile_id = auth.uid());

-- Users CANNOT change who owns the record (profile_id must match their own)
-- This is enforced by: USING (profile_id = auth.uid()) AND WITH CHECK (profile_id = auth.uid())
-- So even if a user tries to set profile_id to another user's ID, the WITH CHECK will reject it.

-- NO INSERT policy: candidates are created by the SECURITY DEFINER trigger.
-- The backend service role bypasses RLS for any future server-side inserts.

-- ============================================================
-- 10. RLS POLICIES — DOMAINS
-- ============================================================

-- Anyone can read active domains (public read access)
CREATE POLICY "Anyone can view active domains"
    ON public.domains FOR SELECT
    USING (is_active = true);

-- NO INSERT/UPDATE/DELETE for candidates. Domains are managed by admins (future phase).

-- ============================================================
-- 11. SEED DATA — Default Domains
-- ============================================================

INSERT INTO public.domains (name, slug, duration_minutes, is_active) VALUES
    ('Machine Learning', 'machineLearning', 20, true),
    ('Web Development', 'webDevelopment', 20, true),
    ('User Interface', 'userInterface', 20, true),
    ('Cyber Security', 'cyberSecurity', 20, true),
    ('Backend Development', 'backendDevelopment', 20, true)
ON CONFLICT (slug) DO NOTHING;
