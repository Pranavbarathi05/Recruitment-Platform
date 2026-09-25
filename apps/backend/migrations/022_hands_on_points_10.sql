-- Hands-On challenges are worth 10 points.
--
-- Source of truth for Hands-On scoring: hands_on_questions.points. The
-- backend awards exactly this value when a challenge validates (or a flag
-- matches) and 0 otherwise, and the candidate-facing questions endpoint
-- returns it as part of the challenge row.
--
-- Until now the column defaulted to 100 and every seeded row carried 100,
-- so candidates saw "100 pts". Align the default AND every existing row to
-- 10. MCQ and coding scoring (separate tables/columns) are untouched.

ALTER TABLE public.hands_on_questions
    ALTER COLUMN points SET DEFAULT 10;

UPDATE public.hands_on_questions
    SET points = 10
    WHERE points <> 10;
