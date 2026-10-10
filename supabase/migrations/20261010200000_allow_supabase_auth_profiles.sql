-- Supabase Auth owns password storage. New confirmed accounts are linked to
-- signup_users by sync_confirmed_auth_profile(), which must not need a legacy
-- application password column to create the profile.
ALTER TABLE public.signup_users
    ALTER COLUMN password DROP NOT NULL;
